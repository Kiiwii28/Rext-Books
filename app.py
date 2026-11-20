"""Rextbooks - recursive textbook generator.

Run with:
    python app.py
Then open http://127.0.0.1:5000
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import zipfile
from io import BytesIO

import requests
from flask import (
    Flask, Response, jsonify, render_template, request,
    send_from_directory, session, stream_with_context,
)
from werkzeug.utils import secure_filename

import config
import epub
import export
import images
import llm
import pages
import palettes
import prompt_store
import prompts
import sparks
import store
from bundle import book_to_bundle, read_bundle, rebind_images
from rendering import render_markdown

app = Flask(__name__)
# Static files (JS/CSS) default to Werkzeug's heuristic caching, which can let
# a browser keep serving a stale module/stylesheet across an ordinary reload
# for a long time after it's changed on disk — a normal refresh looked like
# it "didn't work" even though the file itself was already fixed. Forcing a
# revalidation (a fast 304 when unchanged, a fresh copy when not) on every
# request means an edit is always picked up on the very next reload, no hard
# refresh required.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# The session cookie only ever holds an opaque key-bundle id (see config.py);
# the passcode itself is never stored. A stable signing key matters on a hosted
# instance: without one, everyone would be logged out of their bundle on every
# restart/redeploy.
app.secret_key = config.get_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("REXTBOOKS_HTTPS", "").strip() in ("1", "true", "yes"),
)


@app.before_request
def _apply_key_bundle():
    """Resolve the caller's key bundle for this request only. Thread-local
    rather than global state, so two people using the same instance each keep
    their own bundle — and their own provider choice within it."""
    config.set_active_bundle(session.get("bundle"))
    config.set_request_provider(session.get("provider"))
    config.set_request_models(session.get("models"))
    # A stable per-browser id. Every book is stamped with it and only ever
    # listed back to the same browser, so opening the hosted app on another
    # device is a clean slate. It lives in the signed cookie, so it survives
    # redeploys as long as the session signing key does.
    if not session.get("owner"):
        session["owner"] = secrets.token_hex(16)
        session.permanent = True


@app.teardown_request
def _clear_key_bundle(_exc=None):
    config.clear_active_bundle()


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
    status = config.llm_status()
    return jsonify({"status": "ok",
                    "provider": status["provider"],
                    "label": status["label"],
                    "model": status["model"],
                    "pdf": export.pdf_available(), "pdfEngine": export.pdf_engine()})


# --------------------------------------------------------------------------- #
#  Settings (provider, model, API keys)                                        #
# --------------------------------------------------------------------------- #

def _settings_payload() -> dict:
    """Everything the Settings dialog needs, and nothing secret. The key is
    only ever reported as present/absent plus where it came from."""
    active = config.llm_status()
    return {
        # Generation model selection.
        "provider": active["provider"],
        "providerLabel": active["label"],
        "model": active["model"],
        "defaultModel": active["defaultModel"],
        "models": active["models"],
        # Empty list = no restriction; otherwise a key bundle named the models
        # this user may pick, and the dialog shows only those.
        "allowedModels": active["allowedModels"],
        "modelLocked": active["modelLocked"],
        "contextChars": active["contextChars"],
        "providers": config.llm_providers(),
        # Credential state for the active provider only (never the key itself).
        "hasApiKey": active["hasApiKey"],
        "keySource": active["keySource"],
        "keyPlaceholder": active["keyPlaceholder"],
        "keysUrl": active["keysUrl"],
        # Book / export settings.
        "author": config.get_author(),
        "blurbTemplate": config.get_blurb_template(),
        "blurbDefault": config.DEFAULT_BLURB_TEMPLATE,
        "hasPexelsKey": bool(config.get_pexels_key()),
        "pexelsUsage": config.get_pexels_usage(),
        # "Master key" state: whether bundles are configured at all, and if one
        # is unlocked for this browser, which providers it supplies.
        "keyBundle": config.key_bundle_info(),
    }


@app.get("/api/settings")
def api_get_settings():
    return jsonify(_settings_payload())


@app.post("/api/settings")
def api_save_settings():
    data = request.get_json(silent=True) or {}
    if not {"apiKey", "provider", "model", "author", "blurbTemplate",
            "pexelsApiKey"} & data.keys():
        return jsonify({
            "error": "apiKey, provider, model, author, blurbTemplate or "
                     "pexelsApiKey is required"
        }), 400
    # Provider first: a model/key sent alongside it belongs to that provider.
    try:
        if "provider" in data:
            chosen = config.set_llm_provider(data.get("provider") or "")
            # Inside a bundle the choice belongs to this browser, not to the
            # shared settings file — otherwise one person's switch would change
            # everyone else's provider too.
            if config.get_active_bundle() is not None:
                session["provider"] = chosen
        target = data.get("provider") or config.get_llm_provider()
        if "model" in data:
            config.set_llm_model(data.get("model") or "", provider=target)
            # Same reasoning as the provider above: inside a bundle the model
            # choice belongs to this browser's session, not the shared file.
            if config.get_active_bundle() is not None:
                session["models"] = config.request_models()
        if "apiKey" in data:
            config.set_api_key(data.get("apiKey") or "", provider=target)
    except (ValueError, RuntimeError) as exc:
        # RuntimeError = an unlocked key bundle supplies this, so writing would
        # change the shared settings file for everyone else on the instance.
        return jsonify({"error": str(exc)}), 400
    if "author" in data:
        config.set_author(data.get("author") or "")
    if "blurbTemplate" in data:
        config.set_blurb_template(data.get("blurbTemplate") or "")
    if "pexelsApiKey" in data:
        try:
            config.set_pexels_key(data.get("pexelsApiKey") or "")
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 400
    return jsonify(_settings_payload())


# --- key bundles ("master keys") ------------------------------------------ #
# A passcode fills in every provider key at once. Only an opaque id goes into
# the signed session cookie, so unlocking is per-browser: two people on the
# same instance never overwrite each other's keys. Attempts are rate-limited
# per client so a short passcode can't be brute-forced.

_UNLOCK_WINDOW = 300          # seconds
_UNLOCK_MAX_ATTEMPTS = 10
_unlock_attempts: dict[str, list[float]] = {}
_unlock_lock = threading.Lock()


def _unlock_client() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "local").split(",")[0].strip()


def _unlock_allowed() -> bool:
    now = time.time()
    with _unlock_lock:
        tries = [t for t in _unlock_attempts.get(_unlock_client(), []) if now - t < _UNLOCK_WINDOW]
        _unlock_attempts[_unlock_client()] = tries
        return len(tries) < _UNLOCK_MAX_ATTEMPTS


def _unlock_record_failure() -> None:
    with _unlock_lock:
        _unlock_attempts.setdefault(_unlock_client(), []).append(time.time())


@app.post("/api/settings/unlock")
def api_settings_unlock():
    data = request.get_json(silent=True) or {}
    passcode = (data.get("passcode") or "").strip()
    owner_before_unlock = session.get("owner")
    if not config.bundles_configured():
        return jsonify({"error": "No key bundles are configured on this server."}), 400
    if not _unlock_allowed():
        return jsonify({"error": "Too many attempts — wait a few minutes and try again."}), 429
    bundle = config.resolve_passcode(passcode)
    if bundle is None:
        _unlock_record_failure()
        return jsonify({"error": "That key isn't valid."}), 401
    session.clear()                     # fresh session; nothing from before is trusted
    session["bundle"] = bundle["id"]
    # `session.clear()` must not orphan this browser's books.
    session["owner"] = owner_before_unlock or secrets.token_hex(16)
    session.permanent = True
    # before_request already ran for this request, so pin the bundle here too —
    # otherwise the payload would report the state from *before* unlocking.
    config.set_active_bundle(bundle["id"])
    return jsonify(_settings_payload())


@app.post("/api/settings/lock")
def api_settings_lock():
    session.pop("bundle", None)
    session.pop("provider", None)   # back to this machine's own provider choice
    session.pop("models", None)     # ...and its own model choices
    config.clear_active_bundle()
    return jsonify(_settings_payload())


@app.post("/api/settings/test")
def api_test_settings():
    data = request.get_json(silent=True) or {}
    provider = data.get("provider")
    key = (data.get("apiKey") or "").strip() or config.get_api_key(provider)
    if not key:
        label = config.llm_status(provider)["label"]
        return jsonify({"ok": False, "error": f"No {label} API key to test."}), 400
    model = (data.get("model") or "").strip() or None
    ok, message = llm.test_key(key, provider=provider, model=model)
    return jsonify({"ok": ok, "message": message, "error": None if ok else message})


# --------------------------------------------------------------------------- #
#  Prompt text (Settings → Advanced)                                           #
# --------------------------------------------------------------------------- #
#
# The golden text lives in prompts.defaults.json; user edits go to
# prompts.local.json as sparse overrides. Nothing here touches the code path's
# prompt assembly — it only edits the data that assembly reads, so an edit
# applies to the very next generation.

@app.get("/api/prompts")
def api_get_prompts():
    return jsonify({"blocks": prompt_store.blocks()})


@app.post("/api/prompts")
def api_save_prompts():
    data = request.get_json(silent=True) or {}
    blocks = data.get("blocks")
    if not isinstance(blocks, dict):
        return jsonify({"error": "blocks must be an object of {key: text}"}), 400
    updates = {k: v for k, v in blocks.items() if isinstance(v, str)}
    try:
        warnings = prompt_store.set_overrides(updates)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"blocks": prompt_store.blocks(), "warnings": warnings})


@app.post("/api/prompts/reset")
def api_reset_prompts():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys")
    if keys is not None and not isinstance(keys, list):
        return jsonify({"error": "keys must be a list of prompt ids"}), 400
    prompt_store.reset([str(k) for k in keys] if keys is not None else None)
    return jsonify({"blocks": prompt_store.blocks()})


@app.post("/api/prompts/preview")
def api_preview_prompts():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode") or "content"
    if mode not in prompts.MODES:
        return jsonify({"error": f"mode must be one of {prompts.MODES}"}), 400
    messages = prompts.build_messages(
        mode,
        data.get("prompt") or prompts.default_prompt(
            mode, topic="the book's topic", title="Sample subsection", count=3),
        tone=data.get("tone") or None,
        depth=data.get("depth") or None,
        use_images=bool(data.get("useImages")),
        image_frequency=data.get("imageFrequency") or "Medium",
        diagram_frequency=data.get("diagramFrequency") or "Medium",
        length=data.get("length") or "Medium",
        summary_section=bool(data.get("summarySection", True)),
        terminology_section=bool(data.get("terminologySection")),
    )
    return jsonify({"messages": messages})


@app.post("/render")
def render():
    data = request.get_json(silent=True) or {}
    return jsonify({"html": render_markdown(data.get("text", ""))})


@app.get("/api/palettes")
def api_palettes():
    return jsonify(palettes.all_palettes())


@app.post("/api/palettes")
def api_create_palette():
    try:
        key, palette = palettes.create_custom(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"key": key, "palette": palette}), 201


@app.delete("/api/palettes/<key>")
def api_delete_palette(key: str):
    if key in palettes.PALETTES:
        return jsonify({"error": "Built-in palettes can't be deleted."}), 400
    if not palettes.delete_custom(key):
        return jsonify({"error": "No such custom palette."}), 404
    return jsonify({"ok": True})


@app.get("/api/spark-modes")
def api_spark_modes():
    return jsonify(sparks.modes_summary())


# --------------------------------------------------------------------------- #
#  Books CRUD                                                                  #
# --------------------------------------------------------------------------- #
#
# Books are per-browser. Every book records the id of the browser that created
# it, kept in the signed session cookie, and every route below only ever sees
# books with that owner. Opening the hosted app on another device is therefore
# a clean slate; the same browser gets its books back (and the vault restores
# them if the server's disk was wiped).

def _owner() -> str:
    return session.get("owner") or ""


def _preview_token(book_id: str) -> str:
    """Proof that this server built a render URL for this book.

    The PDF exporter loads ``/api/books/<id>/preview`` in headless Chrome,
    which carries no session cookie — so an owner-only check there would 404
    the export. The token is derived from the app secret and the book id, so
    only the URL we just generated works, without exposing the book to anyone
    who merely guesses an id.
    """
    return hmac.new(app.secret_key.encode(), f"{book_id}:{_owner()}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def _preview_authorised(book_id: str) -> bool:
    token = request.args.get("token") or ""
    return bool(token) and hmac.compare_digest(token, _preview_token(book_id))


@app.get("/api/books")
def api_list_books():
    return jsonify(store.list_books(owner=_owner()))


@app.post("/api/books")
def api_create_book():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()
    title = (data.get("title") or "").strip()
    if not topic and not title:
        return jsonify({"error": "topic is required"}), 400
    return jsonify(store.create_book(topic=topic, title=title, owner=_owner())), 201


@app.post("/api/books/import")
def api_import_book():
    """Import a book — either a plain JSON file (the old format, still
    accepted) or a JSON+images bundle .zip, in which case its images are copied
    into the new book's own asset folder so nothing comes back broken."""
    if "file" in request.files:
        raw = request.files["file"].read()
        if raw[:4] == b"PK\x03\x04":
            return _import_bundle(raw)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return jsonify({"error": "not valid JSON"}), 400
    else:
        data = request.get_json(silent=True)
    try:
        return jsonify(store.import_book(data, owner=_owner())), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def _import_bundle(raw: bytes):
    """Create a book from an exported JSON+images bundle.

    The book is created first so it has an id to put images under, then the
    images are written into ``books/assets/<new id>/`` and the bundle's
    ``Images/<name>`` references re-pointed at that folder. A failure to write
    an individual image is skipped rather than failing the whole import — a
    book with one missing picture beats losing the book."""
    try:
        data, images = read_bundle(raw)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        book = store.import_book(data, owner=_owner())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    written: dict[str, bytes] = {}
    folder = store.assets_dir(book["id"])
    for name, blob in images.items():
        safe = secure_filename(name)
        if not safe:
            continue
        try:
            (folder / safe).write_bytes(blob)
        except OSError:
            continue
        written[name] = blob
    if written:
        book = store.save_book(book["id"], rebind_images(book, book["id"], written),
                               owner=_owner())
    return jsonify(book), 201


