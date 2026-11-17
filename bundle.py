"""Bundle export — a book's JSON *plus* the images it references, in one zip.

The plain JSON export is lossless for the tree but not for the pictures: an
uploaded image lives in ``books/assets/<book_id>/`` (a folder the book JSON
never mentions) and a remote image lives at whatever URL it was pasted from.
Importing that JSON on another machine, or after a hosted instance wiped its
disk, therefore came back with every image broken.

This wraps the *same* JSON in a zip next to an ``Images/`` folder::

    <slug>/<slug>.json
    <slug>/Images/<slug>-<id6>-img1.png

Image filenames reuse the Pages export's per-book prefix (``pages._asset_prefix``)
so a bundle unpacked next to another book's bundle can't collide, and every
``![alt](src)`` in a section body is rewritten to ``Images/<name>`` — a path
that means something both inside the zip and to a human reading the JSON.

The round trip lives in ``app.py``'s ``/api/books/import``: a zip upload is
unpacked, the book is created, each image is copied into the new book's own
asset folder, and the ``Images/`` references are rewritten to that book's
``/assets/<new id>/`` URLs.
"""

from __future__ import annotations

import copy
import json
import re
import zipfile
from io import BytesIO

import epub as _epub
import export as _export
import pages as _pages

#: Folder name used inside the zip, and in the rewritten Markdown references.
IMAGES_DIR = "Images"

_IMG_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _rewrite_images(content: str, bag: "_epub._AssetBag") -> str:
    """Point each ``![alt](src)`` at the bundle's own ``Images/`` copy."""
    def repl(m: re.Match) -> str:
        try:
            name = bag.add(m.group(2))
        except Exception:        # a broken single image must never fail the export
            return m.group(0)
        if not name:
            return m.group(0)   # couldn't fetch it — keep the original reference
        return f"![{m.group(1)}]({IMAGES_DIR}/{name.rsplit('/', 1)[-1]})"
    return _IMG_MD.sub(repl, content)


def _walk(nodes: list[dict]):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


def book_to_bundle(book: dict, base_url: str, exclude_ids: set | None = None,
                   lite: bool = False) -> tuple[bytes, str]:
    """Build the zip. Returns ``(bytes, root folder name)``.

    ``base_url`` is only needed to fetch local ``/assets/...`` references
    (headless-free, it just hits this same server); remote URLs are fetched
    directly. ``lite`` recompresses images exactly as the PDF/EPUB exports do.
    """
    root_name = _pages._safe_name(book.get("title") or book.get("topic") or "book", set())
    nodes = copy.deepcopy(_export.filter_book_nodes(book.get("nodes") or [], exclude_ids))

    bag = _epub._AssetBag(base_url, lite=lite, prefix=_pages._asset_prefix(book, root_name))
    for node in _walk(nodes):
        if isinstance(node.get("content"), str) and node["content"]:
            node["content"] = _rewrite_images(node["content"], bag)

    payload = dict(book)
    payload["nodes"] = nodes
    payload.pop("owner", None)   # the receiving machine stamps its own owner

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{root_name}/{root_name}.json",
                    json.dumps(payload, ensure_ascii=False, indent=2))
        for name, data in bag.files.items():
            zf.writestr(f"{root_name}/{IMAGES_DIR}/{name.rsplit('/', 1)[-1]}", data)
    return buf.getvalue(), root_name


# --------------------------------------------------------------------------- #
#  Import                                                                      #
# --------------------------------------------------------------------------- #

def _looks_like_book(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list)


def read_bundle(raw: bytes) -> tuple[dict, dict[str, bytes]]:
    """Unpack an uploaded bundle into ``(book dict, {image filename: bytes})``.

    Only the outermost book JSON is taken (the shallowest file that parses to a
    real book), and image names are flattened to their basename, matching how
    the references inside the JSON are written. Anything else in the zip — a
    different book's folder, editor junk, ``__MACOSX`` — is ignored rather than
    rejected, so a hand-made zip still imports.

    Raises ``ValueError`` when no book JSON is present.
    """
    try:
        zf = zipfile.ZipFile(BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid zip file") from exc

    with zf:
        candidates = []
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".json"):
                continue
            if "__MACOSX/" in info.filename:
                continue
            try:
                parsed = json.loads(zf.read(info).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, OSError):
                continue
            if _looks_like_book(parsed):
                candidates.append((info.filename.count("/"), info.filename, parsed))
        if not candidates:
            raise ValueError("no book JSON found in the zip")
        candidates.sort(key=lambda c: (c[0], c[1]))
        _, book_name, data = candidates[0]

        # The book's own folder is the one its JSON sits in; images are only
        # taken from there, so a zip holding two bundles doesn't mix them up.
        folder = book_name.rsplit("/", 1)[0] + "/" if "/" in book_name else ""
        images: dict[str, bytes] = {}
        for info in zf.infolist():
            if info.is_dir() or "__MACOSX/" in info.filename:
                continue
            if not info.filename.startswith(folder):
                continue
            rel = info.filename[len(folder):]
            if "/" not in rel or rel.lower().endswith(".json"):
                continue
            images[rel.rsplit("/", 1)[-1]] = zf.read(info)
    return data, images


def rebind_images(book: dict, book_id: str, images: dict[str, bytes]) -> dict:
    """Rewrite ``Images/<name>`` references to ``/assets/<book_id>/<name>``.

    Also resolves the older plain-JSON case where a reference is already an
    ``/assets/<old id>/<name>`` URL whose file the zip happens to carry — that
    book's own folder is gone on this machine, so the bytes from the bundle
    are the only copy left.
    """
    if not images:
        return book

    def fix(content: str) -> str:
        def repl(m: re.Match) -> str:
            src = m.group(2)
            name = src.rsplit("/", 1)[-1]
            if name in images and (
                src.startswith(f"{IMAGES_DIR}/")
                or src.startswith("/assets/")
            ):
                return f"![{m.group(1)}](/assets/{book_id}/{name})"
            return m.group(0)
        return _IMG_MD.sub(repl, content)

    for node in _walk(book.get("nodes") or []):
        if isinstance(node.get("content"), str) and node["content"]:
            node["content"] = fix(node["content"])
    return book
