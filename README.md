# Rextbooks 📚

**Recursive Textbooks** — grow a textbook with an LLM, block by block.

Start from a topic. Generate an **outline** (headings). For any heading, generate
**subheadings**. For any subheading, generate its **section** content. Then
rearrange, edit, add, delete, and rewrite blocks by hand, Notion-style — and
export the finished book.

Generation runs against an **OpenAI-compatible** chat API, streamed
token-by-token. **DeepSeek** and **Google Gemini** are both built in — pick the
provider and model in **⚙ Settings**, no restart needed, and each provider keeps
its own key and model.

## Requirements

- Python 3.9+
- A DeepSeek **or** Google Gemini API key (or any other OpenAI-compatible
  endpoint, via the env overrides below)
- (optional) Pango/cairo for PDF export — see below

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then put your key in .env
```

`.env`:

```
# Which provider is active (a choice saved in ⚙ Settings wins over this).
LLM_PROVIDER=deepseek                  # or: gemini

DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-v4-flash        # cheapest; change if the API rejects it
DEEPSEEK_BASE_URL=https://api.deepseek.com

GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-3.8-flash           # Google retires old model names — Test key names the current one
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
```

`LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` are generic overrides for whichever
provider is active. Only the selected provider's key is ever needed.

`.env` is gitignored and read only on the server — the key never reaches the browser.

**Prompt text is data.** Every instruction the app sends lives in
`prompts.defaults.json` — the golden source of truth. Open **⚙ Settings →
Advanced — prompt text** to see all of it, edit any block (tone hints, depth
hints, length targets, diagram/image wording, Spark mode text, the image-search
judge…), and **Save prompts**; edits are written to `prompts.local.json` (also
gitignored) as sparse overrides and apply to the next generation. **Reset** on a
block deletes that override, so it reverts to whatever `prompts.defaults.json`
says *now* — including any later prompt fixes — and **Reset all** clears every
override. The panel's *Preview* builds the exact system/user messages for a
chosen mode, tone, depth and length, so you can see what the model will actually
be told. Blocks marked ⚠ are parsed by the app (numbered-list output, Mermaid
fences, `image-search` blocks, the Spark title line, the image judge's one-word
verdict) — editing those can silently break that feature. The golden file is
read at startup, so editing it by hand needs a server restart; overrides do not.


**Or skip `.env` entirely** and configure everything from inside the running
app: **⚙ Settings** in the topbar → pick a **provider**, its **model**, paste
the matching key → **Save**. The model field is a dropdown of known names for
that provider (Gemini currently offers `gemini-3.8-flash`, `gemini-3.6-flash`,
`gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`) and also accepts any other
name the provider recognises, so switching between models to compare speed or
quality is just a pick + Save. Pasting a key and pressing **Enter** (or hitting
**Test key**) saves it immediately — the Save button is only needed for the
other fields. Keys are written to `local_settings.json` next to
the app (also gitignored, also never sent back to the browser) and override
`.env` if both are present — so a packaged build can be handed to someone else
with their own key, without them touching a file. Each provider has its own
key and model, so switching is instant and lossless. If neither is set, the app
opens Settings automatically on first launch.

## Run

```bash
python app.py
```

Open <http://127.0.0.1:5000>.

## Features

- **Tutorial (🎓)** — a guided, spotlighted tour of the whole app: topbar,
  panels, the block toolbar, Spark/Bulk/context, the prompt box, section
  editing. **Next**/**Back** step through it, **Skip** (or `Esc`) ends it
  anywhere, and the button always restarts from the top. It only shows steps
  for things that actually exist right now — with no book open you get the
  topbar/AI-panel tour; open a book with some content and the block-level
  steps join in too.
- **Recursive generation** — outline → subheadings → section content, each step a
  streamed LLM call scoped to the selected block.
- **Notion-style blocks** — drag to reorder, collapse, add, delete, rename inline.
- **Resizable panels** — drag the divider between the Outline and AI Assistant
  panels to resize; double-click it to reset. Remembered across reloads.
- **Recurse (`↳`)** — add a nested sub-topic under any heading/subheading, so trees
  go arbitrarily deep. On a subheading with sub-topics the dock offers a
  **Sub-topics / Content** toggle.
- **Edit section text** — click ✎ on a section for an in-place Markdown editor with
  live preview (`Ctrl/Cmd+Enter` = Done, first `Esc` = cancel). Drag the handle below
  the textarea to resize it (sticks — typing won't snap it back, and the size is
  remembered next time); **⛶** expands the whole editor to fill the screen for
  longer edits (`Esc` exits fullscreen first, a second `Esc` cancels).
- **Reprompt a section** — ↻ on a section, or just select it. When a section already
  has text the dock shows **Replace** (fresh) / **Refine** (revise the current draft).
- **Prompt tags** — pick a **tone** (Technical / Academic / Blog / Conversational /
  Informative / Casual) and **depth** (Beginner / Intermediate / Advanced) in the
  dock; they're added to every generation and saved per book.
- **Extra context** — **＋ Add context** in the dock, then click other blocks in the
  outline to feed them to the LLM as reference for the current generation. Ticking a
  heading/subheading auto-ticks its whole subtree; untick any child you don't want.
  The chip row collapses to the top nodes (`Roots +N`). Budget is ~400k chars
  (`REXTBOOKS_CONTEXT_CHARS` overrides it; otherwise sized per provider) — DeepSeek
  v4 and Gemini 2.5 both take ~1M input tokens, so half a textbook of context is
  fine. Per-generation; clears when you pick another block.
- **Bulk generate (`⧉`)** — **⧉ Bulk** in the dock, tick two or more *sibling* blocks
  (same parent, same kind), then **Generate**. Each block is generated by its own
  separate, sequential request — so the model writes each at full length instead of
  splitting one answer — sharing the tone, depth, extra context and an optional
  shared instruction. Its per-block prompt names the full chain of parents above it.
  **⧉ Bulk** and **＋ Add context** work together: switch freely between the two
  pickers (the queued blocks stay listed under **Bulk queue**, removable there),
  and you can tick the very blocks being bulk-generated as context for one
  another — e.g. queue A, B, C and also tick A–D as context, and each of A, B, C
  is generated seeing the *other* three (itself is always excluded automatically).
  Ticking a heading (or a subheading whose children are further subheadings,
  not content) is a shortcut for ticking every one of its children at once —
  still just the one level below it, still all the same kind — instead of
  ticking each by hand. A subheading that already holds its own content still
  ticks itself, so bulk-regenerating several already-written sections works
  exactly as before.
- **Spark (`⚡`)** — cross-breed two blocks. Click **⚡ Spark**, pick exactly two
  blocks, then choose one of ten modes (Cross-Pollinate, Unified Theory, Contrarian,
  Socratic Questioning, Temporal Dimension, Scale Shifting, Metaphor Mapping, Missing
  Node Detection, What If?, Connections Map). Edit the default prompt and generate —
  a new synthesised subheading + section is inserted next to your current selection.
- **Diagrams** — content generation is told to add a **Mermaid** code block
  (```mermaid …```) where a flow / hierarchy / sequence helps. It renders to SVG in
  the app, the editor preview, and the PDF — centred in a translucent figure that
  picks up the book's palette. Needs a CDN (mermaid.js); offline it falls back to
  showing the diagram source. Diagrams are prompted to stay compact (≤~10 nodes,
  left-to-right for long chains) and are height-capped on render so a big diagram
  can't overflow a PDF page.
- **Images in sections** — in the editor, **🖼 Image** → paste, drop, upload a file,
  or add a link. Files are stored under `books/assets/<bookId>/`.
- **Books are private to your browser** — every book is stamped with an id kept in
  your browser's signed cookie, and the API only ever lists/opens/deletes books
  with that id. Opening the hosted app on another device is therefore a clean
  slate; it never shows anyone else's books. Combined with the browser vault below,
  the same browser gets its books back after a redeploy. Moving a book between
  devices is a deliberate action: **Export → JSON + images** on one, **Import** on
  the other (the `.zip` carries the pictures too).
  (Books created before this existed have no owner and stay visible everywhere — on a
  hosted instance the disk is wiped on each deploy, so none survive there.)
- **Books survive a server wipe** — every book the browser has opened or edited is
  also mirrored in the browser itself (IndexedDB, `static/js/local-store.js`). Saves
  are written there *before* the network call, so an edit still lands if the save
  fails, and anything the server has lost (a redeploy, or a free-tier spin-down that
  erases the container's disk) is pushed back on the next page load — same ids, same
  content, with a `[vault] wrote N book(s) back to the server` line in the console.
  Deleting a book clears it from both places, so it can't come back. Limits: the copy
  is per-browser (another device or a cleared site-data cache has nothing to restore),
  and uploaded image *files* under `books/assets/` are not mirrored — remote images
  (Wikimedia/Pexels) come back fine, local uploads may need re-adding.
- **Works on a phone** — below 900px wide the two panels become one swipeable,
  scroll-snapping pair (Outline first, AI Assistant one swipe away) with a bottom
  tab bar, a floating **✨ AI for this block** shortcut once a block is selected,
  a collapsed tone/depth/context section so the prompt and Generate stay above the
  fold, and ↑/↓ buttons for reordering (HTML5 drag doesn't fire on touch). The
  topbar there is just the logo, **＋** (new book), 🎓 and **⋮** — Import, Export,
  Delete, Settings and the light/dark toggle live in the ⋮ menu, and each item
  clicks the same hidden button the desktop layout shows, so there is only one
  implementation of each action. Outline rows give the title a full-width line of
  its own with the block tools underneath, so a long heading or a deeply nested
  one wraps normally instead of being squeezed into a one-letter-per-line column.
  Above 900px nothing changes — every mobile rule lives in the same media query,
  and the touch-only rules under `(hover: none)`.
- **Key bundles ("master keys")** — one passcode fills in several provider keys at
  once, for someone who shouldn't be pasting a Gemini key, a DeepSeek key and a
  Pexels key separately. Bundles are configuration you own: `REXTBOOKS_KEY_BUNDLES`
  (JSON, the one to use on a host) or `key_bundles.json` beside the app (gitignored).
  Each person's passcode unlocks **their own** bundle in **their own browser** — a
  signed cookie holds only an opaque bundle id, never the passcode or a key — so two
  people on one instance don't overwrite each other. A bundle that holds keys for
  both Gemini and DeepSeek lets you **switch between them**, and that choice stays in
  your browser rather than changing everyone else's. Enter it via the **🔑 icon
  beside the Settings title** (a small popover, shown only when the server has
  bundles configured); while unlocked, key fields it supplies are disabled because
  writing them would change the shared settings file. A bundle can also **limit
  which models its user may pick** (`"models": [...]`, or `"model": "…"` for
  exactly one): Settings then offers only those models and the server refuses
  anything else. See the Render notes for the JSON shape and a passcode generator.
- **Export** — **PDF** (15 palettes), **EPUB**, **Markdown**, or **JSON + images**
  (a `.zip` holding the book's own JSON plus an `Images/` folder with every picture
  it references, so a re-import keeps the pictures instead of showing broken
  links). **Content to include** in the Export dialog picks which parts of the
  book actually go in the file — tick a heading and its whole subtree comes along,
  untick anything you don't want, same cascading-select as Extra Context; defaults
  to everything. **Import** takes that `.zip` (or a plain `.json` book, the older
  format) from the topbar; a bundle's images are copied into the new book's own
  `books/assets/<new id>/` folder and its `Images/…` links rewritten to match, so
  nothing comes back broken. Every save also drops a
  versioned snapshot in `books/.trash/` (auto-pruned to 8) so a bad edit can't lose
  work — `GET /api/books/<id>/versions`, `POST /api/books/<id>/restore {file}`.
- **Author** — set in **⚙ Settings**; appears on the front page of PDF/EPUB exports
  (and as a byline in Markdown exports).

### PDF export

PDF is rendered by a **headless Chrome / Edge / Chromium** browser, if one is
installed on the machine running the server — no Python package required (Edge
ships with Windows 11, Chrome/Chromium are common elsewhere). The PDF then looks
exactly like the on-screen preview: cover page, table of contents with working
links, and the full palette colour.

The PDF also gets a proper **navigation pane / bookmarks outline** — nesting
every heading and subheading (down to a section's own internal `##` headings)
the same way your outline tree nests, each entry jumping straight to its page.
This comes from Chrome's own `--generate-pdf-document-outline` flag, built from
the real `<h1>`–`<h6>` tags in the rendered page — no extra dependency, and it
tracks pagination exactly (so it's correct even when content reflows across
pages as the book grows). Only the headless-Chrome path builds it; the
WeasyPrint and browser-print-dialog fallbacks below don't.