@app.get("/api/books/<book_id>")
def api_get_book(book_id: str):
    book = store.get_book(book_id, owner=_owner())
    if book is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(book)


@app.post("/api/books/restore")
def api_restore_book():
    """Re-create a book from the browser's own cached copy.

    A hosted instance wipes its disk on every redeploy and on free-tier
    spin-down, so the browser (see static/js/local-store.js) keeps a mirror of
    each book it has opened and pushes back anything the server has lost. This
    only ever *creates* a missing book: if the id already exists the stored
    copy is returned untouched, so it can't roll back real work."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid body"}), 400
    try:
        return jsonify(store.restore_book(data, owner=_owner())), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/books/<book_id>", methods=["PUT", "POST"])  # POST = sendBeacon fallback
def api_save_book(book_id: str):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid body"}), 400
    try:
        return jsonify(store.save_book(book_id, data, owner=_owner()))
    except KeyError:
        return jsonify({"error": "not found"}), 404


@app.delete("/api/books/<book_id>")
def api_delete_book(book_id: str):
    return jsonify({"deleted": store.delete_book(book_id, owner=_owner())})


@app.get("/api/books/<book_id>/versions")
def api_book_versions(book_id: str):
    if store.get_book(book_id, owner=_owner()) is None:
        return jsonify({"error": "not found"}), 404
    try:
        return jsonify(store.list_versions(book_id))
    except ValueError:
        return jsonify({"error": "bad id"}), 400


@app.post("/api/books/<book_id>/restore")
def api_restore_version(book_id: str):
    data = request.get_json(silent=True) or {}
    if store.get_book(book_id, owner=_owner()) is None:
        return jsonify({"error": "not found"}), 404
    try:
        return jsonify(store.restore_version(book_id, data.get("file", "")))
    except (KeyError, ValueError):
        return jsonify({"error": "version not found"}), 404


# --------------------------------------------------------------------------- #
#  Images                                                                      #
# --------------------------------------------------------------------------- #

@app.get("/api/image-search")
def api_image_search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"results": [], "pexelsConfigured": bool(config.get_pexels_key())})
    try:
        limit = int(request.args.get("limit", 12))
    except ValueError:
        limit = 12
    limit = min(max(limit, 1), 24)
    source = request.args.get("source") or "auto"
    if source not in ("auto", "wikimedia", "pexels"):
        source = "auto"
    return jsonify(images.search_images(query, limit=limit, source=source))


@app.post("/api/books/<book_id>/images")
def api_upload_image(book_id: str):
    if store.get_book(book_id, owner=_owner()) is None:
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


def _parse_lite() -> bool:
    """The Export dialog's "Lite" toggle — shrinks/recompresses images and
    diagrams for a smaller PDF/EPUB. Absent/off means the unchanged default
    export."""
    return request.args.get("lite", "") in ("1", "true", "on")


def _parse_numbered() -> bool:
    """The Pages export's "Number headings" toggle — prefixes every note's
    title/filename with its outline position (hyphen-separated, e.g. "1-2",
    since a "." in a filename is asking for trouble) so a static host that
    loses the outline's own ordering still sorts notes correctly."""
    return request.args.get("number", "") in ("1", "true", "on")


