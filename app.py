"""Rextbooks - recursive textbook generator.

Run with:
    python app.py
Then open http://127.0.0.1:5000
"""

from __future__ import annotations

import json
import re

import requests
from flask import (
    Flask, Response, jsonify, render_template, request,
    send_from_directory, stream_with_context,
)
from werkzeug.utils import secure_filename

import config
import deepseek
import epub
import export
import images
import palettes
import prompts
import sparks
import store
from rendering import render_markdown

app = Flask(__name__)


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", text or "").strip().replace(" ", "-")
    return s[:60] or "rextbook"


# --------------------------------------------------------------------------- #
#  Pages                                                                       #
# --------------------------------------------------------------------------- #

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "model": config.DEEPSEEK_MODEL,
                    "pdf": export.pdf_available(), "pdfEngine": export.pdf_engine()})


# --------------------------------------------------------------------------- #
#  Settings (API key)                                                          #
# --------------------------------------------------------------------------- #

@app.get("/api/settings")
def api_get_settings():
    return jsonify({
        "hasApiKey": bool(config.get_api_key()),
        "keySource": config.api_key_source(),   # "settings" | "env" | "none"
        "model": config.DEEPSEEK_MODEL,
        "author": config.get_author(),
    })


@app.post("/api/settings")
def api_save_settings():
    data = request.get_json(silent=True) or {}
    if "apiKey" not in data and "author" not in data:
        return jsonify({"error": "apiKey or author is required"}), 400
    if "apiKey" in data:
        config.set_api_key(data.get("apiKey") or "")
    if "author" in data:
        config.set_author(data.get("author") or "")
    return jsonify({
        "hasApiKey": bool(config.get_api_key()),
        "keySource": config.api_key_source(),
        "author": config.get_author(),
    })


@app.post("/api/settings/test")
def api_test_settings():
    data = request.get_json(silent=True) or {}
    key = (data.get("apiKey") or "").strip() or config.get_api_key()
    if not key:
        return jsonify({"ok": False, "error": "No API key to test."}), 400
    ok, message = deepseek.test_key(key)
    return jsonify({"ok": ok, "error": None if ok else message})


@app.post("/render")
def render():
    data = request.get_json(silent=True) or {}
    return jsonify({"html": render_markdown(data.get("text", ""))})


@app.get("/api/palettes")
def api_palettes():
    return jsonify(palettes.PALETTES)


@app.get("/api/spark-modes")
def api_spark_modes():
    return jsonify(sparks.modes_summary())


# --------------------------------------------------------------------------- #
#  Books CRUD                                                                  #
# --------------------------------------------------------------------------- #

@app.get("/api/books")
def api_list_books():
    return jsonify(store.list_books())


@app.post("/api/books")
def api_create_book():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    title = (data.get("title") or "").strip()
    if not topic and not title:
        return jsonify({"error": "topic is required"}), 400
    return jsonify(store.create_book(topic=topic, title=title)), 201