Detection is automatic (`GET /health` → `pdfEngine`). Set `REXTBOOKS_CHROME` to a
browser path to override. As a headless-server alternative you can
`pip install weasyprint` (needs Pango/cairo) — it's used if no browser is found.

If neither is available, the Export dialog's **PDF** option opens a palette-styled
print page and you choose *Save as PDF* (enable *Background graphics*).
**Markdown export always works.**

### EPUB export

`epub.py` builds the `.epub` by hand (no third-party ebook library) — same
palette/typography as the PDF, and a proper nested navigation: both an EPUB3
`nav.xhtml` and an EPUB2-compatible `toc.ncx`, built straight from the book's
heading/subheading tree. Chapters split one-per-top-level-heading, every image
(local or remote) downloaded and embedded as a real file since EPUB readers
don't fetch anything over the network, and CSS that wraps long code/tables and
caps image height so nothing overflows a reader's screen.

**Mermaid diagrams are rasterized to PNG, not shipped as live SVG.** One
headless-Chrome pass (loaded from a temp *file*, not the live `/preview` URL —
see below) renders every diagram the same way the PDF/app do, but Mermaid's
SVG output uses `foreignObject` (HTML labels embedded in SVG) and 8-digit
alpha-hex colours, both of which plenty of EPUB readers handle poorly (dropped
label text, solid-black shapes are the typical failure). So instead every
diagram gets screenshotted (at 2x for crisp high-DPI rendering) and embedded
as a plain image — same look everywhere, at the cost of no longer being
vector. A book can have 100+ diagrams, so they're stacked into a handful of
tall batch screenshots and cropped apart with Pillow rather than launching a
Chrome instance per diagram (which took minutes on a 130-diagram book; batched,
it's under a minute). If Pillow or a headless browser isn't available, a
diagram silently stays as live inline SVG (or, with no browser at all, plain
text) rather than failing the export.

The initial render loads a **temp file**, not the running server's own
`/preview` URL — if it renders from `/preview`, Chrome's request lands back on
the exact request-handler thread that's blocked waiting for Chrome, which
stalls badly under Werkzeug's dev server (a book that exports in under 90
seconds from a file took 4+ minutes hitting the live URL).

