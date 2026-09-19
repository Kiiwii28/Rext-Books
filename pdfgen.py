"""Render a URL to PDF with a headless Chromium-family browser.

No Python dependency — it shells out to Chrome / Edge / Chromium if one is
installed (Edge ships with Windows 11, so this "just works" there). The output
is exactly what the /preview page looks like in the browser, with working
internal links and printed background colours.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_WIN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
_NAMES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "chrome", "msedge",
]


def find_browser() -> str | None:
    env = os.getenv("REXTBOOKS_CHROME")
    if env and Path(env).exists():
        return env
    for name in _NAMES:
        found = shutil.which(name)
        if found:
            return found
    for cand in (_WIN if os.name == "nt" else _MAC):
        if Path(cand).exists():
            return cand
    return None


def available() -> bool:
    return find_browser() is not None


def _default_timeout() -> int:
    import config   # imported lazily to avoid any import-order surprises
    return config.PDF_RENDER_TIMEOUT


def _run_with_retry(build_cmd, *, timeout: int, retries: int, prefix: str,
                    check) -> subprocess.CompletedProcess:
    """Run a headless-Chrome subprocess, retrying on a timeout or crash —
    observed in practice: a large/complex render can time out or the browser
    process itself can crash on a first attempt and succeed on a second, with
    nothing else about the request changed. Each attempt gets a brand new
    temp profile (never reuses one from a failed attempt — a crashed Chrome
    profile can leave lock files that make a retry against it fail too).

    ``build_cmd(out_dir) -> (cmd, out_path)`` builds the command for one
    attempt; ``check(proc, out_path)`` raises if that attempt's result looks
    wrong (e.g. no output file) — its exception becomes what a final failure
    raises."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        with tempfile.TemporaryDirectory(prefix=prefix) as d:
            cmd, out_path = build_cmd(Path(d))
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
                check(proc, out_path)
                return proc
            except (subprocess.TimeoutExpired, RuntimeError) as exc:
                last_exc = exc
    raise last_exc


def url_to_pdf(url: str, *, timeout: int | None = None, retries: int = 1) -> bytes:
    exe = find_browser()
    if not exe:
        raise RuntimeError("No Chrome/Edge/Chromium found for PDF rendering.")
    timeout = _default_timeout() if timeout is None else timeout
    captured: dict[str, bytes] = {}

    def build(d: Path):
        out = d / "book.pdf"
        cmd = [
            exe,
            # The old (default) "--headless" mode never populates the PDF's
            # bookmark outline regardless of --generate-pdf-document-outline —
            # verified empirically (empty outline every time). Only the newer
            # "--headless=new" mode actually generates it, which the running
            # header feature in export.py depends on to know which chapter/
            # heading is current on each page.
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            f"--user-data-dir={d / 'profile'}",
            "--no-pdf-header-footer",           # drop the date / title / URL chrome
            "--print-to-pdf-no-header",         # older flag name, harmless if unknown
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=25000",      # wait for images, fonts, Mermaid
            "--generate-pdf-document-outline",  # bookmarks/nav pane, built from <h1>-<h6>
            f"--print-to-pdf={out}",
            url,
        ]
        return cmd, out

    def check(proc, out: Path):
        # Read the bytes here, inside the temp dir's lifetime — the
        # TemporaryDirectory is deleted the moment this attempt's `with`
        # block exits (success or failure alike), so out.read_bytes() would
        # fail if deferred to after _run_with_retry returns.
        if not out.exists() or out.stat().st_size == 0:
            err = proc.stderr.decode("utf-8", "replace")[-500:]
            raise RuntimeError(f"Headless browser did not produce a PDF. {err}")
        captured["data"] = out.read_bytes()

    _run_with_retry(build, timeout=timeout, retries=retries, prefix="rext-pdf-", check=check)
    return captured["data"]


def dump_rendered_dom(url: str, *, timeout: int | None = None, retries: int = 1) -> str:
    """Load `url`, let it fully render (Mermaid diagrams, broken-image swaps)
    via the virtual time budget, and return the post-JS DOM as HTML text.

    Used by the EPUB export: EPUB readers don't run JavaScript, so Mermaid
    diagrams have to be pre-rendered to static SVG before packaging — this
    reuses the exact same rendering pass the PDF export already relies on.
    """
    exe = find_browser()
    if not exe:
        raise RuntimeError("No Chrome/Edge/Chromium found for diagram rendering.")
    timeout = _default_timeout() if timeout is None else timeout
    captured: dict[str, str] = {}

    def build(d: Path):
        cmd = [
            exe,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            f"--user-data-dir={d / 'profile'}",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=25000",
            "--dump-dom",
            url,
        ]
        return cmd, None

    def check(proc, _out):
        text = proc.stdout.decode("utf-8", "replace")
        if not text.strip():
            err = proc.stderr.decode("utf-8", "replace")[-500:]
            raise RuntimeError(f"Headless browser did not return any DOM. {err}")
        captured["text"] = text

    _run_with_retry(build, timeout=timeout, retries=retries, prefix="rext-dom-", check=check)
    return captured["text"]


def screenshot_html(html: str, width: int, height: int, *, timeout: int = 30,
                    retries: int = 1) -> bytes:
    """Render a small standalone HTML snippet and return a PNG screenshot
    (transparent background). Used to rasterize a single Mermaid diagram for
    EPUB: the diagram's live SVG uses foreignObject-embedded HTML labels and
    8-digit alpha-hex colours, both of which plenty of e-reader rendering
    engines handle poorly or not at all (dropped labels, solid-black shapes) —
    a plain image sidesteps that entirely, at the cost of no longer being
    vector. Chrome renders it correctly regardless, so a screenshot always
    matches what the PDF/app show.
    """
    exe = find_browser()
    if not exe:
        raise RuntimeError("No Chrome/Edge/Chromium found for diagram rendering.")
    captured: dict[str, bytes] = {}

    def build(d: Path):
        html_path = d / "snippet.html"
        html_path.write_text(html, encoding="utf-8")
        out = d / "out.png"
        cmd = [
            exe,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            f"--user-data-dir={d / 'profile'}",
            f"--window-size={width},{height}",
            "--hide-scrollbars",
            "--default-background-color=00000000",   # transparent PNG
            f"--screenshot={out}",
            html_path.as_uri(),
        ]
        return cmd, out

    def check(proc, out: Path):
        if not out.exists() or out.stat().st_size == 0:
            err = proc.stderr.decode("utf-8", "replace")[-500:]
            raise RuntimeError(f"Headless browser did not produce a screenshot. {err}")
        captured["data"] = out.read_bytes()

    _run_with_retry(build, timeout=timeout, retries=retries, prefix="rext-shot-", check=check)
    return captured["data"]
