# Change Log

Changes made to Rextbooks by Claude Code, most recent first. Entries below
2026-09-20 are reconstructed after the fact from conversation history and
file-modification timestamps (git commits during this period bundled many
changes into a couple of commits, so exact per-feature times aren't all
independently verifiable) — dates are accurate, times are best-effort.
From 2026-09-20 onward, entries are logged at the time each change is made.

---

## 2026-09-29

**Actual root cause found — the three fixes below were chasing the wrong
layer entirely.** User sent the raw Markdown of a failing section, and it
showed the real answer immediately:
```
![The workforce: the only input that thinks back](/assets/placeholder)

test

![People are the only business input that can learn, choose, improve — or leave]
(/assets/0596599aeb074814b9a63ec7c0f59bae/6fb11a80c1b5415dace14ee9bc437dc7.jpg)
*Photo by Yan Krukau on Pexels*
```
The first image's `src` is the **literal string** `/assets/placeholder` —
not a race, not a timing bug, a genuinely, permanently dead link (confirmed
in the server log: repeated `GET /assets/placeholder` → 404, hammered
repeatedly by the session 3 retry logic, which correctly identified it as
broken every time because it *is* broken). The second image right next to
it is a real, correctly-resolved one. So in one single generation, the
model used the proper `\`\`\`image-search` mechanism for one image and, for
another, hand-wrote a raw Markdown image tag with a made-up path instead —
directly violating the explicit RULE in `prompts.py` that forbids this.

Root cause: `prompts.py`'s content-mode RULE already told the model "NEVER
write a Markdown image tag yourself... request one with a
\`\`\`image-search block instead" — but when "extra context" or "whole
book" context (added earlier this session) includes another
already-generated section, that context can contain a *real*, already-
resolved `![...](/assets/<hash>/<uuid>.jpg)` from the app's own past
resolution. The model sees that pattern in its own context and imitates it
for a new image it wants, producing a fake path since it has no real one —
confirmed as literally `/assets/placeholder`, a value that reads like a
lazy stand-in a model reaches for. This explains both "sometimes works,
sometimes doesn't" (only happens when context includes a prior resolved
image) and the user's own hunch that it traces back to whichever change
introduced heavier context ("Whole book" context, added in the same batch
as Pages export) — correct in spirit, even if Pages export itself wasn't
the mechanism.

Two-part fix:
- **Defense in depth (the real fix)**: new `images.strip_raw_image_tags()`
  — regex-strips any raw `![...](...)`  tag from the model's output.
  Wired into `app.py`'s `_stream_chat_response` to run *unconditionally*
  (whenever "Use images" is on) and *before* `resolve_image_placeholders`
  — at that point nothing has legitimately been resolved into a raw tag
  yet, so anything already in that shape is the hallucination. Runs even
  when no `\`\`\`image-search` block is present at all (the original bug:
  the hallucinated tag was the *only* image markup in that pass, so the old
  code's `if images._PLACEHOLDER_RE.search(full):` guard skipped resolution
  entirely and the raw dead link sailed straight through unprocessed).
  Emits a `revise` SSE event if stripping alone changed the text, same as a
  real resolution would. Logged server-side (`dropped N hand-written image
  tag(s)...`) whenever it fires.
- **Prompt reinforcement**: strengthened the RULE in `prompts.py` to name
  the exact failure mode — explicitly says a real `/assets/...` path seen in
  provided context is the app's own past resolution for a *different*
  section, not a template to imitate, and calls out `/assets/placeholder`
  as a specific example of what not to invent.