## Packaging a copy for someone else

`launcher.py` is the entry point for a zero-install handoff: it starts the
server without the dev reloader, opens the person's browser to it, and (on
Windows) drops a desktop shortcut with a proper icon the first time it runs —
built from wherever the folder actually ends up, so the whole thing can be
copied, renamed, or moved and it still works. If it's already running,
launching it again just opens another tab instead of erroring.

It runs on **port 5001**, not 5000 — deliberately different from the dev
server's port, so a packaged copy left running in the background (it launches
via `pythonw.exe`, with no console window and nothing in the taskbar to
notice) can never silently squat on the dev server's port and serve stale
content under it without anyone realizing.

The actual package is a **portable folder**, not a compiled `.exe` — Windows'
Smart App Control (on by default on most new Windows 11 installs) silently
blocks unsigned executables with no user override, which killed a PyInstaller
build in testing. A folder containing the official embeddable Python
distribution + the app's dependencies pre-installed + `launcher.py`, launched
via a `.vbs` that calls the (already Microsoft-signed) `pythonw.exe`, sails
through that same policy untouched — same one-click experience, no install
step, no console window.

To rebuild it:

```bash
# 1. Fetch the embeddable Python build matching your venv's version from
#    https://www.python.org/ftp/python/<version>/python-<version>-embed-amd64.zip
#    and unzip it into dist-portable/Rextbooks/python/

# 2. Point it at a sibling lib folder — edit dist-portable/Rextbooks/python/python312._pth
#    to add "..\pylibs" (relative to the python/ folder) as an extra line.

# 3. Install the runtime deps into that folder (not the app's own .venv):
pip install --target dist-portable/Rextbooks/pylibs --no-compile \
  Flask requests python-dotenv Markdown

# 4. Copy every .py file in the project root (app.py, config.py, epub.py,
#    export.py, etc.), templates/, static/, launcher.py, and an .ico into
#    dist-portable/Rextbooks/, then zip it.
```

