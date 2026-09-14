"""Per-book image storage for section content.

Images are written to ``books/assets/<book_id>/<uuid>.<ext>`` and referenced
from section Markdown as ``/assets/<book_id>/<uuid>.<ext>``.
"""

from __future__ import annotations

import base64
import re
import sys
import time
import uuid

import requests

import config
import deepseek
import store

def _log(msg: str) -> None:
    print(f"[images] {msg}", file=sys.stderr, flush=True)

MAX_BYTES = 10 * 1024 * 1024          # 10 MB
FETCH_MAX_BYTES = 10 * 1024 * 1024

# magic-byte signatures -> extension (raster formats only; no SVG on purpose)
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
]


def _sniff_ext(data: bytes) -> str | None:
    for sig, ext in _SIGNATURES:
        if data.startswith(sig):
            return ext
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_image(book_id: str, data: bytes) -> dict:
    """Validate + store raw image bytes. Returns {url, markdown}."""
    store.assets_dir(book_id)  # validates book_id, ensures dir
    if not data:
        raise ValueError("empty file")
    if len(data) > MAX_BYTES:
        raise ValueError("image is larger than 10 MB")
    ext = _sniff_ext(data)
    if ext is None:
        raise ValueError("unsupported image type (use PNG, JPEG, GIF or WebP)")

    name = f"{uuid.uuid4().hex}.{ext}"
    (config.BOOKS_DIR / "assets" / book_id / name).write_bytes(data)
    url = f"/assets/{book_id}/{name}"
    return {"url": url, "markdown": f"![]({url})"}


def decode_data_url(data_url: str) -> bytes:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)



# --------------------------------------------------------------------------- #
#  Image search: Wikimedia Commons first, Pexels as a fallback second source   #
# --------------------------------------------------------------------------- #
#
# Wikimedia Commons is the primary source: free, no key needed, and its
# contents (historical photos, scientific diagrams, portraits, maps) are
# exactly what a textbook wants, almost always public-domain or CC-licensed
# with clear attribution metadata attached. Pexels is a secondary source for
# generic "mood" photography Commons is thin on (a stock photo of "a team
# meeting") — only queried when Commons comes up short, and only if a key is
# configured (config.get_pexels_key(); see config.py for the stub).

_WIKIMEDIA_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
_PEXELS_ENDPOINT = "https://api.pexels.com/v1/search"
_SEARCH_TIMEOUT = (5, 15)
_PEXELS_FALLBACK_THRESHOLD = 4   # only try Pexels if Commons returns fewer than this
_TAG_RE = re.compile(r"<[^>]+>")
# Wikimedia's servers hard-reject requests with no (or a generic) User-Agent —
# a 403 "Please set a user-agent" — per https://meta.wikimedia.org/wiki/User-Agent_policy.
# Applied to every outbound request here, not just the search call, since the
# actual image download (fetch_remote, below) hits upload.wikimedia.org too.
_USER_AGENT = "Rextbooks/1.0 (recursive textbook generator; local single-user app)"


