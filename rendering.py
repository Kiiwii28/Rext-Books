"""Shared Markdown -> HTML rendering (used by the app and by export).

Mermaid code fences (```mermaid … ```) are turned into
``<figure class="mermaid-figure"><pre class="mermaid">…</pre></figure>`` so the
client (and the print/PDF page) can render them to SVG. The fence body stays
HTML-escaped; Mermaid reads ``element.textContent`` which decodes it.

Images that point at a placeholder-image service (or have no usable source) are
replaced with a tidy ``<figure class="fig-placeholder">`` caption instead of a
big broken/grey box.
"""

from __future__ import annotations

import html as _html
import re

import markdown

MD_EXTENSIONS = [
    "fenced_code", "tables", "attr_list", "def_list", "abbr",
    "footnotes", "md_in_html", "toc", "sane_lists",
]

_MERMAID = re.compile(
    r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.DOTALL,
)

# The RULE in prompts.py says a diagram's info string must be exactly
# 'mermaid', and that a figure must never sit in a ```text / ```plaintext
# block. Gemini breaks that anyway — a real section came back with a perfectly
# valid "flowchart LR ... -->" inside a ```text fence, which rendered as a
# dark code block full of raw diagram source instead of a diagram. A prompt
# cannot be made authoritative here, so the renderer also recognises a diagram
# by its *body*: a fence in the text-ish family (or with no info string at
# all) whose first non-blank line starts with a Mermaid diagram keyword is
# treated exactly like ```mermaid. Anything else in a text fence is still a
# normal code block.
_MERMAID_START = re.compile(
    r"""^[ \t]*(?:
        (?:flowchart|graph)[ \t]+(?:TD|TB|BT|LR|RL)\b
      | (?:sequenceDiagram|classDiagram(?:-v2)?|stateDiagram(?:-v2)?
        |erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram
        |gitGraph|mindmap|timeline|sankey-beta|xychart-beta|block-beta
        |packet-beta|architecture-beta|kanban|radar-beta|treemap(?:-beta)?
        |zenuml|C4Context|C4Container|C4Component|C4Dynamic|C4Deployment)\b
    )""",
    re.VERBOSE,
)

_MAYBE_MERMAID_FENCE = re.compile(
    r'<pre><code(?: class="language-(?:text|txt|plaintext|plain|mmd)")?>'
    r"(.*?)</code></pre>",
    re.DOTALL,
)

# Mermaid has no server-side parser here (the client renders it), so a model
# that invents an arrow token produces a diagram that cannot render at all —
# the reader gets the "⚠ diagram could not be rendered" box instead. A generated
# diagram never *means* "invalid arrow", so the source is normalised before the
# browser sees it. This also repairs diagrams already saved to a book, and the
# exports, because it runs on every render pass.
#
# Verified against mermaid@10.9.1 (the version the client loads): in a
# sequenceDiagram "->" and "-->" are accepted, but "->-" is not; in flowchart /
# graph / stateDiagram / classDiagram a bare "->" is a parse error while "-->"
# is valid.
_MERMAID_PRE = re.compile(r'(<pre class="mermaid">)(.*?)(</pre>)', re.DOTALL)
_UNQUOTED_SINGLE_ARROW = re.compile(r"(?<![-.<>=])\s*->\s*(?![-.>])")


def _repair_mermaid_source(src: str) -> str:
    head = src.strip().split(None, 1)[0].lower() if src.strip() else ""
    if head == "sequencediagram":
        return src.replace("->-", "->>").replace("--->", "-->>")
    if head.startswith(("flowchart", "graph", "statediagram", "classdiagram")):
        out = []
        for line in src.splitlines():
            # Only rewrite a line with no quoted text: a label like ["a -> b"]
            # is literal and must be left alone.
            if "->" in line and '"' not in line and "'" not in line:
                line = _UNQUOTED_SINGLE_ARROW.sub(" --> ", line)
            out.append(line)
        return "\n".join(out)
    return src


def _repair_mermaid_blocks(html: str) -> str:
    def repl(m: re.Match) -> str:
        src = _repair_mermaid_source(_html.unescape(m.group(2)))
        return m.group(1) + _html.escape(src, quote=False) + m.group(3)

    return _MERMAID_PRE.sub(repl, html)

# A ```image-search block is a request the model makes for the server to
# resolve into a real image (see images.py's resolve_image_placeholders) —
# never content meant for a reader. It's supposed to always be replaced
# (with a real image, or dropped entirely if nothing usable turns up)
# before a generation is saved, but any gap in that path — a crash outside
# the per-placeholder guard, or a stray block copied into a *different*
# generation's output via picked "extra context" that had one still stuck
# in it — would otherwise leave this raw request block visible to the
# reader. This is the last line of defense: strip on every render/export
# pass too, not just at generation time, so any placeholder that slipped
# through by any means never actually reaches a reader — same pattern as
# images._PLACEHOLDER_RE.
_UNRESOLVED_IMAGE_SEARCH = re.compile(r"```image-search\s*\n.*?```\n?", re.DOTALL | re.IGNORECASE)