No `.env` or `local_settings.json` goes into the package — the recipient
pastes their own key into **⚙ Settings**, which opens automatically the first
time there's no key configured at all.

## How it works

### Backend (Flask)

| File | Role |
| --- | --- |
| `app.py` | Routes: pages, book CRUD, SSE generation, render, images, export |
| `config.py` | Loads `.env`; provider presets, active provider/model/key selection |
| `llm.py` | Streaming + plain Chat Completions calls, for any OpenAI-compatible provider (DeepSeek, Gemini, …) |
| `deepseek.py` | Deprecated alias for `llm.py` |
| `prompts.py` | Prompt assembly (RULES vs overridable DEFAULTS), tone/depth, refine, context, templates — the text itself comes from `prompts.defaults.json` |
| `prompt_store.py` | Loads the golden prompt text + sparse user overrides; reset/save for Settings → Advanced |
| `prompts.defaults.json` | **Golden source of truth** for every prompt string the app sends |
| `prompts.local.json` | Your edits from Settings → Advanced (gitignored, created on first save) |
| `sparks.py` | The ten Spark modes + `build_spark_messages` |
| `store.py` | Book JSON persistence, per-book asset folders, versioned snapshots, import |
| `rendering.py` | Shared Markdown → HTML (turns ```mermaid fences into figures) |
| `images.py` | Validate + store section images (magic-byte sniff, size caps) |
| `palettes.py` | The 15 export colour palettes |
| `export.py` | `book_to_markdown` / `book_to_html` / `book_to_pdf` (recursive, any depth) |
| `bundle.py` | `book_to_bundle` — the JSON export's `.zip` (book JSON + `Images/`), and the unpack/rebind side the import route uses |
| `epub.py` | `book_to_epub` — nav.xhtml + toc.ncx, embedded images, pre-rendered Mermaid SVG |
| `pdfgen.py` | Renders a URL to PDF via a headless Chrome/Edge/Chromium; also dumps the post-JS DOM for EPUB |

Books are `books/<id>.json`. The browser owns the tree and PUTs the whole book
(debounced, serialized autosave); the server just reads/writes files. Set
`BOOKS_DIR` to keep books elsewhere (tests use this so they never touch `./books`).
`node` types nest freely: `heading` → `subheading` → `subheading` → … → `section`.

### Frontend (`static/`, no build step — native ES modules)

| File | Role |
| --- | --- |
| `js/api.js` | fetch wrappers, SSE reader, image upload, export hrefs |
| `js/store.js` | in-memory tree, mutations, settings, serialized autosave, pub/sub |
| `js/prompts.js` | templates, "selected block → mode" mapping, tone/depth lists |
| `js/block.js` | one block: toolbar, collapse, section render + Markdown editor + image panel |
| `js/mermaid-render.js` | lazy-loads mermaid.js, renders `pre.mermaid` blocks, themed + cached |
| `js/tree.js` | recursive render, native drag-and-drop, edit lock |
| `js/ai-dock.js` | right panel: target, tone/depth, Sub-topics/Content, Replace/Refine, context + Spark, streaming |
| `js/export-panel.js` | export modal: PDF/EPUB/MD/Pages/JSON-bundle + palette swatches |
| `js/spark-panel.js` | Spark modal: two sources, ten modes, prompt, streaming, node insertion |
| `js/main.js` | bootstrap, book switching, import |
| `js/book-picker.js` | custom-styled book switcher (a native `<select>`'s dropdown can't be skinned) |
| `js/tour.js` | the 🎓 Tutorial — spotlighted, step-by-step walkthrough |
| `js/settings-panel.js` | ⚙ Settings modal — provider, model, per-provider API keys, author |
| `js/resize.js` | draggable divider between the Outline and AI Assistant panels |
| `css/style.css` | mint-green base, translucent teal glass panels, shine + iridescence |

### Node types

`heading` → `subheading` (nests any depth) → `section`. Generating content for a
subheading creates or updates its single `section` child.

### The AI dock

The **mode** is decided by what block is selected, not by the prompt text:

- nothing selected → **outline** → creates top-level headings
- a heading selected → **subheadings** → creates subheadings under it
- a subheading / section selected → **content** → writes/updates the section body

The prompt textarea is pre-filled and editable. Each mode's system prompt in
`prompts.py` is split into **RULES** (invariants the app depends on — parseable
list output, section scope, no stray top-level headings; always enforced) and
**DEFAULTS** (house style — length, structure, how many images/diagrams; the
editable prompt overrides these). So "add more images than normal" or "make these
provocative" works, while "also write the next section too" is ignored. Image and
diagram counts are bounded (≈8 / ≈6) so an over-broad request can't blow up.
Editing the prompt still can't change which node type a mode creates — that's
enforced in `app.py`, not the prompt. **Reset** restores the default text.

The **Length** setting counts *body* words only: the closing **Summary** and
**Terminology** sections are written on top of the target rather than being part
of it, both in the prompt text and in the app's own under-length check
(`_body_word_count` in `app.py`, which drops those trailing sections before
counting), so a section can't reach its floor by padding the recap.
