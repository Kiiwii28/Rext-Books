"""EPUB export — mirrors the PDF's visual language (palette, typography,
Mermaid figures) with a proper nested navigation (both EPUB3 nav.xhtml and
an EPUB2-compatible toc.ncx), every image embedded as a real file (EPUB
readers don't fetch anything over the network), and CSS that keeps content
from overflowing a reader's screen.

Reuses the *same* rendered HTML the PDF export produces: one headless-Chrome
pass renders every Mermaid diagram to static SVG and swaps any broken image
for a placeholder (see ``pdfgen.dump_rendered_dom``); this module just
repackages that into the EPUB container format instead of printing it. If no
headless browser is available at all, it falls back to the un-rendered HTML
(Mermaid blocks show as plain text) rather than failing outright.
"""

from __future__ import annotations

import html as _html
import mimetypes
import re
import tempfile
import uuid
import zipfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

import requests
from werkzeug.utils import secure_filename

import config
import export as _export
import palettes
import pdfgen
import store

try:
    from PIL import Image   # optional: only needed to rasterize Mermaid diagrams
except ImportError:         # pragma: no cover - degrades to inline SVG
    Image = None

_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_VOID = re.compile(r"<(br|hr|img|input|meta|link|col|source)\b([^>]*?)\s*/?>", re.IGNORECASE)
_CHAPTER = re.compile(r'<section class="chapter">(.*?)</section>', re.DOTALL)
_IMG_TAG = re.compile(r"<img\b([^>]*)/?>", re.IGNORECASE)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
_LOCAL_IMG_HTML = re.compile(r'(<img\b[^>]*\bsrc=")(/assets/[^"]+)(")')
_MERMAID_FIGURE = re.compile(
    r'<figure class="mermaid-figure"><pre class="mermaid rendered"[^>]*>(.*?)</pre></figure>',
    re.DOTALL,
)
_VIEWBOX = re.compile(r'viewBox="[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)"')
_MERMAID_SHOT_SCALE = 2   # render at 2x so it stays crisp on high-DPI readers

_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


def _absolutise_html(html: str, base_url: str) -> str:
    """Rewrite <img src="/assets/..."> to a full URL. Needed once the render
    pass loads from a local file instead of the live server (see
    book_to_epub) — a root-relative path can't resolve against file://."""
    base = (base_url or "").rstrip("/")
    return _LOCAL_IMG_HTML.sub(lambda m: f"{m.group(1)}{base}{m.group(2)}{m.group(3)}", html)


def _xmlify(fragment: str) -> str:
    """Best-effort HTML -> well-formed-XML fixups (escape a stray '&', self-
    close void elements). The content here is our own rendered Markdown plus
    injected Mermaid SVG, so this covers the realistic cases without pulling
    in a full HTML parser."""
    frag = _AMP.sub("&amp;", fragment)
    frag = _VOID.sub(lambda m: f"<{m.group(1)}{m.group(2)}/>", frag)
    return frag


class _AssetBag:
    """Downloads every image a chapter references (once each) and hands back
    the epub-relative path to use in its place."""

    _EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.by_src: dict[str, str | None] = {}
        self.files: dict[str, bytes] = {}
        self.media_types: dict[str, str] = {}
        self._n = 0

    def add(self, src: str) -> str | None:
        if src in self.by_src:
            return self.by_src[src]
        got = self._fetch(src)
        if got is None:
            self.by_src[src] = None
            return None
        body, ext = got
        name = self.add_bytes(body, ext)
        self.by_src[src] = name
        return name

    def add_bytes(self, data: bytes, ext: str) -> str:
        """Add an already-in-hand file (e.g. a rasterized diagram) with no
        source URL to de-duplicate against — always a fresh asset."""
        self._n += 1
        name = f"images/img{self._n}.{ext}"
        self.files[name] = data
        self.media_types[name] = (
            "image/svg+xml" if ext == "svg" else (mimetypes.types_map.get(f".{ext}") or "image/png")
        )
        return name

    def _fetch(self, src: str) -> tuple[bytes, str] | None:
        try:
            if src.startswith("/assets/"):
                parts = src.strip("/").split("/")   # ["assets", "<book_id>", "<file>"]
                if len(parts) >= 3:
                    p = store.assets_dir(parts[1]) / secure_filename(parts[2])
                    if p.exists():
                        ext = p.suffix.lstrip(".").lower() or "png"
                        return p.read_bytes(), (ext if ext in self._EXTS else "png")
                return None
            if src.startswith("data:"):
                return None
            url = src if src.startswith("http") else urljoin(self.base_url, src)
            r = requests.get(url, timeout=(10, 20))
            if r.status_code >= 400 or not r.content:
                return None
            ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = (mimetypes.guess_extension(ctype) or PurePosixPath(url.split("?")[0]).suffix or ".png").lstrip(".")
            return r.content, (ext if ext in self._EXTS else "png")
        except requests.RequestException:
            return None


