# Change Log

Changes made to Rextbooks by Claude Code, most recent first. Entries below
2026-09-20 are reconstructed after the fact from conversation history and
file-modification timestamps (git commits during this period bundled many
changes into a couple of commits, so exact per-feature times aren't all
independently verifiable) — dates are accurate, times are best-effort.
From 2026-09-20 onward, entries are logged at the time each change is made.

---

## 2026-09-20

**13:45 SAST** — Added an optional **"Number headings" toggle** to the Pages
export (`pages.py`, `app.py`'s `_parse_numbered`, and the matching checkbox
in the Export dialog): prefixes every note's title *and* filename/foldername
with its outline position — "1", "1-1", "1-2", "2-1"... — using a hyphen
rather than the conventional dot, since a "." in a filename is a real risk
on some filesystems/tools. This exists because a static host (GitHub Pages
via an Obsidian export, specifically) generally loses the outline's actual
ordering and falls back to sorting notes alphabetically; a numeric prefix
makes that fallback sort land correctly instead of scrambled. Numbers are
zero-padded to whatever width each level actually needs (e.g. "01".."12"
for 12 siblings) — caught and fixed this myself before shipping, since a
bare "1".."12" sorts "10" before "2" alphabetically, which would have
silently reintroduced the exact ordering bug the feature exists to fix.
Verified against both a small book (stays unpadded: "1", "2") and a
12-chapter book (pads to "01".."12", confirmed alphabetical-sort order
matches outline order) on both the dev server and the portable build.

**13:20 SAST** — Added a **"Pages" export mode**: a new `pages.py` module
producing a `.zip` of Markdown notes mirroring the book's outline, shaped
for dropping straight into an Obsidian vault. Each container level (a
heading, or a subheading with its own nested subheadings) becomes a folder
with a same-named overview note; each leaf subheading becomes one note
holding its section's content. Notes link to each other via full-vault-path
Obsidian wikilinks (`[[Chapter 1/Some Subheading|Some Subheading]]`, not
bare titles) so two subheadings anywhere in the book can share a title
without colliding; images are copied into one shared `assets/` folder at
the book's root and referenced via `![[filename]]` embeds, matching
Obsidian's filename-based link resolution (confirmed against the user's own
vault/plugin setup) so no relative-path math is needed regardless of
nesting depth. Mermaid code fences pass through completely untouched —
Obsidian renders them natively, so unlike the EPUB path this needs no
headless-browser rasterization step at all. Reuses `epub._AssetBag` for
image fetching/dedup, `export.filter_book_nodes` for the existing "Content
to include" picker, and `compress.shrink_image_bytes` for the existing Lite
toggle (now offered for Pages too). Wired up as a new "Pages" button in the
Export dialog's format selector (`app.py`'s `_parse_lite`/`_parse_exclude`
threaded through a new `/api/books/<id>/export.pages` route;
`static/js/api.js`, `static/js/export-panel.js`, `templates/index.html`).
Verified: folder/file structure, wikilink correctness, image embed syntax,
mermaid passthrough, sibling title-collision handling, special-character
title sanitization, the exclude-content picker, and Lite-mode image
compression (text identical, only the image bytes differ) — via a test
book built specifically to exercise all of those at once, run against both
the main dev server and the portable build.

**12:23 SAST** — Added `CLAUDE.md` (architecture/workflow guide for future
Claude Code sessions in this repo) and this `Change_Log.md`, populated with
the history below. Later the same day, added a standing policy section to
`CLAUDE.md` instructing future sessions to keep this file updated
unprompted for every change (including reverted ones), for continuity
across context compaction.

---

## 2026-09-19 (afternoon/evening)

- **Lite export toggle for PDF/EPUB.** New `compress.py` module (pure
  Pillow, no external binaries): `shrink_image_bytes` resizes+re-encodes an
  already-fetched image in place for EPUB embedding, `compress_pdf_images`
  post-processes a finished PDF's already-embedded raster images via
  `pypdf`. Wired through `export.book_to_pdf(..., lite=...)` and
  `epub.book_to_epub(..., lite=...)`, a new `lite` query param in
  `app.py`'s export routes, and a "📦 Lite export" checkbox in the Export
  dialog (`templates/index.html`, `static/js/export-panel.js`,
  `static/js/api.js`). EPUB's Mermaid-diagram rasterization also drops from
  2x to 1.3x scale and PNG-optimizes when Lite is on. Verified ~62–68% size
  reduction on a mixed test book (photo + tall image + diagram) with page
  count, running headers, and the tall-image overflow fix all unaffected
  between default and Lite output.
