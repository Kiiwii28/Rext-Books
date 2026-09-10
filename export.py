"""Export a book to Markdown or PDF.

PDF rendering, in order of preference:
  1. a headless Chrome/Edge/Chromium browser (``pdfgen``) — matches the on-screen
     preview exactly, keeps working links and printed colours;
  2. WeasyPrint, if it and its native libraries are installed;
  3. nothing — the route 501s and the UI falls back to the browser print dialog.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date
from urllib.parse import quote

import importlib.util

import palettes
import pdfgen
from rendering import render_markdown

# WeasyPrint is optional and only tried if no browser is available. Probe for the
# module without importing it, so its noisy "missing native libs" warning on
# Windows never hits the console at startup.
_HAS_WEASYPRINT = importlib.util.find_spec("weasyprint") is not None


def _load_weasyprint():
    from weasyprint import HTML  # noqa: N811  (import here to defer the warning)
    return HTML


def pdf_engine() -> str | None:
    if pdfgen.available():
        return "browser"
    if _HAS_WEASYPRINT:
        return "weasyprint"
    return None


def pdf_available() -> bool:
    return pdf_engine() is not None


def pdf_error() -> str:
    return (
        "PDF export needs a Chrome/Edge/Chromium browser (or WeasyPrint) on the "
        "server. None was found. Markdown export still works, and the app can open "
        "a print-ready page instead."
    )


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

_HEADING_LINE = re.compile(r"^(#{1,6})(\s)", re.MULTILINE)
_LOCAL_IMG = re.compile(r"(!\[[^\]]*\]\()(/assets/[^)\s]+)(\))")


def _demote(md: str, by: int) -> str:
    return _HEADING_LINE.sub(lambda m: "#" * min(6, len(m.group(1)) + by) + m.group(2), md)


def _absolutise(md: str, base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    return _LOCAL_IMG.sub(lambda m: f"{m.group(1)}{base}{m.group(2)}{m.group(3)}", md)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _strip_dupe_heading(md: str, title: str) -> str:
    """Drop a leading '## Same Title' the model sometimes repeats from the subheading."""
    stripped = md.lstrip()
    lines = stripped.split("\n", 1)
    first = lines[0]
    if re.match(r"^#{1,4}\s+", first):
        htext = re.sub(r"^#{1,4}\s+", "", first).strip().strip("#").strip()
        if _slug(htext) == _slug(title):
            return (lines[1] if len(lines) > 1 else "").lstrip()
    return md


# --------------------------------------------------------------------------- #
#  Markdown                                                                    #
# --------------------------------------------------------------------------- #

def book_to_markdown(book: dict, base_url: str = "") -> str:
    out: list[str] = [f"# {book.get('title', 'Untitled')}", ""]
    if book.get("topic"):
        out += [f"*A textbook on {book['topic']}.*", ""]

    def walk(nodes: list[dict], level: int, container_title: str) -> None:
        for n in nodes:
            if n.get("type") == "section":
                body = _absolutise(n.get("content") or "", base_url)
                body = _strip_dupe_heading(body, container_title)
                out.append(_demote(body, max(0, level - 2)).strip() + "\n")
                continue
            title = (n.get("title") or "").strip()
            out.append(f"\n{'#' * min(level, 6)} {title}\n")
            walk(n.get("children") or [], level + 1, title)

    walk(book.get("nodes") or [], 2, book.get("title", ""))
    return "\n".join(out).strip() + "\n"


# --------------------------------------------------------------------------- #
#  HTML / PDF                                                                  #
# --------------------------------------------------------------------------- #

def _doc_css(p: dict[str, str]) -> str:
    return f"""
    /* No page margin: the palette background must reach every paper edge.
       Chrome's print engine never paints the @page margin area and clips fixed
       elements to it, so instead .content carries the background AND the reading
       margin, with box-decoration-break:clone so both repeat on every page
       fragment — full bleed, and text stays clear of the edge on continuation
       pages too. */
    @page {{ size: A4; margin: 0; }}
    *, *::before, *::after {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    html, body {{ background: {p['bg']}; }}
    body {{
      margin: 0; color: {p['text']};
      font-family: Georgia, 'Iowan Old Style', 'Times New Roman', serif;
      font-size: 10.5pt; line-height: 1.62;
    }}
    .content {{
      padding: 14mm 17mm;
      background: {p['bg']};
      -webkit-box-decoration-break: clone;
      box-decoration-break: clone;
    }}
    .cover {{ padding-top: 14mm; }}
    p {{ margin: 0 0 .75em; orphans: 2; widows: 2; overflow-wrap: break-word; }}
    h1, h2, h3, h4, h5, h6 {{
      font-family: 'Helvetica Neue', 'Segoe UI', Arial, sans-serif;
      color: {p['heading']}; line-height: 1.22; break-after: avoid;
    }}
    h1 {{ font-size: 25pt; letter-spacing: -.01em; margin: 0 0 .3em; }}
    h2 {{
      font-size: 16pt; margin: 1.5em 0 .5em;
      border-bottom: 2pt solid {p['accent']}; padding-bottom: .18em;
    }}
    h3 {{ font-size: 12.5pt; margin: 1.3em 0 .4em; }}
    h4 {{ font-size: 11pt; margin: 1.1em 0 .35em; color: {p['text']}; }}
    h5 {{ font-size: 10.5pt; margin: 1em 0 .3em; color: {p['text']}; }}
    h6 {{ font-size: 10pt; margin: 1em 0 .3em; color: {p['muted']};
      text-transform: uppercase; letter-spacing: .04em; }}

    a {{ color: {p['accent']}; text-decoration: none; }}

    strong {{ color: {p['heading']}; }}
    em {{ color: inherit; }}

    ul, ol {{ margin: .5em 0 .9em; padding-left: 1.4em; }}
    li {{ margin: .25em 0; }}

    code {{
      font-family: 'SF Mono', Consolas, 'Roboto Mono', monospace; font-size: .88em;
      background: {p['accent']}22; color: {p['heading']};
      padding: .08em .32em; border-radius: 3px;
    }}
    pre {{
      background: {p['accent']}14; border-left: 3pt solid {p['accent']};
      padding: 9pt 11pt; border-radius: 3pt; overflow-x: auto; break-inside: avoid;
      font-size: 9pt; line-height: 1.5;
    }}
    pre code {{ background: none; color: {p['text']}; padding: 0; }}

    blockquote {{
      margin: 1em 0; padding: .3em 1em;
      border-left: 3pt solid {p['accent']};
      background: {p['accent']}10; color: {p['muted']}; break-inside: avoid;
    }}

    table {{ border-collapse: collapse; width: 100%; margin: 1em 0; break-inside: avoid; font-size: 9.5pt; }}
    th, td {{ border: .75pt solid {p['muted']}88; padding: 5pt 8pt; text-align: left; }}
    th {{ background: {p['accent']}; color: #fff; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    tr:nth-child(even) td {{ background: {p['accent']}0d; }}

    img {{ max-width: 100%; height: auto; display: block; margin: 1em auto; break-inside: avoid; }}
    hr {{ border: 0; border-top: .75pt solid {p['muted']}66; margin: 1.6em 0; }}

    /* mermaid diagrams — a centred, translucent figure like the callouts.
       The SVG is capped so a tall diagram scales to fit one page instead of
       overflowing / splitting across pages. */
    .mermaid-figure {{
      margin: 1.5em auto; padding: 12pt 10pt; text-align: center;
      background: {p['accent']}0d; border: .75pt solid {p['accent']}3a;
      border-radius: 6pt; break-inside: avoid; overflow: hidden;
    }}
    .mermaid-figure pre.mermaid {{ margin: 0; background: none; padding: 0; border: 0; }}
    .mermaid-figure svg {{
      max-width: 100%; width: auto; height: auto; max-height: 226mm;
    }}
    pre.mermaid:not(.rendered) {{
      display: block; text-align: left; white-space: pre-wrap;
      font-family: 'SF Mono', Consolas, monospace; font-size: 8.5pt; color: {p['muted']};
    }}

    /* placeholder for an image the model referenced but that isn't available */
    .fig-placeholder {{
      margin: 1.4em auto; padding: 12pt; text-align: center;
      border: .75pt dashed {p['muted']}88; border-radius: 5pt;
      background: {p['accent']}08; color: {p['muted']}; break-inside: avoid;
    }}
    .fig-placeholder .fig-icon {{ display: block; font-size: 15pt; margin-bottom: 3pt; opacity: .6; }}
    .fig-placeholder figcaption {{ font-size: 9pt; font-style: italic; }}

    /* cover */
    .cover {{ break-after: page; padding-top: 22mm; }}
    .cover h1 {{ font-size: 34pt; }}
    .cover .band {{ height: 5pt; width: 46mm; background: {p['accent']}; margin: 1.4em 0 1.8em; }}
    .cover .topic {{ font-size: 13pt; font-style: italic; color: {p['muted']}; }}
    .cover .date {{ margin-top: 60mm; font-size: 9.5pt; color: {p['muted']};
      font-family: 'Helvetica Neue', Arial, sans-serif; letter-spacing: .03em; }}

    /* contents */
    nav.toc {{ break-after: page; }}
    nav.toc h2 {{ border: 0; padding: 0; margin-bottom: .8em; }}
    nav.toc ol {{ list-style: none; padding-left: 0; margin: 0; }}
    nav.toc > ol > li {{ margin: .55em 0; font-family: 'Helvetica Neue', Arial, sans-serif; }}
    nav.toc > ol > li > a {{ font-weight: 600; color: {p['heading']}; }}
    nav.toc ol ol {{ padding-left: 1.3em; margin: .2em 0 .5em; }}
    nav.toc ol ol li {{ margin: .28em 0; font-size: .92em; }}
    nav.toc ol ol a {{ color: {p['muted']}; }}

    section.chapter {{ break-before: page; }}
    section.chapter > h1 {{
      border-bottom: 3pt solid {p['accent']}; padding-bottom: .25em; margin-bottom: .9em;
    }}
    """


def book_to_html(book: dict, palette_name: str | None = None) -> str:
    p = palettes.get(palette_name)
    esc = _html.escape
    title = esc(book.get("title", "Untitled"))
    topic = esc(book.get("topic", ""))

    toc: list[str] = []
    body: list[str] = []

    def walk(nodes: list[dict], level: int, container_title: str, in_toc: bool) -> None:
        for n in nodes:
            if n.get("type") == "section":
                if (n.get("content") or "").strip():
                    md = _strip_dupe_heading(n["content"], container_title)
                    body.append(render_markdown(_demote(md, max(0, level - 2))))
                continue
            nid = n.get("id", "")
            ntitle_raw = n.get("title") or "Untitled"
            ntitle = esc(ntitle_raw)
            tag = f"h{min(level, 6)}"
            if level == 1:
                body.append(f'<section class="chapter"><h1 id="{nid}">{ntitle}</h1>')
            else:
                body.append(f'<{tag} id="{nid}">{ntitle}</{tag}>')
            # TOC: chapters + the first two subheading levels
            if in_toc and level <= 3:
                if level == 1:
                    toc.append(f'<li><a href="#{nid}">{ntitle}</a><ol>')
                else:
                    toc.append(f'<li><a href="#{nid}">{ntitle}</a></li>')
            walk(n.get("children") or [], level + 1, ntitle_raw, in_toc and level <= 2)
            if level == 1:
                toc.append("</ol></li>")
                body.append("</section>")

    walk(book.get("nodes") or [], 1, title, True)
    has_mermaid = 'class="mermaid"' in "".join(body)

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title><style>{_doc_css(p)}</style></head><body>
<div class="content">
<div class="cover">
  <h1>{title}</h1><div class="band"></div>
  {f'<div class="topic">A textbook on {topic}</div>' if topic else ''}
  <div class="date">Generated {date.today().isoformat()} &middot; Rextbooks</div>
</div>
<nav class="toc"><h2>Contents</h2><ol>{''.join(toc)}</ol></nav>
{''.join(body)}
</div>
{_BROKEN_IMG_SCRIPT}
{_mermaid_script(p) if has_mermaid else ''}
</body></html>"""


_BROKEN_IMG_SCRIPT = (
    "<script>document.querySelectorAll('img').forEach(function(img){"
    "function swap(){var f=document.createElement('figure');f.className='fig-placeholder';"
    "var c=document.createElement('figcaption');c.textContent=img.getAttribute('alt')||'Figure';"
    "var i=document.createElement('span');i.className='fig-icon';i.textContent='\\u25A8';"
    "f.appendChild(i);f.appendChild(c);"
    "var h=img.closest('p,figure');(h&&h.children.length===1&&!h.textContent.trim()?h:img).replaceWith(f);}"
    "if(img.complete&&img.naturalWidth===0)swap();else img.addEventListener('error',swap,{once:true});"
    "});</script>"
)


def _mermaid_script(p: dict[str, str]) -> str:
    """Client-side Mermaid render for the print/PDF page, themed to the palette."""
    return (
        '<script type="module">\n'
        'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/+esm";\n'
        'mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base",\n'
        '  flowchart: { curve: "basis", useMaxWidth: true, rankSpacing: 34, nodeSpacing: 26, padding: 6 },\n'
        '  sequence: { useMaxWidth: true }, mindmap: { padding: 8 },\n'
        '  themeVariables: {\n'
        '    fontFamily: "Georgia, \'Times New Roman\', serif", fontSize: "13px",\n'
        f'    primaryColor: "{p["accent"]}1f", primaryTextColor: "{p["text"]}",\n'
        f'    primaryBorderColor: "{p["accent"]}", lineColor: "{p["heading"]}",\n'
        f'    secondaryColor: "{p["accent"]}12", tertiaryColor: "{p["bg"]}",\n'
        f'    background: "{p["bg"]}", mainBkg: "{p["accent"]}1f", textColor: "{p["text"]}",\n'
        f'    nodeBorder: "{p["accent"]}", clusterBkg: "{p["accent"]}0d",\n'
        f'    clusterBorder: "{p["accent"]}55", titleColor: "{p["heading"]}",\n'
        f'    edgeLabelBackground: "{p["bg"]}", actorBorder: "{p["accent"]}",\n'
        f'    actorBkg: "{p["accent"]}1f", noteBkgColor: "{p["accent"]}14",\n'
        f'    noteBorderColor: "{p["accent"]}55" }}\n'
        '});\n'
        'const blocks = [...document.querySelectorAll("pre.mermaid")];\n'
        'for (let i = 0; i < blocks.length; i++) {\n'
        '  const pre = blocks[i]; const code = pre.textContent.trim();\n'
        '  try { const { svg } = await mermaid.render("mmd" + i, code);\n'
        '    pre.innerHTML = svg; pre.classList.add("rendered");\n'
        '    const s = pre.querySelector("svg");\n'
        '    if (s) { s.removeAttribute("height"); s.style.maxHeight = "226mm"; s.style.maxWidth = "100%"; }\n'
        '  } catch (e) { pre.classList.add("mermaid-error"); }\n'
        '}\n'
        'document.body.dataset.mermaidDone = "1";\n'
        '</script>'
    )


def book_to_pdf(book: dict, palette_name: str | None, base_url: str) -> bytes:
    engine = pdf_engine()
    if engine == "browser":
        url = (
            f"{base_url.rstrip('/')}/api/books/{book['id']}/preview"
            f"?palette={quote(palette_name or '')}"
        )
        return pdfgen.url_to_pdf(url)
    if engine == "weasyprint":
        html_doc = book_to_html(book, palette_name)
        return _load_weasyprint()(string=html_doc, base_url=base_url).write_pdf()
    raise RuntimeError(pdf_error())