def _parse_diagrams_as_images() -> bool:
    """The Pages export's "Diagrams as images" toggle — rasterizes Mermaid
    diagrams (same technique as the EPUB export) instead of leaving them as
    live ```mermaid``` fences, for hosts whose renderer doesn't handle a live
    diagram well (e.g. some Obsidian HTML-export plugins overflow them)."""
    return request.args.get("diagrams", "") in ("1", "true", "on")


def _parse_page_numbers() -> bool:
    """The PDF export's "Page numbers" toggle — a footer number on every
    content page, plus each entry in the contents page listing the page it
    starts on."""
    return request.args.get("pagenumbers", "") in ("1", "true", "on")


@app.get("/api/books/<book_id>/export.json")
def export_json(book_id: str):
    """The portable copy of a book: a .zip holding the book's own JSON plus an
    ``Images/`` folder with every picture it references. Plain JSON alone lost
    them — uploads live in ``books/assets/<id>/`` and remote ones at their
    original URLs — so re-importing on another machine (or after a redeploy
    wiped the disk) came back with broken images."""
    book = store.get_book(book_id, owner=_owner())
    if book is None:
        return jsonify({"error": "not found"}), 404
    raw, _root = book_to_bundle(book, base_url=request.url_root,
                                exclude_ids=_parse_exclude(), lite=_parse_lite())
    return Response(raw, mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.zip"',
    })