Verified: `images.strip_raw_image_tags` unit-tested against the user's
exact reported text (correctly identifies both raw tags when run on
already-resolved text — which is *why* it must only ever run pre-resolution,
never post-hoc); a staged test simulating raw model output with one
hallucinated tag + one legitimate `\`\`\`image-search` block confirmed the
fix drops only the hallucinated one and lets real resolution proceed
normally. 4 live end-to-end generations through the real `/api/ai/generate`
SSE endpoint, deliberately feeding an already-resolved image via context
(the exact trigger condition) — model didn't hallucinate in any of the 4
(expected; it's probabilistic), all four completed cleanly with no
regression. Synced `app.py`, `images.py`, `prompts.py` to
`dist-portable/Rextbooks/`. **This needed a full server restart** (unlike
the earlier JS-only fixes) — the old production process
(`python -c "import app; ..."` on port 5000, launched with the bare system
Python) was stopped and restarted with the project's venv Python (the
system Python lacks `requests` and failed to start — worth noting for next
time: the user's long-running production server apparently runs from an
environment with the dependencies available on `PYTHONPATH` some other way
than what a fresh `python -c "import app"` from the system interpreter
gets; the venv interpreter is the reliable way to relaunch it). Confirmed
the restarted server is serving the user's real `./books` directory (their
actual "Business Management" book, matching the asset hash from their
screenshot, is present via `/api/books`).

The client-side fixes below (retry-before-placeholder, event-listener-only
`watchImages`, deferred `store.setContent`) were not the actual cause of
this specific bug, but they're real, verified improvements in their own
right (a genuinely interrupted image load — from whatever cause — now
self-heals instead of permanently breaking) and are staying in place.

---