@app.post("/api/books/import")
def api_import_book():
    if "file" in request.files:
        try:
            data = json.loads(request.files["file"].read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return jsonify({"error": "not valid JSON"}), 400
    else:
        data = request.get_json(silent=True)
    try:
        return jsonify(store.import_book(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/books/<book_id>")
def api_get_book(book_id: str):
    book = store.get_book(book_id)
    if book is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(book)


@app.route("/api/books/<book_id>", methods=["PUT", "POST"])  # POST = sendBeacon fallback
def api_save_book(book_id: str):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid body"}), 400
    try:
        return jsonify(store.save_book(book_id, data))
    except KeyError:
        return jsonify({"error": "not found"}), 404


@app.delete("/api/books/<book_id>")
def api_delete_book(book_id: str):
    return jsonify({"deleted": store.delete_book(book_id)})


@app.get("/api/books/<book_id>/versions")
def api_book_versions(book_id: str):
    try:
        return jsonify(store.list_versions(book_id))
    except ValueError:
        return jsonify({"error": "bad id"}), 400


@app.post("/api/books/<book_id>/restore")
def api_restore_version(book_id: str):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(store.restore_version(book_id, data.get("file", "")))
    except (KeyError, ValueError):
        return jsonify({"error": "version not found"}), 404


# --------------------------------------------------------------------------- #
#  Images                                                                      #
# --------------------------------------------------------------------------- #

@app.post("/api/books/<book_id>/images")
def api_upload_image(book_id: str):
    if store.get_book(book_id) is None:
        return jsonify({"error": "book not found"}), 404
    try:
        if "image" in request.files:
            data = request.files["image"].read()
        else:
            body = request.get_json(silent=True) or {}
            if body.get("dataUrl"):
                data = images.decode_data_url(body["dataUrl"])
            elif body.get("url"):
                fetched = images.fetch_remote(body["url"])
                if fetched is None:
                    # keep the external reference as-is
                    url = body["url"].strip()
                    return jsonify({"url": url, "markdown": f"![]({url})", "external": True})
                data = fetched
            else:
                return jsonify({"error": "no image, dataUrl or url provided"}), 400
        return jsonify(images.save_image(book_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/assets/<book_id>/<path:filename>")
def serve_asset(book_id: str, filename: str):
    try:
        directory = store.assets_dir(book_id)
    except ValueError:
        return jsonify({"error": "bad id"}), 400
    return send_from_directory(directory, secure_filename(filename))


# --------------------------------------------------------------------------- #
#  Export                                                                      #
# --------------------------------------------------------------------------- #

def _parse_exclude() -> set:
    """Node ids to leave out of an export — from the Export dialog's content
    picker. Absent/empty means "export everything" (unchanged default)."""
    raw = request.args.get("exclude", "")
    return {x for x in raw.split(",") if x}


@app.get("/api/books/<book_id>/export.json")
def export_json(book_id: str):
    book = store.get_book(book_id)
    if book is None:
        return jsonify({"error": "not found"}), 404
    exclude_ids = _parse_exclude()
    if exclude_ids:
        book = dict(book)
        book["nodes"] = export.filter_book_nodes(book.get("nodes") or [], exclude_ids)
    return Response(json.dumps(book, ensure_ascii=False, indent=2),
                    mimetype="application/json; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.json"',
    })


@app.get("/api/books/<book_id>/export.md")
def export_md(book_id: str):
    book = store.get_book(book_id)
    if book is None:
        return jsonify({"error": "not found"}), 404
    md = export.book_to_markdown(book, base_url=request.url_root, exclude_ids=_parse_exclude())
    return Response(md, mimetype="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.md"',
    })


@app.get("/api/books/<book_id>/export.pdf")
def export_pdf(book_id: str):
    book = store.get_book(book_id)
    if book is None:
        return jsonify({"error": "not found"}), 404
    if not export.pdf_available():
        return jsonify({"error": export.pdf_error()}), 501
    palette = request.args.get("palette") or (book.get("settings") or {}).get("palette")
    pdf = export.book_to_pdf(book, palette, base_url=request.url_root, exclude_ids=_parse_exclude())
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.pdf"',
    })


@app.get("/api/books/<book_id>/export.epub")
def export_epub(book_id: str):
    book = store.get_book(book_id)
    if book is None:
        return jsonify({"error": "not found"}), 404
    palette = request.args.get("palette") or (book.get("settings") or {}).get("palette")
    try:
        data = epub.book_to_epub(book, palette, base_url=request.url_root, exclude_ids=_parse_exclude())
    except Exception as exc:
        return jsonify({"error": f"EPUB export failed: {exc}"}), 500
    return Response(data, mimetype="application/epub+zip", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.epub"',
    })


@app.get("/api/books/<book_id>/preview")
def export_preview(book_id: str):
    book = store.get_book(book_id)
    if book is None:
        return jsonify({"error": "not found"}), 404
    palette = request.args.get("palette") or (book.get("settings") or {}).get("palette")
    html_doc = export.book_to_html(book, palette, exclude_ids=_parse_exclude())
    if request.args.get("print"):
        # Browser "Save as PDF" fallback. Wait for Mermaid (if any) before printing.
        wait = (
            "<script>(function(){function go(){setTimeout(function(){window.print();},250);}"
            "if(document.querySelector('pre.mermaid')){var n=0;var t=setInterval(function(){"
            "if(document.body.dataset.mermaidDone||n++>40){clearInterval(t);go();}},150);}"
            "else{window.addEventListener('load',go);}})();</script>"
        )
        html_doc = html_doc.replace("</body>", wait + "</body>")
    return html_doc


# --------------------------------------------------------------------------- #
#  AI generation (SSE stream)                                                  #
# --------------------------------------------------------------------------- #

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _collect_context(book: dict, ids: list, *, exclude_ids: set | None = None) -> list[str]:
    """Build one context block from exactly the nodes the user ticked.

    The frontend auto-ticks a parent's descendants, then lets the user untick
    individual ones — so we include only the ticked ids (not whole subtrees),
    emitted in document order so the excerpt reads like a slice of the outline.

    ``exclude_ids`` drops the node(s) actually being generated right now, so a
    bulk run where the user ticked the very blocks being generated as context
    for one another never lets a block see its own (stale, about-to-be-
    overwritten) content.
    """
    want = set(ids or []) - (exclude_ids or set())
    if not want:
        return []

    budget = config.CONTEXT_CHAR_BUDGET
    lines: list[str] = []

    def rec(nodes: list[dict], depth: int) -> None:
        nonlocal budget
        for n in nodes:
            if budget > 0 and n.get("id") in want:
                if n.get("type") == "section":
                    body = (n.get("content") or "").strip()
                    if body:
                        chunk = body[:budget]
                        lines.append(chunk)
                        budget -= len(chunk)
                else:
                    title = (n.get("title") or "").strip()
                    if title:
                        lines.append("#" * min(depth + 1, 4) + " " + title)
                        budget -= len(title) + 4
            rec(n.get("children") or [], depth + 1)

    rec(book.get("nodes") or [], 0)
    text = "\n\n".join(lines).strip()
    return [text] if text else []