@app.get("/api/books/<book_id>/export.md")
def export_md(book_id: str):
    book = store.get_book(book_id, owner=_owner())
    if book is None:
        return jsonify({"error": "not found"}), 404
    md = export.book_to_markdown(book, base_url=request.url_root, exclude_ids=_parse_exclude())
    return Response(md, mimetype="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.md"',
    })


@app.get("/api/books/<book_id>/export.pdf")
def export_pdf(book_id: str):
    book = store.get_book(book_id, owner=_owner())
    if book is None:
        return jsonify({"error": "not found"}), 404
    if not export.pdf_available():
        return jsonify({"error": export.pdf_error()}), 501
    palette = request.args.get("palette") or (book.get("settings") or {}).get("palette")
    try:
        pdf = export.book_to_pdf(book, palette, base_url=request.url_root, exclude_ids=_parse_exclude(),
                                 lite=_parse_lite(), page_numbers=_parse_page_numbers(),
                                 token=_preview_token(book_id))
    except subprocess.TimeoutExpired:
        return jsonify({
            "error": "PDF export timed out (tried twice) — this book may be too large or "
                     "image/diagram-heavy for one export pass. Try excluding some content "
                     "via Export → Content to include, or exporting chapters separately.",
        }), 504
    except Exception as exc:
        return jsonify({"error": f"PDF export failed: {exc}"}), 500
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.pdf"',
    })


