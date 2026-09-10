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


def url_to_pdf(url: str, *, timeout: int = 60) -> bytes:
    exe = find_browser()
    if not exe:
        raise RuntimeError("No Chrome/Edge/Chromium found for PDF rendering.")
    with tempfile.TemporaryDirectory(prefix="rext-pdf-") as d:
        out = Path(d) / "book.pdf"
        cmd = [
            exe,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            f"--user-data-dir={Path(d) / 'profile'}",
            "--no-pdf-header-footer",           # drop the date / title / URL chrome
            "--print-to-pdf-no-header",         # older flag name, harmless if unknown
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=25000",      # wait for images, fonts, Mermaid
            f"--print-to-pdf={out}",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if not out.exists() or out.stat().st_size == 0:
            err = proc.stderr.decode("utf-8", "replace")[-500:]
            raise RuntimeError(f"Headless browser did not produce a PDF. {err}")
        return out.read_bytes()