def _stream_chat_response(messages: list[dict], start_payload: dict) -> Response:
    """Shared SSE wrapper for /api/ai/generate and /api/ai/spark."""
    @stream_with_context
    def generate():
        yield _sse("start", start_payload)
        try:
            for piece in deepseek.stream_chat(messages):
                yield _sse("delta", {"text": piece})
            yield _sse("done", {})
        except requests.HTTPError as exc:
            yield _sse("error", {"message": str(exc)})
        except requests.RequestException as exc:
            yield _sse("error", {"message": f"network error: {exc}"})
        except RuntimeError as exc:  # missing API key etc.
            yield _sse("error", {"message": str(exc)})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/ai/generate")
def api_generate():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    book_id = body.get("bookId")
    node_id = body.get("nodeId")
    user_prompt = (body.get("prompt") or "").strip()
    tone = body.get("tone")
    depth = body.get("depth")
    refine = bool(body.get("refine"))
    context_ids = body.get("contextIds") or []

    if mode not in prompts.MODES:
        return jsonify({"error": f"mode must be one of {prompts.MODES}"}), 400
    if not user_prompt:
        return jsonify({"error": "prompt is required"}), 400

    book = store.get_book(book_id) if book_id else None
    if book is None:
        return jsonify({"error": "book not found"}), 404

    node, _parent = (None, None)
    if node_id:
        node, _parent = store.find_node(book.get("nodes", []), node_id)

    if mode == "subheadings" and node is None:
        return jsonify({"error": "select a heading first"}), 400
    if mode == "content" and node is None:
        return jsonify({"error": "select a subheading first"}), 400

    # For "refine", feed the existing section text back to the model.
    refine_source = None
    if mode == "content" and refine and node is not None:
        if node.get("type") == "section":
            refine_source = node.get("content") or ""
        else:
            sec = next((c for c in node.get("children", []) if c.get("type") == "section"), None)
            refine_source = (sec or {}).get("content") or ""
        if not refine_source.strip():
            refine_source = None

    # Extra context: other nodes the user picked, flattened to text. Exclude the
    # node being generated (and, for content, its own section) even if it's
    # among the picks — e.g. a bulk run where the ticked context is the same
    # set of siblings being generated.
    exclude_ids: set = set()
    if node is not None:
        exclude_ids.add(node.get("id"))
        if mode == "content":
            for child in node.get("children") or []:
                if child.get("type") == "section":
                    exclude_ids.add(child.get("id"))
    context_blocks = _collect_context(book, context_ids, exclude_ids=exclude_ids)
    overarching = (book.get("settings") or {}).get("overarchingPrompt") or ""

    messages = prompts.build_messages(
        mode, user_prompt, tone=tone, depth=depth, refine_source=refine_source,
        context_blocks=context_blocks, overarching=overarching,
    )
    return _stream_chat_response(messages, {
        "mode": mode, "refine": refine_source is not None, "context": len(context_blocks),
    })


@app.post("/api/ai/spark")
def api_spark():
    body = request.get_json(silent=True) or {}
    book_id = body.get("bookId")
    spark_mode = body.get("sparkMode")
    a_id, b_id = body.get("aId"), body.get("bId")
    user_prompt = (body.get("prompt") or "").strip()

    if spark_mode not in sparks.SPARK_MODES:
        return jsonify({"error": "unknown spark mode"}), 400
    if not user_prompt:
        return jsonify({"error": "prompt is required"}), 400

    book = store.get_book(book_id) if book_id else None
    if book is None:
        return jsonify({"error": "book not found"}), 404

    a_node, _ = store.find_node(book.get("nodes", []), a_id)
    b_node, _ = store.find_node(book.get("nodes", []), b_id)
    if a_node is None or b_node is None:
        return jsonify({"error": "pick two blocks from this book"}), 400

    half = max(2000, config.CONTEXT_CHAR_BUDGET // 2)
    settings = book.get("settings") or {}
    messages = sparks.build_spark_messages(
        spark_mode, user_prompt,
        store.node_as_text(a_node, limit=half),
        store.node_as_text(b_node, limit=half),
        a_title=a_node.get("title") or "A",
        b_title=b_node.get("title") or "B",
        tone=settings.get("tone"), depth=settings.get("depth"),
        overarching=settings.get("overarchingPrompt"),
    )
    return _stream_chat_response(messages, {"mode": "spark", "sparkMode": spark_mode})


if __name__ == "__main__":
    # threaded=True so the preview / asset endpoints stay responsive while an
    # SSE generation stream is in flight (and so PDF export can fetch /assets).
    #
    # use_reloader=False: the debug reloader restarts itself by re-invoking
    # sys.executable — in this venv that alternates between the venv's own
    # python.exe and the base interpreter on each restart, cascading into a
    # chain of several processes all fighting over the same port instead of
    # one clean process. debug=True is kept (still get readable tracebacks
    # in the browser on a crash); only the file-watching auto-restart is off,
    # which isn't needed anyway when just running the app rather than
    # actively editing its source.
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)