**Third follow-up — added self-healing retry; extensive stress-testing could
not reproduce the user's continued failure, so this makes the failure mode
recoverable regardless of its exact remaining cause.** User reported it
happening again after the previous fix, on an already-populated section,
and suspected it might relate to Mermaid diagram rendering (the one setting
they'd changed). Tested that combination specifically — 2 images + 1 diagram
together, in the same 55-block book, High frequency for both — 4 clean
runs. Then stress-tested harder: network throttled to ~200KB/s with 400ms
latency and browser cache disabled (forcing a real, slow Mermaid CDN
refetch) — 3 more clean runs. Then 3x repeated regeneration on an
already-populated section (matching "I even regenerated content") — 3 more
clean runs. 10/10 across every variation constructed, including the user's
specific diagram hypothesis; could not reproduce the failure to find a
further root cause. User confirmed testing in Chrome, ruling out a
browser-engine difference from the (also Chrome-based) headless testing.

Rather than keep guessing blindly, made the failure mode self-healing:
`watchImages()` in `block.js` now, on a genuine `error` event, probes the
exact same URL once more with a fresh `Image()` before permanently showing
the placeholder. Every resolved image this app produces is a same-origin
`/assets/` file already fully written to disk before its `<img>` tag ever
reaches the browser (confirmed repeatedly this session), so a load failure
is expected to be transient rather than a genuinely missing file — a retry
should succeed whatever the underlying cause (an interrupted request from
some other re-render path this session didn't specifically test, e.g.
`tree.js`'s `forceRender()` via the edit-lock/focusout mechanism, a one-off
network hiccup, etc.). If the retry succeeds, the `<img>` is reloaded with a
cache-busting query param (forcing an actual reload rather than a same-value
no-op `src` assignment) instead of showing a placeholder; a `console.warn`
either way makes a genuine remaining failure immediately diagnosable from
the browser console without digging through the Network tab. Verified
end-to-end against the *actual* `block.js` code (not a reimplementation): a
real image was resolved and saved to disk via `images.resolve_image_placeholders`,
embedded in a real book, and CDP's `Fetch` domain was used to deterministically
fail the *first* request for that exact URL (a genuine, forced network-level
failure — not a simulated detection bug) — the app recovered automatically:
`naturalWidth: 1280`, zero `.fig-placeholder` elements, and the expected
`[image] load failed once but a retry succeeded…` message in the console.
Synced to `dist-portable/Rextbooks/static/js/block.js`.

---

**Second follow-up — the `waitForBlockImages` fix (below) was still
incomplete; the actual root cause is now fixed.** User confirmed the hard
refresh fixed previously-broken images (expected — a plain, single render of
already-saved content never hits this race) but a *new* generation on a
real, sizeable book still produced one broken placeholder among two images.
Root-caused for real this time: `static/js/block.js`'s `watchImages()` used
a synchronous (well, one-frame-deferred, per the first attempt below)
`img.complete && img.naturalWidth === 0` check to catch "already known bad"
images fast, on top of the `error` event listener. Verified empirically via
a focused CDP test (`data:` URL images, since they load fast enough to
control precisely): recreating a fresh `<img>` with a `src` the browser has
already loaded once *can* resolve `complete`/`naturalWidth` **synchronously**,
immediately after insertion — contrary to the assumption behind the earlier
rAF-deferred version. That's exactly the shape of `renderTree`'s teardown+
rebuild: a fresh `<img>` for a just-loaded URL, checked essentially
immediately. If that synchronous resolution ever lands mid-way through a
re-decode (a genuinely separate browser-internal race, still not fully
pinned down at the browser-implementation level, but irrelevant to the fix),
it reports a false `naturalWidth: 0` and `replaceBrokenImg` permanently
swaps in the placeholder — no retry, ever.

The actual, complete fix: removed the proactive check entirely. Per the
HTML spec, setting an `<img>`'s `src` always queues its `load`/`error`
dispatch as a **later task**, never synchronously within the script turn
that set it — so an `error` listener attached immediately after insertion
(which `watchImages` already does) can never miss the real event, cached or
not. Confirmed this directly too: a garbage `data:` URL image reports
`complete: false` synchronously every time, and its `error` event still
fires reliably moments later. So the "catch it instantly" shortcut was
solving a problem that didn't exist, while causing the one that did.
`watchImages` now does nothing but attach the `error` listener — no
`complete`/`naturalWidth` check anywhere, synchronous or deferred.

Verified with a live CDP test against a **55-block, 25-subheading seeded
book** (closer to real-book scale than the earlier small test books) — real
generation, 2 images, High image frequency, through the actual AI dock UI —
run 4 times, zero broken placeholders every time. Synced to
`dist-portable/Rextbooks/static/js/block.js`.

---

**Follow-up — the first fix (`waitForBlockImages`) below was incomplete.** User hard-refreshed,
regenerated, and still saw a broken placeholder (one of two images in the
same section; the other rendered fine) — same signature as before (caption
is alt text, not a "Photo by X" attribution, confirming it's the client-side
placeholder swap, not a genuinely unresolved image). The first fix only
addressed `ai-dock.js`'s own redundant `onRevise`+`onDone` double-render; it
did nothing about the *real* remaining destroyer: `store.setContent()`
(called from `onDone`) always triggers `store`'s `emit()`, which `main.js`'s
`store.subscribe` callback turns into `tree.js`'s `renderTree()` — and
`renderTree` does an unconditional `container.innerHTML = ""` + full rebuild
on *every* store change (this is documented, intentional architecture, see
CLAUDE.md — "full re-render on every store change... simpler than
diffing"). So immediately after `onRevise` renders the resolved image and
its `<img>` starts loading, `onDone`'s `store.setContent()` tears down and
recreates that exact block (and its `<img>`) again via `renderTree`,
regardless of the first fix — confirmed with a `MutationObserver`-
instrumented live CDP test showing a destroy+recreate pair a few ms after
the image's first insertion.

Rather than touching `tree.js`'s render strategy (deliberately simple,
touching it risks the rest of the app), added a scoped wait in `ai-dock.js`:
a new `waitForBlockImages(sectionId, timeoutMs = 4000)` finds that section's
current `<img>` elements and returns a promise that resolves once every one
has fired `load` or `error` (or the 4s cap elapses, so one hung request
can't stall saving indefinitely). Both `onDone` handlers (`run()` and the
bulk-generate `streamOnce()`) now `await` it *before* calling
`store.setContent()`. This doesn't prevent `renderTree`'s teardown — it just
guarantees the teardown always happens *after* the browser has already
resolved that URL, so the recreated `<img>` is a fast, correct cache hit
instead of a fresh in-flight request getting interrupted. Verified with 5
consecutive live CDP runs through the real AI dock UI (1–2 images each,
High image frequency) — all landed at `complete: true` with a real
`naturalWidth` and zero `.fig-placeholder` elements. Synced to
`dist-portable/Rextbooks/static/js/ai-dock.js`.

---

**Fixed: images showing as broken placeholders right after content
generation.** User reported (with a screenshot) that a resolved image —
valid src, valid caption — rendered as a broken-image placeholder box
immediately after generation, "for all images." Extensive backend testing
(image search/resolve/save/serve, `rendering.render_markdown` on the exact
resolved markdown, a full real SSE `/api/ai/generate` run, the live
`/render` HTTP endpoint) all produced correct output — ruled out anything
server-side. Root cause was client-side, in `static/js/block.js`'s
`watchImages()`: after a fresh `<img>` element is inserted, it synchronously
checks `img.complete && img.naturalWidth === 0` to catch already-known-bad
cached images, and swaps in a permanent placeholder (`replaceBrokenImg`) if
so — a one-way swap with no retry. Two things could make that synchronous
check false-positive on a perfectly good, still-loading image:

1. `static/js/ai-dock.js`'s `onRevise` and `onDone` handlers both called
   `renderSection(sectionId, full)` with (in the image-resolution case)
   identical text moments apart — destroying and recreating the `<img>`
   element a second time right as its first load was starting.
2. Independently, `main.js`'s `store.subscribe` callback calls
   `renderTree(state)` on *every* state change, so `store.setContent()`
   (called from `onDone`) triggers its own additional re-render/recreation
   of the block regardless of (1).

Confirmed via a `MutationObserver`-instrumented live CDP test (real
generation through the actual AI dock UI, `BOOKS_DIR` pointed at an isolated
test dir) that the image `<img>` element was being destroyed and recreated
2–3 times within ~100ms of first insertion.

Fix (two parts, both low-risk):
- `ai-dock.js` (`run()` and `streamOnce()`): track `lastRendered`, the text
  `onRevise` last rendered; `onDone` now only calls `renderSection` again if
  `full !== lastRendered`, eliminating the redundant explicit re-render.
  This is safe even if `stripUnresolvedPlaceholders` changes `full` in
  `onDone` — the comparison still catches genuine differences and re-renders
  then.
- `block.js` (`watchImages`): the `error` listener is still attached
  synchronously (always reliable), but the "already complete and broken"
  check is now deferred one `requestAnimationFrame` tick (`img.isConnected`
  guarded), giving the browser a chance to settle a freshly-(re)inserted
  image's true load state before it's judged — closes the remaining race
  from the unavoidable `renderTree` re-render in (2) above without weakening
  real-failure detection at all (a genuinely dead image still gets caught,
  just one frame later).

Verified with a live CDP test driving the real AI-dock UI end-to-end
(select subheading → fill prompt → enable images → Generate → poll status →
inspect final DOM): image ends at `complete: true, naturalWidth: 1280`, zero
`.fig-placeholder` elements, and the mutation log shows the churn reduced
from 3 insertion cycles to 1 clean insertion + 1 harmless already-connected
recreate (down from what would have been up to 3 destroy/recreate cycles
pre-fix). Synced to `dist-portable/Rextbooks/static/js/{ai-dock,block}.js`.
Static-JS-only change — no server restart needed, just a browser reload
(`SEND_FILE_MAX_AGE_DEFAULT = 0` already forces revalidation).

---

## 2026-09-26

**08:06 SAST** — A large batch of features requested together:

- **"Whole book" context select** — `store.selectAllContext()` + a new
  "📖 Whole book" button next to "＋ Add context" adds every node in the
  book as context in one click (still excludes whatever's actually being
  generated, same as ticking manually would).
- **Pages export: "Diagrams as images"** toggle — rasterizes Mermaid
  diagrams (reusing `epub._rasterize_all_mermaid` as-is) instead of leaving
  them as live ```mermaid``` fences, for Obsidian HTML-export plugins whose
  live-diagram rendering overflows. Implemented via one whole-book headless-
  Chrome render pass (`pages._rasterize_book_mermaid`), then correlating the
  resulting rasterized images to each section's own fences *by position* —
  both traversals visit the same filtered node set in the same left-to-
  right, depth-first order, so the Nth diagram found rendering the book
  is always the Nth ```mermaid``` fence encountered walking the tree.
- **Settings: "Blurb"** — the "A textbook on {topic}." line under the title
  on export covers/TOC notes is now a configurable global template
  (`config.get_blurb_template`/`set_blurb_template`, defaulting to the
  original text) with a Reset button, replacing the hardcoded string in
  all five places it appeared (`export.py` ×2, `epub.py` ×2, `pages.py`).
- **Settings: "Textbook title"** — editable per-book title field, updates
  the book itself (`store.setBookTitle`) and the topbar book-picker's label
  immediately (`book-picker.updateCurrentTitle`), without a full book-list
  refetch.
- **PDF: "Page numbers"** toggle — a footer number on every page except the
  cover, and each contents-page entry gets its own page number backfilled
  at the right margin, aligned to that entry's own line. The hard part:
  finding *where* each contents-page entry actually sits — solved with
  pypdf's `extract_text(visitor_text=...)`, composing the text-drawing
  operation's `cm`/`tm` matrices (pypdf hands them back un-composed) to get
  real page-space coordinates, matched against the outline-derived "first
  page" for each chapter/major-heading title (same title set the running-
  header feature already classifies). While building this, found and fixed
  a real pre-existing bug: the running-header stamper's page-by-page
  `writer.add_page()` loop silently drops the PDF's own outline/bookmarks
  (confirmed empirically: 6 entries → 0) — every running-header export has
  been quietly destroying the PDF's navigation pane the whole time it's
  existed. Fixed by switching both stampers to `writer.append(reader)`,
  which preserves it (confirmed: 6 → 6), so bookmarks now survive
  regardless of which optional stamps are turned on, and the two features
  compose safely in either order.
