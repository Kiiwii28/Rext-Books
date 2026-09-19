"""Lite-export image compression, shared by the PDF and EPUB exporters.

Pure-Pillow (already a dependency via reportlab/EPUB's Mermaid rasterizer) —
no external binaries required. Every function here is conservative on
purpose: it falls back to the original, untouched bytes on any failure, on
an unsupported format, or if the result wouldn't actually be smaller. Lite
mode should make a book's exports smaller, never the reason an image goes
missing, a page breaks, or a diagram looks wrong.
"""

from __future__ import annotations

from io import BytesIO

try:
    from PIL import Image
except ImportError:                # pragma: no cover - degrades to a no-op
    Image = None

CONTENT_MAX_DIM = 1000   # px, long edge — plenty for a textbook page/e-reader
JPEG_QUALITY = 72
DIAGRAM_SHOT_SCALE = 1.3   # vs. epub.py's normal 2x — still crisp, notably smaller


def shrink_image_bytes(data: bytes, *, max_dim: int = CONTENT_MAX_DIM,
                        jpeg_quality: int = JPEG_QUALITY) -> bytes:
    """Resize-if-needed + re-encode one already-fetched image file, for the
    EPUB path (images are embedded as plain files there).

    Keeps the original format — never converts PNG<->JPEG — so a diagram or
    screenshot that relies on transparency never regresses into a solid
    background. Returns the input unchanged if Pillow isn't installed, the
    format isn't one of the two handled here, decoding fails, or shrinking
    it didn't actually save anything.
    """
    if Image is None:
        return data
    try:
        im = Image.open(BytesIO(data))
        fmt = (im.format or "").upper()
        if fmt not in ("JPEG", "PNG"):
            return data
        im.load()
        w, h = im.size
        scale = max_dim / max(w, h)
        if scale < 1:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        buf = BytesIO()
        if fmt == "JPEG":
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(buf, format="JPEG", quality=jpeg_quality, optimize=True, progressive=True)
        else:
            im.save(buf, format="PNG", optimize=True)
        out = buf.getvalue()
        return out if len(out) < len(data) else data
    except Exception:
        return data


def compress_pdf_images(pdf_bytes: bytes, *, max_dim: int = CONTENT_MAX_DIM,
                        jpeg_quality: int = JPEG_QUALITY) -> bytes:
    """Recompress every raster image already embedded in a finished PDF —
    photos Chrome printed in at their original resolution — in place:
    resized to fit ``max_dim`` and re-encoded as JPEG.

    This runs as a post-process on the PDF bytes rather than trying to
    intercept what Chrome fetches, so it works regardless of how large the
    source photos were and needs no changes to the live preview/asset
    routes. Mermaid diagrams in the PDF are native vector drawing (Chrome
    prints the live SVG, not a raster), so there's nothing to shrink there.

    Falls back to the untouched input on any failure, and specifically
    checks the page count is unchanged before accepting the result — never
    silently drops a page over an image that failed to re-encode.
    """
    if Image is None:
        return pdf_bytes
    try:
        import pypdf
    except ImportError:
        return pdf_bytes
    try:
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        writer = pypdf.PdfWriter()
        writer.append(reader)
        for page in writer.pages:
            for img in page.images:
                try:
                    pil_img = img.image
                    w, h = pil_img.size
                    scale = max_dim / max(w, h)
                    if scale < 1:
                        pil_img = pil_img.resize(
                            (max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
                    if pil_img.mode not in ("RGB", "L"):
                        pil_img = pil_img.convert("RGB")
                    img.replace(pil_img, quality=jpeg_quality)
                except Exception:
                    continue   # leave this one image untouched; never fail the whole export
        out = BytesIO()
        writer.write(out)
        result = out.getvalue()
        if len(pypdf.PdfReader(BytesIO(result)).pages) != page_count:
            return pdf_bytes   # sanity check failed — bail out to the safe original
        return result if len(result) < len(pdf_bytes) else pdf_bytes
    except Exception:
        return pdf_bytes