def strip_unresolved_image_placeholders(text: str) -> str:
    return _UNRESOLVED_IMAGE_SEARCH.sub("", text or "")

# LLMs reach for these when told to "add more images" — they render as a grey box
# that looks like a bug. Treat them as "figure intended but not available".
_PLACEHOLDER_HOSTS = (
    "placehold.co", "placeholder.com", "dummyimage.com", "fakeimg.pl", "fpoimg.com",
    "placekitten.com", "placeimg.com", "placebear.com", "baconmockup.com",
    "loremflickr.com", "lorempixel.com", "unsplash.it", "picsum.photos",
    "source.unsplash.com",
)

_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

# A lone image (optionally with a caption/attribution line right after it, no
# blank line between — the search-and-insert flow writes exactly this:
# "![alt](url)\n*attribution*") renders as ONE <p> holding both. Chrome's
# print engine doesn't reliably honour break-inside:avoid on a bare <img> (a
# replaced element) when it comes to page pagination — the image can still
# split across a page boundary. A block-level wrapper is respected reliably,
# so this promotes any single-image-only paragraph into a proper <figure>,
# with the caption line (if any) as a real <figcaption>.
_IMG_ONLY_P = re.compile(
    r"<p>\s*(<img\b[^>]*>)\s*(?:<em>(.*?)</em>)?\s*</p>", re.IGNORECASE | re.DOTALL,
)