def search_wikimedia(query: str, limit: int = 12) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    # Fetch a bigger pool than requested, then filter and truncate: Commons'
    # own relevance ranking for anything diagram-shaped skews heavily SVG
    # (e.g. every one of the top 10 hits for "neuron diagram" is an SVG, and
    # the raster alternatives that do exist are clustered near position
    # 35-50, not near the top) — since SVG is filtered out below, asking for
    # only `limit` candidates can leave nothing at all even when perfectly
    # good raster matches exist a bit further down the ranking.
    fetch_pool = 50
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,   # File: namespace
        "gsrlimit": fetch_pool,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        # A scaled rendition, not the raw original: Commons originals can be
        # huge (a NASA image search turned up a 12 MB original — bigger than
        # FETCH_MAX_BYTES below, silently falling back to an unsaved external
        # link instead of actually storing the picked image). 1000px is a
        # reasonable width for a textbook page either way.
        "iiurlwidth": 1000,
    }
    try:
        resp = requests.get(
            _WIKIMEDIA_ENDPOINT, params=params, timeout=_SEARCH_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        pages = (resp.json().get("query") or {}).get("pages") or {}
    except (requests.RequestException, ValueError):
        return []

    out = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = info.get("mime") or ""
        if not mime.startswith("image/") or mime == "image/svg+xml":
            # Commons files can be PDFs/audio/video too — images only. SVG is
            # excluded on purpose, same as direct upload/paste (_sniff_ext
            # above): this app never stores SVG, since an embedded <script>
            # in an "image" is a real XSS vector once it's served back out.
            continue
        meta = info.get("extmetadata") or {}
        artist = _TAG_RE.sub("", (meta.get("Artist") or {}).get("value") or "").strip() or "Unknown"
        license_name = (meta.get("LicenseShortName") or {}).get("value") or "see file page for licence"
        # Both fields point at the same ~1000px-wide rendition — plenty for a
        # textbook page, and reliably under the fetch size cap; the raw
        # `url` (original) is never used for download.
        scaled = info.get("thumburl") or info.get("url")
        out.append({
            "source": "wikimedia",
            "thumbUrl": scaled,
            "fullUrl": scaled,
            "width": info.get("thumbwidth") or info.get("width"),
            "height": info.get("thumbheight") or info.get("height"),
            "title": (page.get("title") or "").removeprefix("File:"),
            "attribution": f"{artist} — {license_name}, via Wikimedia Commons",
            "pageUrl": info.get("descriptionurl") or "",
        })
        if len(out) >= limit:
            break
    return out


def search_pexels(query: str, limit: int = 12) -> list[dict]:
    query = (query or "").strip()
    key = config.get_pexels_key()
    if not query or not key:
        return []
    try:
        resp = requests.get(
            _PEXELS_ENDPOINT,
            params={"query": query, "per_page": min(max(limit, 1), 15)},
            headers={"Authorization": key},
            timeout=_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos") or []
    except (requests.RequestException, ValueError):
        return []

    out = []
    for p in photos:
        src = p.get("src") or {}
        photographer = p.get("photographer") or "Unknown"
        out.append({
            "source": "pexels",
            "thumbUrl": src.get("medium") or src.get("small") or src.get("original"),
            "fullUrl": src.get("large2x") or src.get("large") or src.get("original"),
            "width": p.get("width"),
            "height": p.get("height"),
            "title": p.get("alt") or "Photo",
            "attribution": f"Photo by {photographer} on Pexels",
            "pageUrl": p.get("url") or "",
        })
    return out[:limit]


def search_images(query: str, limit: int = 12, source: str = "auto") -> dict:
    """`source` picks a single explicit provider ("wikimedia" or "pexels"),
    or "auto" (default) for the original Wikimedia-first, Pexels-as-fallback
    behaviour — kept for callers that don't care which source answered."""
    if source == "pexels":
        results = search_pexels(query, limit=limit)
    elif source == "wikimedia":
        results = search_wikimedia(query, limit=limit)
    else:
        wiki = search_wikimedia(query, limit=limit)
        results = wiki + (search_pexels(query, limit=limit) if len(wiki) < _PEXELS_FALLBACK_THRESHOLD else [])
    return {"results": results, "pexelsConfigured": bool(config.get_pexels_key())}


def fetch_remote(url: str, *, retries: int = 1) -> bytes | None:
    """Download a remote image (size + content-type capped). None on failure.

    One retry by default — a real Wikimedia/Pexels URL occasionally blips
    (a transient timeout or connection reset) even when the image is
    perfectly fine a moment later; worth a second attempt before treating the
    whole thing as unfetchable."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, stream=True, timeout=(5, 20), headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            if ctype and not ctype.startswith("image/"):
                return None
            chunks, total = [], 0
            for chunk in resp.iter_content(64 * 1024):
                total += len(chunk)
                if total > FETCH_MAX_BYTES:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        except requests.RequestException as exc:
            if attempt >= retries:
                _log(f"fetch_remote failed after {attempt + 1} attempt(s) for {url!r}: {exc!r}")
                return None
            time.sleep(1)   # brief backoff — covers a momentary rate-limit/blip


# --------------------------------------------------------------------------- #
#  DeepSeek-driven images: the model requests a fenced ```image-search block   #
#  (see prompts.py's use_images branch) instead of writing a Markdown image    #
#  tag itself; resolved here, after generation, into a real inserted image.    #
# --------------------------------------------------------------------------- #

_PLACEHOLDER_RE = re.compile(r"```image-search\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s*(query|caption)\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
MAX_RESOLVED_IMAGES = 8   # matches the "up to about eight" DEFAULT in prompts.py


def _parse_placeholder(body: str) -> tuple[str, str]:
    fields = {k.lower(): v.strip() for k, v in _FIELD_RE.findall(body)}
    return fields.get("query", ""), fields.get("caption", "")


def _choose_candidate(caption: str, candidates: list[dict]) -> int | None:
    """A small, cheap, non-streaming DeepSeek call picks the best-matching
    candidate by its title/attribution text (no vision model involved — this
    app never sees the actual pixels either). Returns None if nothing
    plausibly matches.

    This check is load-bearing, not a nicety: stock-photo search (Pexels)
    doesn't reliably return zero results for a query with no real match — it
    falls back to generic/trending photos instead (a nonsense query like
    "zzqqxx probably no results" still comes back with six unrelated stock
    photos). Without a genuinely skeptical judge here, a bad query silently
    inserts a random, unrelated stock photo instead of no image at all — so
    any failure in this function itself also fails closed (returns None,
    dropping the image) rather than guessing the top result."""
    if not candidates:
        return None
    listing = "\n".join(
        f'{i}. [{c["source"]}] "{c["title"]}" — {c["attribution"]}'
        for i, c in enumerate(candidates)
    )
    messages = [
        {"role": "system", "content": (
            "You are a strict, skeptical judge picking an image for a textbook "
            "caption, from a list of real image-search results — titles and "
            "attributions only, you cannot see the actual pixels. IMPORTANT: stock-"
            "photo search often returns generic or trending filler with no real "
            "connection to the query when nothing good actually matches (e.g. "
            "confetti, stock office photos, unrelated abstract art) — do not pick "
            "one of these just because it's in the list. Only pick a candidate "
            "whose title plausibly, specifically depicts what the caption "
            'describes. Reply with ONLY the number of that candidate, or the word '
            '"none" if nothing genuinely matches. No other text, no punctuation.'
        )},
        {"role": "user", "content": f'Caption: "{caption}"\n\nCandidates:\n{listing}'},
    ]
    try:
        # This model spends an unpredictable — sometimes very large (500+
        # tokens observed, no fixed ceiling found) — number of hidden
        # "reasoning" tokens before any visible output, even for a trivial
        # one-word answer, and they count against max_tokens together with
        # the real reply. Raising max_tokens (300, then 2000) only reduced
        # how often that silently produced an empty reply; it kept happening
        # at 2000 too. reasoning_effort="none" skips that pass entirely —
        # confirmed to still answer correctly on the exact prompts that were
        # coming back empty, using a single output token instead of 500+.
        reply = deepseek.chat(messages, temperature=0, max_tokens=50,
                              reasoning_effort="none").strip().lower()
    except Exception as exc:
        _log(f"chooser call failed for {caption!r}: {exc!r} — dropping image")
        return None   # chooser failed — fail closed: no image beats a wrong one
    if "none" in reply:
        _log(f"chooser said none for {caption!r} among {len(candidates)} candidate(s) — reply={reply!r}")
        return None
    m = re.search(r"\d+", reply)
    if m:
        idx = int(m.group())
        if 0 <= idx < len(candidates):
            return idx
    _log(f"chooser reply unparseable for {caption!r}: {reply!r} — dropping image")
    return None


def resolve_image_placeholders(text: str, book_id: str) -> tuple[str, int, int]:
    """Replace every ```image-search request block with a real, locally-saved
    image — searched via Wikimedia/Pexels, picked by ``_choose_candidate``
    among the actual results — or drop it silently if nothing usable turns up.
    Never raises: a failure resolving any one placeholder just drops that one,
    so a flaky search/download/chooser call can't break the whole response.
    Returns (new_text, resolved_count, placeholder_count)."""
    matches = list(_PLACEHOLDER_RE.finditer(text))
    if not matches:
        return text, 0, 0

    out: list[str] = []
    last_end = 0
    resolved = 0
    for m in matches:
        out.append(text[last_end:m.start()])
        last_end = m.end()
        replacement = ""
        if resolved < MAX_RESOLVED_IMAGES:
            query, caption = _parse_placeholder(m.group(1))
            if not query:
                _log(f"placeholder with no parseable query, raw body={m.group(1)!r} — dropping")
            else:
                try:
                    candidates = search_images(query, limit=6, source="auto")["results"]
                    if not candidates:
                        _log(f"zero search results for query={query!r}")
                    idx = _choose_candidate(caption or query, candidates)
                    if idx is None:
                        _log(f"no image used for query={query!r} ({len(candidates)} candidate(s) offered)")
                    if idx is not None:
                        chosen = candidates[idx]
                        fetched = fetch_remote(chosen["fullUrl"])
                        if not fetched:
                            _log(f"fetch_remote failed for chosen candidate: {chosen['fullUrl']!r}")
                        else:
                            saved = save_image(book_id, fetched)
                            alt = (caption or query).replace("[", "").replace("]", "")
                            replacement = f"![{alt}]({saved['url']})\n*{chosen['attribution']}*"
                            resolved += 1
                except Exception as exc:
                    import traceback
                    _log(f"unhandled exception resolving query={query!r}: {exc!r}")
                    traceback.print_exc(file=sys.stderr)
                    replacement = ""
        out.append(replacement)
    out.append(text[last_end:])
    return "".join(out), resolved, len(matches)