- **Static-file caching fix.** `app.py`: `SEND_FILE_MAX_AGE_DEFAULT = 0`.
  Root cause of an earlier debugging dead-end — Flask's default static-file
  caching could let a browser keep serving a stale JS/CSS file across an
  *ordinary* reload for a long time after it changed on disk, previously
  requiring a hard refresh (or not helping at all if the browser's cache
  logic didn't revalidate). Discovered mid-investigation of the fullscreen
  editor toolbar bug below.
- **Fullscreen Markdown editor: header collapsing to a sliver in Preview
  view.** Root cause: `.b-edit-head` (the toolbar) had no explicit
  `flex-shrink`, so as a flex item next to a much-taller rendered preview
  pane in Preview mode, flexbox's proportional shrink distribution squeezed
  it down toward zero height. Fixed with `flex-shrink: 0` in
  `static/css/style.css` so the toolbar always holds its natural height;
  the preview pane (which already scrolls internally) absorbs the
  difference instead.
- **Fullscreen Markdown editor: toolbar rendering above the box, cut off.**
  Root cause: entering fullscreen reparents the editor to `<body>`, so
  `.b-edit-head`'s `position: sticky` (added for the sticky-toolbar feature
  below) resolved against the viewport instead of the fixed-position editor
  box, which sits 4vh down from the true page top. Fixed by disabling
  sticky specifically in fullscreen (`static/css/style.css`) — unneeded
  there anyway, since the flex-column layout already keeps the toolbar
  permanently visible.
- **Sticky Markdown toolbar + adjustable fullscreen split + view modes.**
  `static/js/block.js` / `static/css/style.css`: the editor's top bar and
  formatting toolbar now stay pinned while scrolling a long section, in
  both normal and fullscreen editing (`.b-edit-head`, `position: sticky`).
  In fullscreen, the existing drag handle between editor/preview now
  actually works (previously disabled there), resizing the split as a
  remembered percentage; a new **Split / Raw / Preview** segmented toggle
  lets the editor or the rendered preview take the full height instead.
- **Book-structure context for generation.** `app.py` (`_book_outline`,
  `_titled_id`) / `prompts.py`: every "content"/"subheadings" generation
  now includes a titles-only outline of the *entire* book, with the node
  being written and any manually-picked extra context flagged in place —
  so the model can see which chapter it's in and what's around it, not
  just the direct ancestor breadcrumb it already had.
- **Bulk-generate: select a parent to select all its children.**
  `static/js/store.js` (`isBulkContainer`, `toggleBulkChildren`) /
  `static/js/tree.js` / `static/js/block.js`: ticking a heading (or a
  subheading whose children are further subheadings) in the bulk-generate
  picker now ticks every one of its children in one click instead of
  requiring each to be ticked by hand — still constrained to one level, one
  kind. A subheading that already holds its own content still ticks
  itself, so bulk-*regenerating* several already-written sections keeps
  working. Added a matching indeterminate checkbox state.
- **Export bug: "Content to include" could silently export nothing.**
  `static/js/export-panel.js`: the exclude-list builder was including a
  partially-selected *ancestor's* id whenever only some of its descendants
  were checked; the backend prunes a listed id's entire subtree, so ticking
  just one deep subheading under an otherwise-unticked chapter produced a
  cover-page-and-empty-TOC PDF/EPUB with no content at all. Fixed by only
  excluding a node when its whole subtree has zero included descendants.

## 2026-09-17

- **PDF running headers.** `export.py` (`_major_heading_titles`,
  `_running_headers`, `_stamp_running_headers`): a post-processing pass —
  Chrome doesn't support CSS running headers in `--print-to-pdf` — that
  reads the generated PDF's own bookmark outline via `pypdf`, matches it
  against the book's real chapter/major-heading titles (filtering out the
  cover/TOC's incidental headings), and draws `"Chapter — Subheading"` into
  each page's existing top margin with `reportlab`. New dependencies:
  `pypdf`, `reportlab` (added to `requirements.txt`). While building this,
  found and fixed a real `pdfgen.py` bug: plain `--headless` (old headless
  mode) never populates a PDF's bookmark outline regardless of
  `--generate-pdf-document-outline` — switched the PDF-export Chrome
  invocation to `--headless=new`.
- **Image overflow across PDF pages, second attempt.** `export.py`:
  `break-inside: avoid` alone can't stop a page break inside an image
  that's taller than a full printable page — added `max-height: 200mm` to
  the print CSS's `img` rule so an image always shrinks to fit one page,
  making the break-avoidance hint actually effective. (A same-day earlier
  attempt had only added the `break-inside: avoid` figure-wrapping, which
  turned out to be necessary but not sufficient.)
- **PDF export timeout guardrails.** `config.py`
  (`PDF_RENDER_TIMEOUT`), `pdfgen.py` (`_run_with_retry` — one automatic
  retry with a fresh temp profile dir for every headless-Chrome subprocess
  call), `app.py` (`export_pdf`/`export_epub` now catch
  `subprocess.TimeoutExpired` specifically and return an actionable 504
  instead of a raw traceback).
- **Prevent DeepSeek reusing the same image twice in one book.**
  `images.py`: used image URLs are recorded per-book in a sidecar file
  (`books/<id>.usedimages.json`, kept separate from the book's own JSON so
  the browser's autosave can't clobber it mid-request) and filtered out of
  future search results. `store.py`: clean up the sidecar file on book
  delete.
- **TOC indentation fix** — nested subheadings weren't indenting under
  their parent in the exported table of contents.
- **Force a page break before every major heading** (level-1 and level-2
  headings) so a new chapter/major section always starts cleanly on a new
  PDF page.
- All of the above were also synced into `dist-portable/Rextbooks/` (the
  hand-maintained portable-build copy) and verified there separately.