@app.get("/api/books/<book_id>/export.epub")
def export_epub(book_id: str):
    book = store.get_book(book_id, owner=_owner())
    if book is None:
        return jsonify({"error": "not found"}), 404
    palette = request.args.get("palette") or (book.get("settings") or {}).get("palette")
    try:
        data = epub.book_to_epub(book, palette, base_url=request.url_root, exclude_ids=_parse_exclude(),
                                 lite=_parse_lite())
    except subprocess.TimeoutExpired:
        return jsonify({
            "error": "EPUB export timed out (tried twice) — this book may be too large or "
                     "diagram-heavy for one export pass. Try excluding some content via "
                     "Export → Content to include, or exporting chapters separately.",
        }), 504
    except Exception as exc:
        return jsonify({"error": f"EPUB export failed: {exc}"}), 500
    return Response(data, mimetype="application/epub+zip", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}.epub"',
    })


@app.get("/api/books/<book_id>/export.pages")
def export_pages(book_id: str):
    book = store.get_book(book_id, owner=_owner())
    if book is None:
        return jsonify({"error": "not found"}), 404
    try:
        data = pages.book_to_pages(book, base_url=request.url_root, exclude_ids=_parse_exclude(),
                                   lite=_parse_lite(), numbered=_parse_numbered(),
                                   diagrams_as_images=_parse_diagrams_as_images())
    except subprocess.TimeoutExpired:
        return jsonify({
            "error": "Pages export timed out — this book may be too large or image-heavy for "
                     "one export pass. Try excluding some content via Export → Content to "
                     "include, or exporting chapters separately.",
        }), 504
    except Exception as exc:
        return jsonify({"error": f"Pages export failed: {exc}"}), 500
    return Response(data, mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{_slug(book.get("title"))}-pages.zip"',
    })


@app.get("/api/books/<book_id>/preview")
def export_preview(book_id: str):
    # Chrome (during PDF export) sends no cookies, so it uses the signed token
    # the exporter put in the URL instead. A signed-in browser just owns the
    # book, and ``owner=None`` disables the check for that token-verified case.
    by_token = _preview_authorised(book_id)
    book = store.get_book(book_id, owner=None if by_token else _owner())
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

    budget = config.get_context_char_budget()
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


def _book_outline(book: dict, *, mark_id: str | None = None,
                  context_ids: set | None = None) -> str:
    """A titles-only outline of the WHOLE book (headings/subheadings, no body
    text), with the node currently being generated and any picked-context
    nodes flagged in place — so the model can see the book's overall shape
    and where its assigned subsection sits within it (what chapter, what
    precedes/follows it) without the weight of full section text.

    Sections don't carry their own titles (they hold the body text of their
    parent heading/subheading), so they're skipped here entirely; a section
    id in ``mark_id``/``context_ids`` should already have been resolved to
    its titled parent by the caller.
    """
    context_ids = context_ids or set()
    lines: list[str] = []

    def rec(nodes: list[dict], depth: int) -> None:
        for n in nodes:
            if n.get("type") == "section":
                continue
            title = (n.get("title") or "").strip()
            if title:
                tag = (
                    "  <-- you are writing this now" if n.get("id") == mark_id else
                    "  (picked as extra context)" if n.get("id") in context_ids else
                    ""
                )
                lines.append("  " * depth + "- " + title + tag)
            rec(n.get("children") or [], depth + 1)

    rec(book.get("nodes") or [], 0)
    return "\n".join(lines)


def _titled_id(book: dict, node_id: str | None) -> str | None:
    """A node's own id, or its nearest titled ancestor's id if it's a section
    (sections show up in the outline as their parent's line, not their own)."""
    if not node_id:
        return None
    node, parent = store.find_node(book.get("nodes") or [], node_id)
    if node is None:
        return None
    if node.get("type") == "section":
        return parent.get("id") if parent else None
    return node_id


