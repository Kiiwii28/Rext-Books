# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Rextbooks — a recursive AI textbook generator. Flask backend, vanilla-JS ES-module frontend (no build step), DeepSeek (OpenAI-compatible) for generation. A book is a tree: `heading` → `subheading` (nests any depth) → `section` (Markdown body). The user grows the tree node-by-node via streamed LLM calls, edits Notion-style, and exports to PDF/EPUB/Markdown/JSON. See `README.md` for the full feature list and export-format details — it's kept current and is the primary reference; this file adds the architecture and workflow context README doesn't cover.

## Policy: always keep Change_Log.md current

**Append an entry to `Change_Log.md` for every change you make in this repo — every fix, feature, or reverted/abandoned attempt — as you make it, not just at the end of a session.** Date-stamp each entry (and time, if known) and say what the change was and why. Log a reverted change too, rather than deleting evidence it happened — the point is continuity: if this conversation gets compacted or a future session picks up mid-task with no memory of what already happened, `Change_Log.md` is the record that fills the gap. Do this unprompted; it's a standing policy, not something to wait for the user to ask for again.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env        # put DEEPSEEK_API_KEY in it, or paste one into the app's own ⚙ Settings later
python app.py                # http://127.0.0.1:5000
```

**There is no automated test suite, linter, or build step.** No `package.json`, no `pytest`/lint config. All verification is manual, against a real running server. The established convention (used successfully throughout this project's history) for changing anything:

1. Run an isolated server on a scratch port, pointed at a throwaway books directory — **never** the real `./books` or port 5000/5001 that a real session might be using:
   ```bash
   BOOKS_DIR=/path/to/scratch/test-books python -c "
   import app
   app.app.run(host='127.0.0.1', port=5099, debug=False, use_reloader=False, threaded=True)
   "
   ```
2. Exercise it with small throwaway scripts (`requests` against the HTTP API to build a test book, `pypdf`/`zipfile` to inspect exported PDFs/EPUBs, or the Chrome DevTools Protocol over a websocket to drive the real frontend in headless Chrome for UI/CSS changes — no Playwright/Selenium installed, but `websocket-client` + raw CDP works and has been used for this). Read back PDF pages directly (the environment's file-reading tool renders PDF pages to images) to visually confirm layout, not just that a byte count changed.
3. Only after that, restart whatever's actually serving the user's own session (port 5000 for the dev server, or the `dist-portable/Rextbooks` copy if that's what's in use) so they pick up the change.

**Windows process gotcha:** `Get-Process python` does not match `pythonw.exe` — check both when hunting for a stray server process. Also watch for **two processes both showing LISTENING on the same port** (seen in practice: a user's own long-running `python app.py` terminal plus a separately-started one) — only one is likely actually serving; kill both and start exactly one clean process rather than assuming a restart replaced the right one.

## Architecture

### The tree and persistence

`node.type` is `"heading" | "subheading" | "section"`; subheadings nest arbitrarily deep, and a subheading holds at most one `section` child (its content) alongside any number of nested subheadings. The **frontend owns the tree** (`static/js/store.js`) and PUTs the entire book on every change (debounced); the backend (`store.py`) just does safe read/write of `books/<id>.json` plus bookkeeping — there's no per-node API. `BOOKS_DIR` env var overrides where books live (this is what test isolation above relies on). `store.py` also snapshots the previous version into `books/.trash/` before an overwrite that looks like data loss (fewer nodes, or a big content shrink), pruned to the last 8 — a safety net, not a full version history UI.

### Generation: mode comes from selection, not from the prompt text

`app.py`'s `/api/ai/generate` decides **outline** (nothing selected) vs **subheadings** (a heading/subheading selected) vs **content** (a subheading/section selected) from *what node is selected*, never from parsing the user's prompt — this is enforced in `app.py`, so an edited prompt can change tone/length/emphasis but can never make the app build the wrong node type. `prompts.py` builds each mode's system prompt as **RULES** (invariants the app depends on — parseable list output, section scope, no stray top-level headings — always enforced) plus **DEFAULTS** (house style: length, image/diagram counts, summary sections — the user's editable prompt text overrides these). Every content generation also gets a titles-only outline of the *entire* book (see `_book_outline` in `app.py`) with the current node and any picked "extra context" flagged in place, so the model knows where its assigned piece sits in the larger structure — separate from, and in addition to, whatever body text the user explicitly picked as context via `_collect_context`.

`sparks.py` is a parallel, structurally different generation path ("Spark"): cross-breeds exactly two existing nodes under one of ten fixed modes into a new sibling node, rather than extending the tree downward from one selection.

### Export pipeline — one shared HTML render, three consumers

`export.py`'s `book_to_html` (recursive over arbitrary tree depth, driven by the same palette system as the live preview) is the single source of truth for layout; `book_to_pdf` and `epub.py`'s `book_to_epub` both build on it rather than maintaining their own rendering:

- **PDF** renders that HTML through a real, installed headless Chrome/Edge/Chromium (`pdfgen.py`, `--print-to-pdf`) — not a Python PDF library — so the exported PDF is pixel-faithful to the live preview. Two things are stitched on afterward as separate post-processing passes over the finished PDF bytes (both independently best-effort — a failure in either must never break the export itself, only skip that enhancement):
  - **Running headers**: reads the PDF's own bookmark outline (only present when Chrome is launched with `--headless=new`, *not* the older bare `--headless` — this was a real bug, confirmed empirically that old-headless mode never populates the outline regardless of `--generate-pdf-document-outline`) via `pypdf`, matches titles against the book's real node structure to exclude the cover/TOC's incidental headings, then draws `"Chapter — Subheading"` into each page's existing top margin with `reportlab` and merges it in with `pypdf`.
  - **Lite-mode image compression** (`compress.py`): finds every raster image already embedded in the finished PDF and recompresses it in place with Pillow. Runs *after* the header stamping, deliberately, so the two post-processing steps can't interact.
  - A tall image can't just rely on `break-inside: avoid` to stay on one page — that only works if the element actually fits on *some* page, so images are also `max-height`-capped in the print CSS.
- **EPUB** (`epub.py`) is built by hand — no third-party ebook library — reusing the *rendered* HTML from a single headless-Chrome DOM-dump pass (loaded from a temp file, not the live `/preview` URL, or Chrome's request lands back on the same request-handler thread that's blocked waiting for it and stalls badly under the dev server) so Mermaid diagrams are already resolved to real SVG before EPUB-specific processing. Diagrams are then rasterized to PNG (batched — one screenshot per stack of diagrams, cropped apart with Pillow, not one Chrome launch per diagram) because Mermaid's live SVG output uses features (`foreignObject` labels, 8-digit alpha-hex) many e-reader engines render wrong. Lite mode drops the rasterization scale and PNG-optimizes; images embedded from remote URLs or local uploads are resized/recompressed the same way as the PDF path but via `compress.shrink_image_bytes` (a plain-bytes-in-bytes-out function, since EPUB embeds files directly rather than post-processing a container format).
- Both `book_to_pdf` and `book_to_epub` take `exclude_ids` (from the Export dialog's "Content to include" picker) and `lite` (the size-optimized export toggle) as parameters threaded down from `app.py`'s query-string parsing.

### The portable build is a second, manually-synced copy of the app

`dist-portable/Rextbooks/` is a full standalone copy (embeddable Python + pre-installed deps in `pylibs/` + copies of every backend `.py` file, `templates/`, `static/`) built for zero-install handoff via `launcher.py` (runs on port 5001, specifically different from the dev server's 5000). **This is not a build artifact generated from the main tree — it's a hand-maintained duplicate.** Any change to `app.py`, `export.py`, `epub.py`, `compress.py`, or anything under `static/`/`templates/` needs the same file copied into `dist-portable/Rextbooks/` afterward, and a new third-party dependency needs `pip install --target dist-portable/Rextbooks/pylibs <pkg>` from the *main* `.venv` (so the wheel matches the embedded interpreter's exact Python version/platform) in addition to `requirements.txt`. See `README.md`'s "Packaging a copy for someone else" section for the full rebuild recipe.

### Frontend state model

`static/js/store.js` is the single in-memory source of truth (the tree, selection, ephemeral "pick" state for context/Spark/bulk-generate) with a pub/sub `subscribe`/`emit`; `tree.js` does a full re-render of the outline on every store change (trees are small enough that this is simpler than diffing) and owns native drag-and-drop. Three mutually-aware "pick modes" share one `pickMode` field — **context** (tick blocks to feed as reference for the next generation, cascades to a ticked node's whole subtree), **Spark** (tick exactly two, standalone), and **bulk** (tick sibling blocks of one kind to generate each independently in sequence; ticking a container node is a shortcut for ticking all its children at once, *unless* that node already holds its own content, which stays individually pickable so bulk-regenerating already-written sections keeps working). No frontend build step — `<script type="module">` loads `main.js`, which imports the rest directly as browser-native ES modules; a change to any `static/js/*.js` file takes effect on a normal page reload, no compile step, but Flask's default static-file caching headers mean a *server* restart or the browser's own cache can occasionally serve a stale copy — the app explicitly sets `SEND_FILE_MAX_AGE_DEFAULT = 0` in `app.py` so an ordinary reload always revalidates.
