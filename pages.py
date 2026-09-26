"""Pages export — a folder of Markdown notes mirroring a book's outline,
shaped for dropping straight into an Obsidian vault.

Design, matching how Obsidian itself resolves links (confirmed against a
real vault: ``![[Pasted image ....png]]`` embeds resolve by filename alone,
no attachment-folder convention required):

- Every container level (a heading, or a subheading that itself has nested
  subheadings) becomes a folder with a same-named "overview" note holding
  links to its own children — Obsidian's "folder note" convention.
- A subheading with no children of its own (a leaf) becomes one note in its
  parent's folder, holding its section's content.
- All images live in one shared ``assets/`` folder at the book's root and
  are referenced by every note via ``![[filename]]`` — filename-based
  resolution means this works regardless of how deeply a note is nested,
  with no relative-path arithmetic anywhere.
- Notes link to each other via *full vault-path* wikilinks
  (``[[Chapter 1/Some Subheading|Some Subheading]]``), not bare titles —
  two different subheadings anywhere in the book can share a title without
  colliding, since Obsidian's bare-title link resolution isn't relied on.

Reuses ``epub._AssetBag`` for image fetching/dedup/Lite-mode compression —
same job (resolve a book's mixed local/remote image references to actual
bytes, once each), just re-homed under one flat ``assets/`` folder instead
of an EPUB container's ``images/`` manifest entries.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import config
import epub as _epub
import export as _export
import pdfgen
from epub import _AssetBag
from rendering import strip_unresolved_image_placeholders

_IMG_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
_MERMAID_FENCE = re.compile(r"```mermaid\s*\n.*?```\n?", re.DOTALL | re.IGNORECASE)
_RASTERIZED_MERMAID_IMG = re.compile(r'<figure class="mermaid-figure"><img src="([^"]+)"')


def _safe_name(title: str, used_lower: set[str]) -> str:
    """A filesystem- and Obsidian-safe note/folder name, unique among
    ``used_lower`` (siblings already named in the same directory)."""
    name = _INVALID_CHARS.sub("-", (title or "Untitled").strip()) or "Untitled"
    name = re.sub(r"\s+", " ", name).strip(" .")[:100] or "Untitled"
    base, n = name, 2
    while name.lower() in used_lower:
        name = f"{base} ({n})"
        n += 1
    used_lower.add(name.lower())
    return name


def _rewrite_images(content: str, bag: _AssetBag) -> str:
    def repl(m: re.Match) -> str:
        name = bag.add(m.group(2))
        if not name:
            return m.group(0)   # couldn't fetch it — leave the original Markdown link as a fallback
        return f"![[{name.rsplit('/', 1)[-1]}]]"
    return _IMG_MD.sub(repl, content)


def _rasterize_book_mermaid(book: dict, exclude_ids: set, bag: _AssetBag, lite: bool) -> list[str]:
    """Render the whole book once — the same headless-Chrome pass the EPUB
    export uses to resolve Mermaid to real SVG — then rasterize every
    diagram found (reusing epub.py's batching/cropping code as-is) and
    return the resulting ``![[filename]]`` embed for each one, in the same
    left-to-right, depth-first order the diagrams themselves appear in the
    book. The caller substitutes them 1:1 into each section's own
    ```mermaid``` fences encountered in that same order while walking the
    node tree — the two traversals visit the same filtered node set in the
    same order, so position alone is enough to correlate them without
    needing to track which diagram belongs to which section explicitly.

    Returns an empty list (fences are then left untouched, still valid
    Markdown) if no headless browser/Pillow is available, or rendering
    fails for any reason — this is a nice-to-have, never a reason to break
    the whole export."""
    try:
        html_doc = _export.book_to_html(book, None, exclude_ids)
        if not pdfgen.available():
            return []
        with tempfile.TemporaryDirectory(prefix="rext-pages-render-") as d:
            html_path = Path(d) / "preview.html"
            html_path.write_text(html_doc, encoding="utf-8")
            dumped = pdfgen.dump_rendered_dom(html_path.as_uri())
        out_html = _epub._rasterize_all_mermaid([dumped], bag, lite=lite)[0]
        return [m.group(1).rsplit("/", 1)[-1] for m in _RASTERIZED_MERMAID_IMG.finditer(out_html)]
    except Exception:
        return []


def _replace_mermaid_fences(content: str, mermaid_iter) -> str:
    def repl(m: re.Match) -> str:
        name = next(mermaid_iter, None)
        return f"![[{name}]]" if name else m.group(0)   # ran out — leave this one as a live fence
    return _MERMAID_FENCE.sub(repl, content)


class _Node:
    """One note-or-folder-note in the output. ``path`` is the vault path
    without a ``.md`` extension, i.e. exactly what a wikilink to it needs."""

    __slots__ = ("id", "title", "path", "section", "children")

    def __init__(self, node_id: str, title: str, path: str):
        self.id = node_id
        self.title = title
        self.path = path
        self.section: dict | None = None
        self.children: list["_Node"] = []


def _build_tree(nodes: list[dict], dir_path: str, numbered: bool = False,
                num_prefix: str = "") -> list["_Node"]:
    """First pass: decide every node's final vault path with no content
    written yet, so a note can link to a sibling/child whose path is
    already settled by the time content actually gets written.

    ``numbered`` prefixes every heading/subheading's title (and therefore
    its file/folder name) with its outline position — "1", "1-1", "1-2",
    "2-1", ... — a hyphen rather than the conventional "1.1" dot, since a
    "." in a folder/file name is asking for trouble on some filesystems and
    tools. This exists because a static host (e.g. GitHub Pages via an
    Obsidian export) generally loses the outline's own ordering and falls
    back to sorting notes alphabetically — a numeric prefix makes that
    fallback sort correct instead of scrambled.
    """
    used_lower: set[str] = set()
    struct_nodes = [c for c in nodes if c.get("type") != "section"]
    # Zero-padded to the width this level actually needs (e.g. "01".."12" for
    # 12 siblings) — a bare "1".."12" would sort "10" before "2" alphabetically,
    # which is exactly the failure mode this numbering exists to avoid.
    width = len(str(len(struct_nodes)))
    out = []
    for i, n in enumerate(struct_nodes, start=1):
        raw_title = n.get("title") or "Untitled"
        idx = f"{i:0{width}d}"
        num = idx if not num_prefix else f"{num_prefix}-{idx}"
        title = f"{num} {raw_title}" if numbered else raw_title
        name = _safe_name(title, used_lower)
        struct_children = [c for c in n.get("children") or [] if c.get("type") != "section"]
        section = next((c for c in n.get("children") or [] if c.get("type") == "section"), None)
        if struct_children:
            sub_dir = f"{dir_path}/{name}"
            node = _Node(n["id"], title, f"{sub_dir}/{name}")
            node.section = section
            node.children = _build_tree(struct_children, sub_dir, numbered, num)
        else:
            node = _Node(n["id"], title, f"{dir_path}/{name}")
            node.section = section
        out.append(node)
    return out


def _write_notes(tree_nodes: list["_Node"], parent: "_Node", bag: _AssetBag,
                 files: dict[str, str], mermaid_iter) -> None:
    for node in tree_nodes:
        parts = [f"*Part of [[{parent.path}|{parent.title}]]*"]
        body = strip_unresolved_image_placeholders((node.section or {}).get("content") or "").strip()
        if body:
            body = _replace_mermaid_fences(body, mermaid_iter)
            parts.append(_rewrite_images(body, bag).strip())
        if node.children:
            parts.append("## Contents\n" + "\n".join(
                f"- [[{c.path}|{c.title}]]" for c in node.children))
        files[f"{node.path}.md"] = "\n\n".join(parts).strip() + "\n"
        if node.children:
            _write_notes(node.children, node, bag, files, mermaid_iter)


def book_to_pages(book: dict, base_url: str, exclude_ids: set | None = None,
                  lite: bool = False, numbered: bool = False,
                  diagrams_as_images: bool = False) -> bytes:
    exclude_ids = exclude_ids or set()
    nodes = _export.filter_book_nodes(book.get("nodes") or [], exclude_ids)
    title = (book.get("title") or "Untitled").strip()
    root_name = _safe_name(title, set())

    bag = _AssetBag(base_url, lite=lite)
    tree = _build_tree(nodes, root_name, numbered)
    root = _Node("__root__", title, f"{root_name}/{root_name}")

    mermaid_images = (
        _rasterize_book_mermaid(book, exclude_ids, bag, lite) if diagrams_as_images else []
    )
    files: dict[str, str] = {}
    _write_notes(tree, root, bag, files, iter(mermaid_images))

    toc = [f"# {title}"]
    author = config.get_author()
    if author:
        toc.append(f"*by {author}*")
    if book.get("topic"):
        toc.append(f"*{config.format_blurb(book['topic'])}*")
    if tree:
        toc.append("## Contents\n" + "\n".join(f"- [[{c.path}|{c.title}]]" for c in tree))
    files[f"{root.path}.md"] = "\n\n".join(toc).strip() + "\n"

    zbuf = BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED, compresslevel=9 if lite else None) as z:
        for path, content in files.items():
            z.writestr(path, content)
        for name, data in bag.files.items():
            z.writestr(f"{root_name}/assets/{name.rsplit('/', 1)[-1]}", data)
    return zbuf.getvalue()