# How many times a response cut off by the provider's output limit is
# continued automatically before the cut is reported to the user. Two is
# enough to finish any realistic section (the cut happens around a few
# thousand visible tokens), and each round re-sends the text written so far,
# so a larger number only adds cost — it does not buy much extra length.
MAX_CONTINUATIONS = 2


# A response only counts as finished when it ends on something sentence-shaped:
# terminal punctuation, a closing bracket/quote/emphasis marker, a table row, or
# a closed code fence. Used together with "the provider sent no finish_reason at
# all" to decide whether a stream died early (see _stream_chat_response).
_TERMINAL_TAIL = re.compile(r"(?:[.!?\u2026:)\]}`|*])\s*$")


def _looks_unfinished(text: str) -> bool:
    """Whether the text visibly stops mid-thought.

    Only consulted when the provider sent no terminal chunk, so a normal reply
    (which always ends with a finish_reason) is never second-guessed. An
    unterminated ``` fence is conclusive on its own; otherwise the tail just
    has to end on punctuation rather than a bare word."""
    tail = (text or "").rstrip()
    if not tail:
        return False
    if tail.count("```") % 2:
        return True
    return not _TERMINAL_TAIL.search(tail)


def _trim_continuation_overlap(base: str, addition: str) -> str:
    """Drop the start of a continuation round that repeats the text it resumed from.

    Models usually carry straight on, but one that restarts at the beginning of
    the sentence it broke inside ("…If the vict" -> "If the victim is chosen…")
    repeats words that are already in the section. So instead of comparing raw
    prefixes, ask whether the start of the new text already appears in the tail
    of the old text: if it does, everything up to the end of that occurrence is
    a repeat and gets dropped.

    Only an overlap of 10+ characters counts, so a continuation that merely
    opens with a common word ("The …", "This …") is never eaten."""
    if not base or not addition:
        return addition
    tail = base[-500:]
    for k in range(min(len(addition), 400), 9, -1):
        if tail.rfind(addition[:k]) >= 0:
            return addition[k:]
    return addition


# How many extra rounds a finished-but-too-short section may get before the
# result is accepted as-is. One is enough: the extension asks for the missing
# depth in a single, coherent addition, and more rounds would risk turning a
# 1,500-word section into a 4,000-word one. See _LENGTH_MIN_WORDS for why this
# exists at all.
MAX_LENGTH_EXTENSIONS = 1

# Minimum prose words per Length setting. The prompt already gives the model a
# target range, but a small model can ignore it outright — gemini-3.5-flash-lite
# produced 618 prose words for a setting that asked for 1,400-2,000, while
# DeepSeek wrote 1,702 for the same prompt. Rather than hoping a prompt wording
# wins, the floor is enforced here: a finished section below it is extended
# once before it is saved. High is set near what DeepSeek actually writes with
# the same prompt (~2,000+ prose words), so both providers land in the same
# range; Low is deliberately 0 — brevity needs no guard.
_LENGTH_MIN_WORDS = {"Low": 0, "Medium": 500, "High": 1700}


def _prose_word_count(text: str) -> int:
    """Words of actual prose: code fences and Markdown table rows don't count,
    since neither is what the Length setting is really about."""
    body = re.sub(r"```.*?```", "", text or "", flags=re.DOTALL)
    body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("|"))
    return len(re.findall(r"[A-Za-z']+", body))


# The closing recap blocks are additional to the Length setting, not part of it:
# "600-900 words" means 600-900 words of substance plus a short Summary and
# Terminology list on top. Only *trailing* recap headings count as that tail — a
# sub-heading that merely starts with "Summary" mid-argument doesn't, and a body
# that is nothing but a recap is left untouched rather than measuring zero.
_HEADING_LINE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*(.*)$", re.MULTILINE)
_RECAP_TITLE = re.compile(
    r"^[^A-Za-z0-9]*(?:summary|key takeaways|in summary|terminology|glossary|key terms)\b",
    re.IGNORECASE,
)


def _body_word_count(text: str) -> int:
    """Prose words in the *body* — the trailing Summary and Terminology
    sections are excluded.

    The Length setting describes how much substance to write; the recap and the
    glossary at the end sit on top of that rather than counting towards it."""
    body = text or ""
    cut = None
    for m in reversed(list(_HEADING_LINE.finditer(body))):
        if not _RECAP_TITLE.match(m.group(1).strip()):
            break
        cut = m.start()
    if cut is not None and cut > 0:
        body = body[:cut]
    return _prose_word_count(body)


