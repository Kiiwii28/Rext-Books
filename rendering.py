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


def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=MD_EXTENSIONS, output_format="html5")
    # Python-Markdown's default escapable set doesn't include "$" — the model
    # sometimes writes "\$42" (a habit from contexts where "$" starts inline
    # math), which without this just passes the literal backslash straight
    # through into the rendered page instead of being consumed as an escape.
    md.ESCAPED_CHARS.append("$")
    text = strip_unresolved_image_placeholders(text)
    html = md.convert(text or "")
    html = _MERMAID.sub(
        r'<figure class="mermaid-figure"><pre class="mermaid">\1</pre></figure>',
        html,
    )
    # Wrap an image+caption paragraph into one <figure> BEFORE checking for a
    # broken/placeholder src — reversed, a broken image gets swapped for its
    # own <figure class="fig-placeholder"> first, which no longer matches
    # _IMG_ONLY_P's "<p><img>...<em>caption</em></p>" pattern (there's no
    # <img> left inside the <p>), orphaning the caption as a disconnected
    # paragraph below the placeholder box instead of attached to it.
    html = _IMG_ONLY_P.sub(_wrap_image_figure, html)
    html = _IMG_TAG.sub(lambda m: _fix_image(m.group(0)), html)
    return html
