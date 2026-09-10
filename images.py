"""Per-book image storage for section content.

Images are written to ``books/assets/<book_id>/<uuid>.<ext>`` and referenced
from section Markdown as ``/assets/<book_id>/<uuid>.<ext>``.
"""

from __future__ import annotations

import base64
import uuid

import requests

import config
import store

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


def fetch_remote(url: str) -> bytes | None:
    """Download a remote image (size + content-type capped). None on failure."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, stream=True, timeout=(5, 20))
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
    except requests.RequestException:
        return None