def _force_svg_size(svg: str, w: float, h: float) -> str:
    """Strip any existing width/height/style on the root <svg> and pin it to
    an exact pixel size (viewBox already defines the internal coordinate
    system, so this just scales the rendered output cleanly)."""
    svg = re.sub(r'\swidth="[^"]*"', "", svg, count=1)
    svg = re.sub(r'\sheight="[^"]*"', "", svg, count=1)
    svg = re.sub(r'\sstyle="[^"]*"', "", svg, count=1)
    return re.sub(r"^<svg\b", f'<svg width="{w:.2f}" height="{h:.2f}"', svg, count=1)


_GAP = 12            # px between stacked diagrams in one batch screenshot
_MAX_BATCH_HEIGHT = 6000   # keeps each individual headless-Chrome screenshot modest


def _rasterize_all_mermaid(chapter_html: list[str], bag: "_AssetBag") -> list[str]:
    """Replace every pre-rendered (but still live-SVG) Mermaid figure across
    every chapter with a rasterized PNG.

    Mermaid's SVG uses foreignObject for labels and 8-digit alpha-hex fills —
    both are inconsistently supported across e-reader rendering engines
    (dropped label text, solid-black shapes are the typical failure). A
    screenshot, taken with the same Chrome that already renders it correctly
    for the app/PDF, sidesteps that completely.

    A textbook can easily have 100+ diagrams — one headless-Chrome launch per
    diagram would take minutes, so instead every diagram this finds gets
    stacked into a handful of tall pages (capped in height so each screenshot
    stays quick), each page screenshotted once and cropped apart with Pillow.
    """
    entries: list[dict] = []
    for ci, html in enumerate(chapter_html):
        for m in _MERMAID_FIGURE.finditer(html):
            svg = m.group(1)
            vb = _VIEWBOX.search(svg)
            w = float(vb.group(1)) if vb else 600.0
            h = float(vb.group(2)) if vb else 300.0
            entries.append({
                "ci": ci, "svg": svg,
                "w": max(60.0, min(w, 1600.0)),
                "h": max(40.0, min(h, 1600.0)),
            })

    if not entries or Image is None or not pdfgen.available():
        return chapter_html   # leave as live inline SVG — still valid, just less compatible

    batch: list[dict] = []
    batch_h = 0.0
    for e in entries:
        eh = e["h"] * _MERMAID_SHOT_SCALE + _GAP
        if batch and batch_h + eh > _MAX_BATCH_HEIGHT:
            _rasterize_batch(batch, bag)
            batch, batch_h = [], 0.0
        batch.append(e)
        batch_h += eh
    if batch:
        _rasterize_batch(batch, bag)

    by_chapter: dict[int, list[dict]] = {}
    for e in entries:
        by_chapter.setdefault(e["ci"], []).append(e)

    out = list(chapter_html)
    for ci, group in by_chapter.items():
        it = iter(group)

        def repl(m: re.Match, _it=it) -> str:
            e = next(_it)
            if "asset" not in e:
                return m.group(0)
            return (
                '<figure class="mermaid-figure">'
                f'<img src="{e["asset"]}" alt="Diagram" width="{int(e["w"])}" height="{int(e["h"])}"/>'
                "</figure>"
            )

        out[ci] = _MERMAID_FIGURE.sub(repl, out[ci])
    return out