- **Export dialog decluttered** — Author, Diagrams as images, Lite export,
  Number headings, and Page numbers moved into a collapsible "Advanced"
  disclosure (same pattern as the AI dock's own Advanced section), each
  still only shown when relevant to the selected format. The Author field
  doubles as a shortcut to the same global Settings value — editing it here
  saves back to Settings before the export downloads.

Verified: the page-numbers feature end-to-end with a real multi-chapter
book (screenshot-confirmed the contents page's numbers exactly match where
each chapter/major heading actually starts, footer numbers sequential,
outline intact in all three toggle combinations); the Pages
diagrams-as-images correlation directly; Settings title-rename updating
both the store and the book-picker label live; and every Advanced field's
per-format visibility in a real browser. Synced to the portable build and
restarted the production server.

**Deferred (discussion only, no code):** the user asked about eventually
letting DeepSeek write cross-chapter hyperlinks (Obsidian-style
`[[#heading]]`) and whether links could stay valid automatically if a
heading's title changes later — answered in conversation, not implemented.

---

## 2026-09-25 (continued)

**10:11 SAST** — Fixed two related image-placeholder bugs, both reported by
the user with screenshots of raw internal syntax leaking into rendered
content:

1. **Unresolved ` ```image-search ` request blocks shown raw to the
   reader.** These fenced blocks are an internal signal the model emits
   (only when "Use images" is on) for the server to resolve into a real
   photo after the stream finishes (`images.resolve_image_placeholders`);
   traced the resolution code path in full and found it structurally sound
   (every match is always replaced with either a real image or an empty
   string, never left raw) — so the likely cause is either a crash outside
   the per-placeholder guard, or the model echoing a stray unresolved block
   it saw in picked "extra context" from an earlier, differently-configured
   generation. Rather than chase one specific trigger, added a
   defense-in-depth fix that closes the gap regardless of cause: a new
   `rendering.strip_unresolved_image_placeholders` (mirroring
   `images._PLACEHOLDER_RE`) now runs inside `render_markdown` itself
   (covering the live preview, PDF, and EPUB — all three already routed
   through it), plus in `export.book_to_markdown` and `pages.py` (the two
   consumers that pass raw Markdown straight through without ever calling
   `render_markdown`). Also added the equivalent regex client-side in
   `ai-dock.js`, applied to the generated text right before
   `store.setContent` in both the single- and bulk-generation paths, so a
   stray placeholder can no longer even be *saved* into a book's content
   going forward, not just hidden at render/export time.
2. **A broken/placeholder image's caption left orphaned below it,
   disconnected.** Root cause: `rendering.py`'s `render_markdown` ran the
   "swap a broken image for a dashed-box placeholder" pass
   (`_IMG_TAG`/`_fix_image`) *before* the "wrap an image+caption paragraph
   into one `<figure>`" pass (`_IMG_ONLY_P`/`_wrap_image_figure`) — once an
   `<img>` tag was replaced with a `<figure class="fig-placeholder">`, the
   `<p><img>...<em>caption</em></p>` pattern the second pass looks for no
   longer matched (no `<img>` left inside the `<p>`), leaving the caption
   as a disconnected floating paragraph below the placeholder box instead
   of attached to it. Fixed by reordering the two passes — wrap first, fix
   second — so a broken image's placeholder now nests inside the same
   `<figure class="img-figure">` as its caption, exactly like a working
   image does.

Verified both via direct Python calls (`rendering.render_markdown`,
`export.book_to_markdown`, `pages.book_to_pages`), a Node-based test of the
client-side strip regex, the live `/render` endpoint through the restarted
production server, and a real-browser screenshot of the fixed
placeholder+caption grouping (visually matches the intended "grouped, not
orphaned" result) — plus a regression check confirming a normal working
image+caption pair still renders exactly as before. Synced to the portable
build and confirmed importable there too.

---

## 2026-09-25

**09:54 SAST** — Investigated a reported "stuck prompt" bug in the AI dock
(clearing the prompt box and asking for something different still produced
the same result) — audited `ai-dock.js`'s `promptDirty`/`refreshPrompt`
logic and `api.js`'s `streamGenerate` fetch call; found no caching/memoization
bug (every generation reads the prompt box live at click-time and POSTs a
fresh, never-cached request). Likely explanation reported back to the user:
the **Reset** button (tooltip: "Restore the default prompt") does exactly
that — restores the same deterministic auto-template for a given
target/mode, which is indistinguishable from "stuck" if interpreted as a
plain clear button; separately, output style can legitimately stay
consistent with sibling sections because of the book-outline-context
feature (2026-09-19) and picked Extra Context, both of which explicitly
instruct the model to stay stylistically consistent with the rest of the
book. No code change made for this part — reported findings instead of
guessing at a fix for a bug that didn't reproduce in the code.

Added three small AI-dock usability improvements (`ai-dock.js`, `main.js`,
`templates/index.html`, `style.css`):
- **"Clear all"** for the Extra Context chip row — previously only
  per-chip removal existed; now a link appears alongside the "N blocks ·
  ~Nk chars" hint (only when context is picked) that calls the
  already-existing `store.clearContext()`.
- **"Clear"** for the Bulk-generate queue — same idea, empties the queue
  (`store.clearBulk()`) without touching the book itself.
- **"🗑 Delete"** for the Bulk-generate queue — a new `deleteBulkSelection`
  in `ai-dock.js` that deletes every currently-queued block (and its
  subtree) from the book, confirming first with a singular/plural-aware
  message, distinct from "Clear" (which only empties the picker, never
  touches the tree). Reuses the existing `store.removeNode`, one call per
  queued id.

Verified all three via a real browser (CDP): picking 2 context blocks then
clicking "Clear all" empties the chip row and hides it; picking 2 bulk
blocks then "Clear" empties the queue while leaving both nodes in the tree;
picking 2 bulk blocks then "Delete" (confirm dialog intercepted and
accepted) removes both from the tree and empties the queue, while a
sibling not in the selection is left untouched; separately confirmed
declining the confirm dialog leaves both the node and the queue exactly as
they were.

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