# --------------------------------------------------------------------------- #
#  Math (LaTeX → MathML)                                                      #
# --------------------------------------------------------------------------- #
#
# Models write formulas as LaTeX — $…$, $$…$$, \(…\), \[…\] — and nothing in
# the app rendered them, so they reached the reader as raw "$\frac{V \times
# S}{T}$". Conversion happens here, server-side, rather than through KaTeX or
# MathJax on the client, because MathML is the one representation every
# consumer already shares: the live preview and the PDF/Pages exports all print
# through Chromium (MathML Core is native there), and EPUB3 supports MathML —
# so there is no CDN dependency and the exports match the preview exactly.
#
# Delimiters are matched conservatively: a `$` must not be backslash-escaped,
# there must be no space just inside the pair, inline math stays on one line,
# and the body has to contain a letter or a TeX command. That last rule is what
# keeps currency out of it — "$5-$7" or "$5 and $7" is prose, not a formula.
_MATH_DISPLAY = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL)
_MATH_DISPLAY_BRACKET = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_MATH_INLINE_PAREN = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_MATH_INLINE = re.compile(r"(?<!\\)\$(?!\s)([^$\n]*?)(?<!\s)(?<!\\)\$")
_MATH_HAS_SUBSTANCE = re.compile(r"[A-Za-z\\]")
# Fenced blocks and inline code spans, which must never be touched.
_CODE_SPAN = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]*`)", re.DOTALL)

try:  # optional at runtime: without it, formulas stay as written
    import latex2mathml.converter as _latex2mathml
except Exception:  # pragma: no cover - exercised only on a broken install
    _latex2mathml = None


def _mathml(tex: str, display: str) -> str | None:
    """MathML for one formula, or None when it cannot be converted (an
    unsupported command, unbalanced braces). None means "leave the source"."""
    if _latex2mathml is None or not tex.strip():
        return None
    try:
        return _latex2mathml.convert(tex.strip(), display=display)
    except Exception:
        return None


def _replace_math(text: str) -> str:
    def display_repl(m: re.Match) -> str:
        ml = _mathml(m.group(1), "block")
        if ml is None:
            return m.group(0)
        return f'\n\n<div class="math-block">{ml}</div>\n\n'

    def inline_repl(m: re.Match) -> str:
        body = m.group(1)
        if not _MATH_HAS_SUBSTANCE.search(body):
            return m.group(0)
        ml = _mathml(body, "inline")
        if ml is None:
            return m.group(0)
        return f'<span class="math-inline">{ml}</span>'

    text = _MATH_DISPLAY.sub(display_repl, text)
    text = _MATH_DISPLAY_BRACKET.sub(display_repl, text)
    text = _MATH_INLINE_PAREN.sub(inline_repl, text)
    return _MATH_INLINE.sub(inline_repl, text)


def _render_math(text: str) -> str:
    """Convert LaTeX delimiters outside code spans/fences to MathML."""
    parts = _CODE_SPAN.split(text)
    for i in range(0, len(parts), 2):     # odd indexes are the code spans
        parts[i] = _replace_math(parts[i])
    return "".join(parts)


def _wrap_image_figure(m: re.Match) -> str:
    img_tag, caption = m.group(1), m.group(2)
    inner = img_tag + (f"<figcaption>{caption}</figcaption>" if caption else "")
    return f'<figure class="img-figure">{inner}</figure>'


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', tag, re.IGNORECASE)
    return m.group(1) if m else ""


def _placeholder_figure(alt: str) -> str:
    label = _html.escape(alt.strip()) or "Figure"
    return (
        '<figure class="fig-placeholder">'
        '<span class="fig-icon" aria-hidden="true">▨</span>'
        f'<figcaption>{label}</figcaption>'
        "</figure>"
    )


def _fix_image(tag: str) -> str:
    src = _attr(tag, "src").strip()
    alt = _attr(tag, "alt")
    if not src or src.lower().startswith("javascript:"):
        return _placeholder_figure(alt)
    host = re.sub(r"^\w+://", "", src).split("/", 1)[0].lower().split("@")[-1]
    if any(host == h or host.endswith("." + h) for h in _PLACEHOLDER_HOSTS):
        return _placeholder_figure(alt)
    return tag


def _relabel_diagram_fences(html: str) -> str:
    """Turn a text/plain/unlabelled code fence whose body is a Mermaid diagram
    into a real mermaid figure. Everything else is left untouched."""
    def repl(m: re.Match) -> str:
        body = m.group(1)
        if _MERMAID_START.match(_html.unescape(body).lstrip()):
            return (f'<figure class="mermaid-figure"><pre class="mermaid">'
                    f"{body}</pre></figure>")
        return m.group(0)

    return _MAYBE_MERMAID_FENCE.sub(repl, html)


# Gemini also collapses whole bulleted lists onto ONE paragraph line,
# separating items with an inline " * " instead of putting each on its own
# line ("...outside the organization: * **Figurehead:** ... * **Leader:** ...").
# Markdown only starts a list item at the beginning of a line, so that renders
# as a run of literal asterisks mid-paragraph. Reflow such a line into a real
# list before conversion. Deliberately conservative so ordinary prose is never
# mangled: 2+ separators are required, a lone " *word* " emphasis marker is
# never a separator, and either the lead-in has to read like a list
# introduction (end with ":") or the items have to be long enough to be
# descriptions rather than emphasised words.
_BULLET_SEP = re.compile(r"(?<=\S)[ \t]+([*\u2022])[ \t]+(?=\S)")
_FENCE_BLOCK = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\1[ \t]*$",
                          re.DOTALL | re.MULTILINE)


def _reflow_inline_list(line: str) -> str:
    stripped = line.lstrip(" \t")
    # Leave alone anything that isn't plain prose: headings, quotes, tables,
    # indented code, and lines that already open with a list marker.
    if not stripped or stripped[0] in "#>|" or line[:1] in (" ", "\t"):
        return line
    if re.match(r"(?:[*+\-\u2022]|\d+[.)])[ \t]", stripped):
        return line

    seps = list(_BULLET_SEP.finditer(line))
    if len(seps) < 2:
        return line

    lead = line[:seps[0].start()].rstrip()
    items, start = [], seps[0].end()
    for sep in seps[1:]:
        items.append(line[start:sep.start()].strip())
        start = sep.end()
    items.append(line[start:].strip())

    # Every item has to look like list content, not an emphasised word.
    if any(len(it) < 8 or " " not in it for it in items):
        return line
    if not (not lead or lead.endswith(":")) and len(items) < 3:
        return line

    bullets = "\n".join(f"- {it}" for it in items)
    return f"{lead}\n\n{bullets}" if lead else bullets


def _reflow_inline_lists(text: str) -> str:
    """Apply _reflow_inline_list to prose only — never inside a code fence."""
    out, pos = [], 0
    for m in _FENCE_BLOCK.finditer(text):
        out.append("\n".join(_reflow_inline_list(ln)
                             for ln in text[pos:m.start()].split("\n")))
        out.append(m.group(0))
        pos = m.end()
    out.append("\n".join(_reflow_inline_list(ln)
                         for ln in text[pos:].split("\n")))
    return "".join(out)


def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=MD_EXTENSIONS, output_format="html5")
    # Python-Markdown's default escapable set doesn't include "$" — the model
    # sometimes writes "\$42" (a habit from contexts where "$" starts inline
    # math), which without this just passes the literal backslash straight
    # through into the rendered page instead of being consumed as an escape.
    md.ESCAPED_CHARS.append("$")
    text = strip_unresolved_image_placeholders(text)
    text = _render_math(text)
    text = _reflow_inline_lists(text)
    html = md.convert(text or "")
    html = _MERMAID.sub(
        r'<figure class="mermaid-figure"><pre class="mermaid">\1</pre></figure>',
        html,
    )
    html = _relabel_diagram_fences(html)
    html = _repair_mermaid_blocks(html)
    # Wrap an image+caption paragraph into one <figure> BEFORE checking for a
    # broken/placeholder src — reversed, a broken image gets swapped for its
    # own <figure class="fig-placeholder"> first, which no longer matches
    # _IMG_ONLY_P's "<p><img>...<em>caption</em></p>" pattern (there's no
    # <img> left inside the <p>), orphaning the caption as a disconnected
    # paragraph below the placeholder box instead of attached to it.
    html = _IMG_ONLY_P.sub(_wrap_image_figure, html)
    html = _IMG_TAG.sub(lambda m: _fix_image(m.group(0)), html)
    return html