def _rasterize_batch(group: list[dict], bag: "_AssetBag") -> None:
    """Stack every diagram in `group` into one tall page, screenshot it once,
    and crop each diagram back out with Pillow — sets `e["asset"]` in place."""
    y = 0.0
    max_w = 0.0
    divs = []
    positions = []
    for e in group:
        sw, sh = e["w"] * _MERMAID_SHOT_SCALE, e["h"] * _MERMAID_SHOT_SCALE
        sized_svg = _force_svg_size(e["svg"], sw, sh)
        divs.append(
            f'<div style="position:absolute;left:0;top:{y:.1f}px;'
            f'width:{sw:.1f}px;height:{sh:.1f}px;overflow:hidden;">{sized_svg}</div>'
        )
        positions.append((y, sw, sh))
        max_w = max(max_w, sw)
        y += sh + _GAP
    total_h = y

    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        "<style>html,body{margin:0;padding:0;background:transparent;}"
        "svg{display:block;}</style></head><body>" + "".join(divs) + "</body></html>"
    )
    try:
        png_bytes = pdfgen.screenshot_html(html, int(max_w) + 8, int(total_h) + 8)
        sheet = Image.open(BytesIO(png_bytes)).convert("RGBA")
    except Exception:
        return   # every entry in this batch simply stays as inline SVG

    for e, (y0, sw, sh) in zip(group, positions):
        crop = sheet.crop((0, int(y0), int(sw), int(y0 + sh)))
        buf = BytesIO()
        crop.save(buf, format="PNG")
        e["asset"] = bag.add_bytes(buf.getvalue(), "png")


def _rewrite_images(fragment: str, bag: "_AssetBag") -> str:
    def repl(m: re.Match) -> str:
        attrs = dict(_ATTR.findall(m.group(1)))
        src = attrs.get("src", "")
        alt = _html.escape(attrs.get("alt", "") or "Figure")
        asset = bag.add(src) if src else None
        if not asset:
            return f'<span class="fig-placeholder-inline">▨ {alt}</span>'
        return f'<img src="{asset}" alt="{alt}"/>'
    return _IMG_TAG.sub(repl, fragment)


def _build_nav(nodes: list[dict]) -> tuple[list[tuple[dict, str]], str, str]:
    """`nodes` must already be exclude-filtered. Returns
    ``([(chapter_node, filename), ...], nav_ol_html, ncx_navpoints_xml)``."""
    chapters: list[tuple[dict, str]] = []
    i = 0
    for n in nodes:
        if n.get("type") == "heading":
            i += 1
            chapters.append((n, f"ch{i}.xhtml"))

    file_of: dict[str, str] = {}

    def mark(node: dict, fname: str) -> None:
        file_of[node.get("id", "")] = fname
        for c in node.get("children") or []:
            mark(c, fname)

    for node, fname in chapters:
        mark(node, fname)

    def kids_of(n: dict) -> list[dict]:
        return [c for c in (n.get("children") or []) if c.get("type") != "section"]

    def rec_ol(items: list[dict]) -> str:
        parts = ["<ol>"]
        for n in items:
            href = f'{file_of.get(n["id"], "")}#{n["id"]}'
            title = _html.escape(n.get("title") or "Untitled")
            parts.append(f'<li><a href="{href}">{title}</a>')
            kids = kids_of(n)
            if kids:
                parts.append(rec_ol(kids))
            parts.append("</li>")
        parts.append("</ol>")
        return "".join(parts)

    play_order = [0]

    def rec_ncx(items: list[dict]) -> str:
        parts = []
        for n in items:
            play_order[0] += 1
            po = play_order[0]
            href = f'{file_of.get(n["id"], "")}#{n["id"]}'
            title = _html.escape(n.get("title") or "Untitled")
            inner = rec_ncx(kids_of(n))
            parts.append(
                f'<navPoint id="np{po}" playOrder="{po}">'
                f'<navLabel><text>{title}</text></navLabel>'
                f'<content src="{href}"/>{inner}</navPoint>'
            )
        return "".join(parts)

    top = [n for n, _ in chapters]
    nav_ol = rec_ol(top) if top else "<ol></ol>"
    ncx_points = rec_ncx(top)
    return chapters, nav_ol, ncx_points