def _stream_chat_response(messages: list[dict], start_payload: dict,
                          *, resolve_images_book_id: str | None = None,
                          resolve_images_source: str = "auto",
                          min_words: int = 0) -> Response:
    """Shared SSE wrapper for /api/ai/generate and /api/ai/spark.

    When ``resolve_images_book_id`` is set (content mode with the "Use
    images" toggle on), any ```image-search request blocks in the raw model
    output are resolved — searched, judged, downloaded, saved — after the
    text stream finishes, and the corrected full text is sent as one extra
    "revise" event before "done". The client replaces its accumulated buffer
    with that text rather than trying to patch deltas in place, since the
    resolution can both remove placeholders entirely (nothing found) and
    change their length (a placeholder block vs. the inserted Markdown)."""
    profile = config.llm_status()

    # The response body is produced *after* this view returns, by which point
    # Flask has torn the request down — including the per-request key bundle
    # that ``before_request`` resolved. Without re-applying it here, every
    # streamed generation silently fell back to the machine's own keys (or
    # none): a bundle user saw "400 Please pass a valid API key" even though
    # Settings correctly showed their bundle and provider. Capture the ids
    # while the request is still alive and restore them for the whole stream.
    bundle_id = session.get("bundle")
    provider_pref = session.get("provider")
    models_pref = session.get("models")

    def _generate_body():
        yield _sse("start", {**start_payload, "provider": profile["provider"],
                             "label": profile["label"], "model": profile["model"]})
        text = ""
        meta: dict = {}
        continuations = 0
        extensions = 0
        round_messages = messages
        try:
            while True:
                meta.clear()
                before_round = len(text)
                round_parts: list[str] = []
                for piece in llm.stream_chat(round_messages, meta=meta):
                    round_parts.append(piece)
                    yield _sse("delta", {"text": piece})
                text += "".join(round_parts)
                if before_round:
                    # A continuation round just ended — remove anything it
                    # repeated from the tail it was shown (see the helper).
                    # Deltas have already reached the client, so the corrected
                    # text is sent as "revise", which replaces the client's
                    # accumulated buffer wholesale.
                    kept = _trim_continuation_overlap(text[:before_round], text[before_round:])
                    if kept != text[before_round:]:
                        text = text[:before_round] + kept
                        yield _sse("revise", {"text": text})
                if not meta.get("truncated") and not (
                        meta.get("incomplete") and _looks_unfinished(text)
                        and start_payload.get("mode") in ("content", "spark")):
                    # The reply finished on its own. If the Length setting asked
                    # for more than it produced, ask for the missing depth now —
                    # once — instead of saving a section that is half the length
                    # the user selected.
                    written = _body_word_count(text)
                    if (min_words and extensions < MAX_LENGTH_EXTENSIONS
                            and written < min_words):
                        extensions += 1
                        print(f"[app] {start_payload.get('mode')} finished at "
                              f"{written} prose words, under the {min_words}-word "
                              f"floor — asking the model to extend",
                              file=sys.stderr, flush=True)
                        yield _sse("status", {"message":
                            f"{written} words so far — extending to the requested "
                            "length…"})
                        round_messages = messages + [
                            {"role": "assistant", "content": text},
                            {"role": "user", "content": prompt_store.get(
                                "shared.length_extension", written=written,
                                target=min_words)},
                        ]
                        continue
                    break
                # "length" / "MAX_TOKENS" means the provider stopped mid-word
                # because its output budget ran out. No finish_reason at all
                # means the connection just ended — Gemini does both, and neither
                # one is visible to the user. Rather than save a half-written
                # section, ask the model to carry on from exactly where it
                # stopped and stitch the pieces together.
                if continuations >= MAX_CONTINUATIONS:
                    break
                continuations += 1
                print(f"[app] {start_payload.get('mode')} response stopped early "
                      f"(finish_reason={meta.get('finish_reason')!r}, "
                      f"truncated={bool(meta.get('truncated'))}) after "
                      f"{len(text)} chars — asking the model to continue "
                      f"({continuations}/{MAX_CONTINUATIONS})",
                      file=sys.stderr, flush=True)
                yield _sse("status", {"message":
                    ("The model hit its output limit" if meta.get("truncated")
                     else "The reply stopped early")
                    + " — continuing where it stopped "
                    f"({continuations}/{MAX_CONTINUATIONS})…"})
                round_messages = messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": prompts.continuation_prompt()},
                ]
            still_cut = bool(meta.get("truncated") or meta.get("incomplete"))
            if still_cut:
                # Still cut after every continuation — say so honestly rather
                # than letting the end of the section look deliberate.
                yield _sse("status", {"message":
                    "The response ended before it finished — this may be cut short."})
            if resolve_images_book_id:
                original = text
                full = original
                # The model is instructed to request images only via a
                # ```image-search block and to NEVER hand-write a Markdown
                # image tag itself — but it can still imitate a real
                # ![...](/assets/...) it saw in its own context (another
                # already-generated section pulled in as extra/whole-book
                # context), hallucinating a fake path of its own. Strip any
                # such raw tag before resolving the real ```image-search
                # blocks, so a hallucinated dead link can never reach saved
                # content even when it's the only image markup present (no
                # ```image-search block to trigger the check below).
                full, dropped_raw = images.strip_raw_image_tags(full)
                if dropped_raw:
                    print(f"[app] dropped {dropped_raw} hand-written image tag(s) "
                          "the model wrote instead of an image-search block",
                          file=sys.stderr, flush=True)
                revised = full
                if images._PLACEHOLDER_RE.search(full):
                    yield _sse("status", {"message": "Finding images…"})
                    try:
                        revised, resolved, total = images.resolve_image_placeholders(
                            full, resolve_images_book_id, source=resolve_images_source)
                    except Exception as exc:
                        import traceback
                        print(f"[app] resolve_image_placeholders crashed: {exc!r}", file=sys.stderr, flush=True)
                        traceback.print_exc(file=sys.stderr)
                        revised, resolved, total = full, 0, 0
                    print(f"[app] image resolution: {resolved} of {total} placeholder(s) resolved",
                          file=sys.stderr, flush=True)
                    if total:
                        yield _sse("status", {"message": f"Found {resolved} of {total} image(s)."})
                if revised != original:
                    yield _sse("revise", {"text": revised})
            # The client uses this to decide whether "Content updated ✓" is the
            # honest message — a cut-short result must not be reported as a
            # clean success.
            yield _sse("done", {"truncated": still_cut,
                                "continuations": continuations})
        except requests.HTTPError as exc:
            yield _sse("error", {"message": str(exc)})
        except requests.RequestException as exc:
            yield _sse("error", {"message": f"network error: {exc}"})
        except RuntimeError as exc:  # missing API key etc.
            yield _sse("error", {"message": str(exc)})

    @stream_with_context
    def generate():
        config.set_active_bundle(bundle_id)
        config.set_request_provider(provider_pref)
        config.set_request_models(models_pref)
        try:
            yield from _generate_body()
        finally:
            config.clear_active_bundle()

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
    use_images = bool(body.get("useImages"))
    use_wikimedia = bool(body.get("useWikimedia", True))
    use_pexels = bool(body.get("usePexels", True))
    image_frequency = body.get("imageFrequency") or "Medium"
    diagram_frequency = body.get("diagramFrequency") or "Medium"
    length = body.get("length") or "Medium"
    summary_section = bool(body.get("summarySection", True))
    terminology_section = bool(body.get("terminologySection"))

    if mode not in prompts.MODES:
        return jsonify({"error": f"mode must be one of {prompts.MODES}"}), 400
    if not user_prompt:
        return jsonify({"error": "prompt is required"}), 400

    book = store.get_book(book_id, owner=_owner()) if book_id else None
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

    # A titles-only map of the whole book, with the node being written and any
    # picked context flagged in place, so the model can see where its subsection
    # sits relative to the rest of the book (what chapter, what's around it) —
    # not just the direct ancestor breadcrumb already in the task prompt.
    mark_id = _titled_id(book, node.get("id")) if node is not None else None
    outline_context_ids = {i for i in (_titled_id(book, i) for i in context_ids) if i}
    book_outline = _book_outline(book, mark_id=mark_id, context_ids=outline_context_ids)

    messages = prompts.build_messages(
        mode, user_prompt, tone=tone, depth=depth, refine_source=refine_source,
        context_blocks=context_blocks, overarching=overarching, use_images=use_images,
        image_frequency=image_frequency, diagram_frequency=diagram_frequency, length=length,
        summary_section=summary_section, terminology_section=terminology_section,
        book_outline=book_outline,
    )
    # Which source(s) the "Use images" toggle is allowed to draw from — both
    # ticked keeps today's Wikimedia-first/Pexels-fallback behaviour; one
    # ticked restricts to just that source; neither means every placeholder
    # is dropped (images.search_images already treats "none" as zero results).
    image_source = (
        "auto" if use_wikimedia and use_pexels else
        "wikimedia" if use_wikimedia else
        "pexels" if use_pexels else
        "none"
    )
    return _stream_chat_response(messages, {
        "mode": mode, "refine": refine_source is not None, "context": len(context_blocks),
    }, resolve_images_book_id=(book_id if mode == "content" and use_images else None),
       resolve_images_source=image_source,
       # A refine is a revision of an existing draft, not a request for a longer
       # one — extending it would silently add new sections the user didn't ask
       # for when they only wanted the draft reworked.
       min_words=0 if refine_source is not None
       else _LENGTH_MIN_WORDS.get(length, 0) if mode == "content" else 0)


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

    book = store.get_book(book_id, owner=_owner()) if book_id else None
    if book is None:
        return jsonify({"error": "book not found"}), 404

    a_node, _ = store.find_node(book.get("nodes", []), a_id)
    b_node, _ = store.find_node(book.get("nodes", []), b_id)
    if a_node is None or b_node is None:
        return jsonify({"error": "pick two blocks from this book"}), 400

    half = max(2000, config.get_context_char_budget() // 2)
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