def _epub_css(p: dict[str, str]) -> str:
    return f"""
body {{ margin: 0; padding: 5%; color: {p['text']}; background: {p['bg']};
  font-family: Georgia, 'Iowan Old Style', 'Times New Roman', serif;
  font-size: 1em; line-height: 1.6; overflow-wrap: break-word; }}
h1, h2, h3, h4, h5, h6 {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: {p['heading']}; line-height: 1.25; }}
h1 {{ font-size: 1.7em; margin: 0 0 .5em; }}
h2 {{ font-size: 1.35em; margin: 1.3em 0 .5em; border-bottom: 2px solid {p['accent']}; padding-bottom: .2em; }}
h3 {{ font-size: 1.15em; margin: 1.1em 0 .4em; }}
h4 {{ font-size: 1.05em; margin: 1em 0 .3em; }}
h5, h6 {{ font-size: 1em; margin: 1em 0 .3em; color: {p['muted']}; text-transform: uppercase; letter-spacing: .04em; }}
p {{ margin: 0 0 1em; }}
a {{ color: {p['accent']}; }}
strong {{ color: {p['heading']}; }}
img {{ max-width: 100%; height: auto; }}
ul, ol {{ padding-left: 1.3em; }}
li {{ margin: .3em 0; }}
pre, code {{ font-family: 'SF Mono', Consolas, 'Roboto Mono', monospace;
  white-space: pre-wrap; overflow-wrap: break-word; word-break: break-word; }}
code {{ background: {p['accent']}22; padding: .08em .3em; border-radius: 3px; }}
pre {{ background: {p['accent']}14; border-left: 3px solid {p['accent']}; border-radius: 4px;
  padding: .6em .8em; }}
pre code {{ background: none; padding: 0; }}
blockquote {{ margin: 1em 0; padding: .3em 1em; border-left: 3px solid {p['accent']};
  background: {p['accent']}10; color: {p['muted']}; }}
table {{ border-collapse: collapse; width: 100%; table-layout: fixed; font-size: .88em; margin: 1em 0; }}
th, td {{ border: 1px solid {p['muted']}88; padding: .3em .5em; overflow-wrap: break-word; text-align: left; }}
th {{ background: {p['accent']}; color: #fff; }}
tr:nth-child(even) td {{ background: {p['accent']}0d; }}
hr {{ border: 0; border-top: 1px solid {p['muted']}66; margin: 1.6em 0; }}
.mermaid-figure {{ margin: 1.3em 0; padding: .7em; text-align: center;
  background: {p['accent']}0d; border: 1px solid {p['accent']}3a; border-radius: 6px; }}
.mermaid-figure svg {{ max-width: 100% !important; width: auto !important; height: auto !important; }}
.fig-placeholder, .fig-placeholder-inline {{
  display: block; margin: 1em 0; padding: .8em; text-align: center;
  border: 1px dashed {p['muted']}88; border-radius: 5px;
  background: {p['accent']}08; color: {p['muted']}; font-style: italic; }}
.cover {{ text-align: center; padding-top: 30%; }}
.cover h1 {{ font-size: 2em; }}
.cover .band {{ height: 3px; width: 40%; margin: 1em auto; background: {p['accent']}; }}
.cover .topic {{ font-style: italic; color: {p['muted']}; }}
.cover .author {{ font-weight: 600; color: {p['heading']}; margin-top: .4em; }}
.cover .date {{ margin-top: 3em; font-size: .82em; color: {p['muted']};
  font-family: 'Helvetica Neue', Arial, sans-serif; }}
#toc ol {{ list-style: none; padding-left: 1.1em; }}
#toc > ol {{ padding-left: 0; }}
#toc a {{ color: {p['heading']}; text-decoration: none; }}
"""


def _cover_xhtml(title: str, topic: str, author: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><meta charset="utf-8"/><title>{title}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<section class="cover">
  <h1>{title}</h1>
  <div class="band"></div>
  {f'<p class="topic">A textbook on {topic}</p>' if topic else ''}
  {f'<p class="author">by {_html.escape(author)}</p>' if author else ''}
  <p class="date">Generated {date.today().isoformat()} &#183; Rextbooks</p>
</section>
</body>
</html>"""


def _chapter_xhtml(title: str, inner_html: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="utf-8"/><title>{title}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<section epub:type="chapter">
{inner_html}
</section>
</body>
</html>"""


def _nav_xhtml(title: str, nav_ol: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="utf-8"/><title>{title} &#8212; Contents</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<nav epub:type="toc" id="toc"><h1>Contents</h1>{nav_ol}</nav>
</body>
</html>"""


def _toc_ncx(book_uuid: str, title: str, ncx_points: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_uuid}"/>
    <meta name="dtb:depth" content="3"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>{ncx_points}</navMap>
</ncx>"""


def _content_opf(book_uuid: str, title: str, author: str, topic: str,
                  manifest_items: list[tuple[str, str, str]], spine_ids: list[str]) -> str:
    items_xml = "".join(
        f'<item id="{iid}" href="{href}" media-type="{mtype}"'
        + (' properties="nav"' if iid == "nav" else "") + "/>"
        for iid, href, mtype in manifest_items
    )
    spine_xml = "".join(f'<itemref idref="{i}"/>' for i in spine_ids)
    creator = f"<dc:creator>{_html.escape(author)}</dc:creator>" if author else ""
    desc = f"<dc:description>A textbook on {topic}.</dc:description>" if topic else ""
    modified = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_uuid}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>en</dc:language>
    <dc:date>{date.today().isoformat()}</dc:date>
    {creator}
    {desc}
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="css" href="style.css" media-type="text/css"/>
    {items_xml}
  </manifest>
  <spine toc="ncx">{spine_xml}</spine>
  <guide><reference type="toc" title="Contents" href="nav.xhtml"/></guide>
</package>"""


def book_to_epub(book: dict, palette_name: str | None, base_url: str, exclude_ids: set | None = None) -> bytes:
    exclude_ids = exclude_ids or set()
    p = palettes.get(palette_name)
    nodes = _export.filter_book_nodes(book.get("nodes") or [], exclude_ids)
    chapters, nav_ol, ncx_points = _build_nav(nodes)

    # One headless-Chrome pass renders Mermaid diagrams to static SVG and
    # swaps out any broken image — exactly what the PDF export gets. Rendered
    # from a *local file*, not the live /preview URL: this call runs inside
    # the very request handler thread that's serving this export, and Chrome
    # making an HTTP request back to that same (single-process) dev server
    # while its handler thread sits blocked on this subprocess call stalls
    # badly — a four-minute export dropped to under ninety seconds by
    # rendering a local file instead of asking the server to render itself.
    html_doc = _absolutise_html(_export.book_to_html(book, palette_name, exclude_ids), base_url)
    dumped = None
    if pdfgen.available():
        try:
            with tempfile.TemporaryDirectory(prefix="rext-epub-render-") as d:
                html_path = Path(d) / "preview.html"
                html_path.write_text(html_doc, encoding="utf-8")
                dumped = pdfgen.dump_rendered_dom(html_path.as_uri())
        except Exception:
            dumped = None
    if dumped is None:
        # No headless browser at all — still produce a valid (if plainer)
        # epub rather than failing outright; Mermaid blocks stay as text.
        dumped = html_doc

    chapter_html = _CHAPTER.findall(dumped)

    title = _html.escape(book.get("title", "Untitled"))
    topic = _html.escape(book.get("topic", ""))
    author = config.get_author()
    book_uuid = f"urn:uuid:{book.get('id') or uuid.uuid4().hex}"

    bag = _AssetBag(base_url)
    manifest_items: list[tuple[str, str, str]] = []
    spine_ids: list[str] = []

    # Content <img> tags first (real URLs to fetch/embed) for every chapter,
    # *then* Mermaid rasterization once across all of them — reversed, the
    # image rewrite would try to re-fetch a freshly-inserted epub-internal
    # image path as if it were a content URL, fail, and stomp it with a
    # placeholder. Mermaid runs last, batched, since a book can easily have
    # 100+ diagrams and a Chrome launch per diagram would take minutes.
    chapter_html = [_rewrite_images(h, bag) for h in chapter_html]
    chapter_html = _rasterize_all_mermaid(chapter_html, bag)

    zbuf = BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER_XML)
        z.writestr("OEBPS/style.css", _epub_css(p))

        z.writestr("OEBPS/cover.xhtml", _cover_xhtml(title, topic, author))
        manifest_items.append(("cover", "cover.xhtml", "application/xhtml+xml"))
        spine_ids.append("cover")

        for i, (node, fname) in enumerate(chapters, start=1):
            inner = chapter_html[i - 1] if i - 1 < len(chapter_html) else ""
            inner = _xmlify(inner)
            chap_title = _html.escape(node.get("title") or "Untitled")
            z.writestr(f"OEBPS/{fname}", _chapter_xhtml(chap_title, inner))
            item_id = f"chap{i}"
            manifest_items.append((item_id, fname, "application/xhtml+xml"))
            spine_ids.append(item_id)

        for path, data in bag.files.items():
            z.writestr(f"OEBPS/{path}", data)
            manifest_items.append((path.replace("/", "_"), path, bag.media_types.get(path, "application/octet-stream")))

        z.writestr("OEBPS/nav.xhtml", _nav_xhtml(title, nav_ol))
        manifest_items.append(("nav", "nav.xhtml", "application/xhtml+xml"))

        z.writestr("OEBPS/toc.ncx", _toc_ncx(book_uuid, title, ncx_points))
        manifest_items.append(("ncx", "toc.ncx", "application/x-dtbncx+xml"))

        z.writestr("OEBPS/content.opf", _content_opf(book_uuid, title, author, topic, manifest_items, spine_ids))

    return zbuf.getvalue()
