# Change Log

Changes made to Rextbooks by Claude Code, most recent first. Entries below
2026-09-20 are reconstructed after the fact from conversation history and
file-modification timestamps (git commits during this period bundled many
changes into a couple of commits, so exact per-feature times aren't all
independently verifiable) — dates are accurate, times are best-effort.
From 2026-09-20 onward, entries are logged at the time each change is made.

---

## 2026-11-20 (bundle model limits: optional, and a deny-list spelling)

Follow-up to the model restriction: "could the restriction field not be
mandatory … and if it's in, say which models are restricted rather than which
are enabled?"

- Every model field stays **optional** — that was already true, but the docs and
  the example read as though `models` were expected. Leaving all of
  `models` / `excludeModels` / `model` out means every model is allowed (verified
  end to end: `allowedModels: []`, the full preset list offered, any model
  accepted).
- New `"excludeModels": [...]` — the models that are **not** allowed, measured
  against the provider's own preset list. This is the spelling the user asked
  for: `"excludeModels": ["gemini-3.8-flash"]` blocks that one and leaves the
  rest selectable. `models` (only these) and `model` (exactly one) still work,
  and each accepts a per-provider `{provider: [...]}` map.
- `_parse_allowed_models` became `_parse_model_map`, used for both fields;
  `bundle_allowed_models()` now resolves the effective list (allow-list first,
  then exclusions removed from it). A deny-list that happens to cover *every*
  preset model is treated as a typo: it collapses to the provider's default
  model rather than silently lifting the restriction.
- `get_llm_model` / `set_llm_model` now call `bundle_allowed_models()` rather
  than reading the raw allow-list, so an excluded model is refused with a 400
  just like a non-listed one. `key_bundle_info()` reports the effective `models`
  *and* the raw `excludeModels`, so Settings can say "disallows X — you can use
  Y" instead of showing an unexplained shorter list.
- Settings model note and the 🔑 popover both state the exclusions.
- Verified: deny bundle offers the two remaining models, refuses an excluded one
  (400), accepts an allowed one; per-provider deny map only affects its own
  provider; unrestricted bundle unchanged; `local_settings.json` still
  byte-identical.

## 2026-11-20 (mobile outline layout + ⋮ topbar menu; key bundles can restrict models)

**1. Mobile: outline rows and the topbar.** Reported with a phone screenshot of
the Render site: a heading rendered as one letter per line, and the topbar
wrapped "New book / Import / Export / Delete / ⚙ / ◑" into a crowded stack.

- Cause of the vertical text: `.block-row` is a single flex line. On touch the
  tool buttons are forced visible at 38px each (seven of them), so the buttons
  plus the kind label and drag handle consumed the whole row and `.b-title`
  shrank to roughly one character wide. `overflow-wrap: anywhere` then did
  exactly what it says.
- Fix (`static/css/style.css`, inside the existing `max-width: 900px` block):
  `.block-row` is a 3-column grid — chevron, then a title line and a tools line
  — so the title always gets the full row width regardless of its length or
  nesting depth; the drag handle and the "HEADING" label are hidden there (drag
  doesn't fire on touch anyway, and ↑/↓ buttons exist); child indentation was
  reduced from 32px to 18px per level; `.b-section-body` lost its 30px left
  margin. Verified at 390x844: titles 261–299px wide, long headings wrap to two
  lines, no horizontal overflow — and at 1280px the rows are still the original
  single flex line with hover tools.
- Topbar (`templates/index.html` + `static/js/mobile-menu.js`, new): below 900px
  the labelled buttons are hidden and the row is just the logo, **＋** (new
  book), 🎓 and **⋮**. The ⋮ panel holds Import, Export, Delete book, Settings
  and Light/dark mode (with the current Auto/Light/Dark state beside it); each
  item clicks the same hidden desktop button, so there is exactly one
  implementation of each action. Closes on outside click, Escape, or crossing
  back above 900px. New book's ＋ clicks the same handler as the labelled one.
- `combo.js` gained `setDisabled()` for the model picker below.

**2. Key bundles can now restrict which models a user may pick.** Asked for a
third bundle holding only a Gemini key, limited to certain models.

- `config.py`: new optional `"models"` per bundle — a list (applies to that
  bundle's provider) or a `{provider: [...]}` mapping. `"model": "…"` still
  works and is treated as a one-item list. Parsed by `_parse_allowed_models`
  into `bundle["models"]`; `bundle_allowed_models()` exposes it.
- Enforcement is server-side: `get_llm_model` clamps to the list (session
  choice → pinned → first allowed) and `set_llm_model` raises `RuntimeError` for
  anything else, which `api_save_settings` returns as a 400. A request that
  bypasses the UI is refused just the same.
- The model choice is now **per session** for every bundle (like the provider
  choice): `session["models"]`, applied by `config.set_request_models` in
  `before_request`, re-applied inside `_stream_chat_response`'s generator (same
  reason as the provider — teardown clears the thread-local), and cleared by
  `api_settings_lock`. Verified: two browsers on one bundle hold different
  models, `local_settings.json` stays byte-identical, and an SSE generation's
  first event reports the restricted model.
- Settings UI: when a bundle names models, the dropdown offers only those (no
  "Custom model…", text input hidden), a one-model bundle disables the control
  and shows what's in use, and both the model note and the 🔑 popover say why.
  Without `models`/`model` everything behaves exactly as before.
- `experiments/render/README.md` documents the JSON shape with a worked
  "Lite plan" bundle; README and CLAUDE.md updated for both changes.

## 2026-11-17 (Render deploy failed: `No module named 'bundle'`)

Deploy exited with status 3, `gunicorn` worker failing to boot at
`/srv/app.py` line 41 (`from bundle import book_to_bundle, read_bundle,
rebind_images`) — while the same code ran fine locally and in
`dist-portable/`.

Cause: `experiments/render/Dockerfile` copied the app's modules from an
**itemised** list (`COPY app.py config.py llm.py … palettes.py ./`). Adding
`bundle.py` for the new JSON+images export never touched that list, so the
image shipped `app.py` without the module it imports. Nothing else was wrong —
no missing dependency, no ignore rule.

- Fix: the COPY now globs the app's own modules
  (`COPY *.py prompts.defaults.json ./`), with a comment recording the
  failure. Every `.py` at the repo root is an app module (the portable build
  and any scratch work live in folders `.dockerignore` already drops), so a
  future new module can't be forgotten this way. `templates/` and `static/`
  are still copied explicitly.
- Verified by rebuilding the exact file set the Dockerfile now produces in a
  temp directory and importing `bundle` + `app` from it — image boot OK.
- **Remember:** `.dockerignore` is not the issue and needs no change; the
  Dockerfile is the only place with a file list.

## 2026-11-17 (JSON export carries its images; Summary/Terminology don't count towards Length)

**Two changes, both about a book's own words and pictures leaving and coming
back intact.**

1. **The Length target now means body-only.** Reported as: a "medium" section
   could hit its word floor while much of that was the closing Summary.
   - `prompts.defaults.json` — `content.defaults.summary` and the new
     `content.defaults.terminology` text both say the recap/glossary are extra,
     written *after* the body reaches the target; `content.defaults.length.low/
     medium/high` and `shared.length_extension` say the same thing at the point
     where the model is actually choosing a length.
   - `app.py` — new `_body_word_count()` (plus `_HEADING_LINE` / `_RECAP_TITLE`)
     strips a *trailing* run of recap headings (`summary`, `key takeaways`,
     `in summary`, `terminology`, `glossary`, `key terms`) before calling
     `_prose_word_count`, so the under-length check measures what the prompt
     describes rather than something the recap can pad. A recap heading in the
     middle of a section doesn't truncate anything, and a body that is *only* a
     recap is left alone instead of measuring 0. The extension round now asks
     for new sections *before* any existing closing Summary.
   - Verified with a snippet against 8 shapes (body only, body+Summary,
     body+Summary+Terminology, body+Terminology, mid-text "Summary of the
     argument", trailing "Glossary", all-summary, recap then a bullet list):
     the recap tail is excluded every time and mid-text headings still count.

2. **JSON export is now a `.zip` that includes the images.**
   - New module `bundle.py` (not `export.py`, which can't import `epub` at
     module level without an import cycle): `book_to_bundle()` reuses the EPUB
     path's `_AssetBag` (fetch/dedup/Lite-compress) and `pages._asset_prefix`,
     rewrites each section's `![alt](src)` to `Images/<name>`, and zips
     `<slug>/<slug>.json` + `<slug>/Images/*`. A single unfetchable image is left
     as its original reference rather than failing the export.
   - `/api/books/<id>/export.json` serves that zip (`application/zip`).
   - `POST /api/books/import` detects the format by magic bytes (`PK\x03\x04`),
     not the filename: `read_bundle()` takes the shallowest JSON that parses to
     a real book plus the images in *its own folder* (ignoring `__MACOSX`, stray
     top-level files, another bundle's folder), the book is created, each image
     is written to `books/assets/<new id>/`, and `rebind_images()` points the
     `Images/…` (and any legacy `/assets/<old id>/…`) references at the new id.
     A plain `.json` upload still imports exactly as before.
   - Frontend: the Export dialog's JSON tab reads **JSON + images** with a note
     about the zip; **Lite** now applies to it too (images are recompressed);
     the Import input accepts `.zip` as well as `.json`.
   - Verified on an isolated server: export → zip members
     `<title>/<title>.json` + `<title>/Images/<slug>-<id6>-img1.png`, owner
     stripped from the payload; zip import returns 201, the image lands in the
     *new* book's asset folder, the rewritten `/assets/<new id>/…` URL serves
     200 `image/png`, excluded nodes stay pruned, a junk zip 400s, a hand-made
     zip with nested folders + `__MACOSX` imports correctly, plain JSON still
     imports, and another owner still gets 404. Also driven through the real
     browser: Export dialog shows the new label/note, and importing a bundle
     opens the book with the image rendering from `/assets/<new id>/…`.

## 2026-11-17 (books are per-browser)

**A book created on one device no longer appears on another.** Reported as:
opening the Render site on a phone showed the books made on the desktop.

- `app.py` — `before_request` creates a random 32-hex `session["owner"]` on the
  first visit and keeps it in the signed cookie. `_owner()` feeds every book
  route; `POST /api/settings/unlock` now re-sets it after `session.clear()`, so
  unlocking a key bundle no longer orphans that browser's books.
- `store.py` — books carry an `owner` field; `list_books`, `get_book`,
  `save_book`, `delete_book`, `import_book` and `restore_book` all take an
  optional `owner` (`None` = unfiltered). A book with no owner (created before
  this change) stays visible to everyone: that keeps an existing local library
  working and can't leak on a hosted instance, whose disk is wiped on every
  deploy — every book created there is stamped.
- Exports had to be handled: the PDF path loads
  `/api/books/<id>/preview` in headless Chrome, which sends **no session
  cookie**, so an owner-only check would have 404'd every PDF export.
  `_preview_token()` (HMAC of book id + owner, keyed on `app.secret_key`) is
  appended to the render URL by `export.book_to_pdf(token=...)`, and the preview
  route accepts either that token or normal ownership.
- Verified with two separate cookie jars and two real browser contexts:
  A creates a book → A sees it after a reload, B (fresh browser, mobile size)
  does not, and B's GET/PUT/DELETE on A's book return 404/false. A's **PDF
  (11.9 KB, valid `%PDF`) and Pages exports still succeed** after the change;
  B exporting A's book is 404. Simulated redeploy (deleted A's file): A's list
  drops it, `POST /api/books/restore` re-creates it stamped with A's owner, and
  B still cannot see it.
- Consequence for the user: transferring a book between devices is now a
  deliberate Export → JSON / Import. Documented in README, CLAUDE.md and the
  Render notes.

## 2026-11-16 (night, CRITICAL: bundle keys not used when streaming)

**A key bundle was correct in Settings but the generation used the machine's own
keys instead** — reported as "Google Gemini 400: Please pass a valid API key"
(and the same failure on DeepSeek) for both people, on the hosted instance.

Cause: `_stream_chat_response` returns a generator whose body runs **after** the
view returns. Flask tears the request down at that point, so
`teardown_request`'s `config.clear_active_bundle()` had already run before the
first `llm.stream_chat()` — every streamed call therefore resolved keys without
the bundle and fell back to `local_settings.json`/env. The Settings dialog
(non-streaming) was unaffected, which is why unlocking "worked" and showed both
providers while generation still failed. It silently used whatever old
`GEMINI_API_KEY` / `DEEPSEEK_API_KEY` env vars the service had, so both providers
failed identically for both users.

- Fix: `_stream_chat_response` captures `session["bundle"]` and
  `session["provider"]` while the request is alive and re-applies them at the
  top of the generator (`set_active_bundle` / `set_request_provider`), clearing
  them in a `finally`. This also covers the post-stream work that needs keys —
  image-search judging and Pexels lookups.
- Reproduction (before the fix), with an empty `local_settings.json` and
  deliberately invalid env keys: Settings reported `provider=gemini,
  keySource=bundle`, the `start` event said Gemini, and the actual call failed
  with **"DeepSeek 401 … NOT-A-REAL-DEEPSEEK-KEY is invalid"** — proof the
  stream had fallen back to the environment. After the fix the same session
  generated 1,209 characters on DeepSeek through the bundle key, and the Gemini
  call reached Google (which returned a transient 503).
- Verified the reported keys themselves are fine: the Gemini key works on
  `/v1beta/models` and on the OpenAI-compatible endpoint, and both DeepSeek keys
  return 200 on `/models`. `gemini-3.8-flash` was returning **503 "high demand"**
  at the time while `gemini-3.6-flash`, `gemini-3.5-flash-lite` and
  `gemini-3.1-flash-lite` all returned 200 — so a 503 in that situation is the
  model, not the key; pick a different model in Settings → Model.

## 2026-11-16 (night, subtle key UI)

**The key bundle moved out of the Settings body and behind a 🔑 icon.**

It was a labelled field sitting above Provider, which drew every user's eye and
invited "what is this key for?" — exactly the wrong first impression for someone
who just wants to write a book.

- The whole block is gone from `.modal-body`; the header now has
  `<h2>⚙ Settings</h2>` on the left and a small `.modal-head-actions` group on
  the right holding 🔑 then ✕.
- `#settings-bundle-toggle` opens a small popover anchored under the header
  (`.kb-popover`): paste + **Unlock** when locked, `🔑 <label>` + **Lock** plus a
  one-line "Unlocks gemini, deepseek for this browser" when unlocked. Closes on
  outside click, `Esc` (which does not also close Settings), or the ✕ in the
  popover, and is always reset when Settings closes.
- The icon is **hidden entirely** unless `keyBundle.configured` is true, so an
  ordinary install never renders it. When a bundle is active the icon takes a
  quiet accent tint (`.is-unlocked`) instead of a banner — a hint, not an
  announcement.
- Verified on a configured server: icon present at 12px muted, popover closed on
  open, click opens it and focuses the input when locked, unlock switches to the
  label/Unlocks view and keeps the popover open, outside-click and `Esc` close
  only the popover, Lock returns it to the paste state, and the icon tints.
  On a server with no bundles the button is `hidden` and never appears.

## 2026-11-16 (night, bundles: switchable providers)

**A key bundle no longer locks you to one provider.** If a bundle holds both a
Gemini and a DeepSeek key, the Settings provider picker stays live and switches
between them.

- The choice is stored **in the session** (`session["provider"]`), not in
  `local_settings.json` — otherwise one person switching to Gemini would switch
  it for everyone else on the instance. `config.set_request_provider()` carries
  it on the request thread, and `get_llm_provider()` resolves:
  session choice (if the bundle has that key) → bundle's declared `provider` →
  first available → the normal global chain.
- `set_llm_provider()` inside a bundle now validates against
  `bundle_providers()` and pins the session instead of raising; asking for a
  provider the bundle has no key for still fails with a specific message
  ("… has no DeepSeek key — it can use: Google Gemini.").
- `key_bundle_info()` gained `availableProviders` and `modelProvider`, so the UI
  enables exactly the providers the bundle can serve, and stops claiming a
  pinned model once you've switched to the provider it doesn't apply to.
- Locking clears the session choice, so a bundle user's preference never leaks
  into the machine's own settings.
- Verified: bundle with both keys — switch deepseek → gemini → deepseek all 200,
  the gemini model resolved from the saved per-provider setting, key placeholder
  followed the provider; bundle with only Gemini — DeepSeek option disabled and a
  POST for it returns 400; two sessions on the same bundle sit on different
  providers independently; `local_settings.json` was byte-identical before and
  after a switch.

## 2026-11-16 (night, mobile + master keys)

**1. Pages export: unique image filenames (fixes two books overwriting each
other in one Obsidian vault).** `epub.py`'s `_AssetBag` takes an optional
`prefix`, and `pages.py` passes `_asset_prefix(book, root_name)` — the book's
title slug plus six characters of its id, e.g.
`the-brain-as-a-computer-3f2a91-img1.png`. Obsidian resolves `![[img1.png]]`
by filename across the whole vault, so two exports both starting at `img1`
silently replaced each other; now a re-export overwrites only its *own*
images. EPUB keeps the unprefixed `images/imgN.png` because those names live
inside the container.

**2. Key bundles ("master keys").** One passcode fills in several provider
keys at once.

- `config.py` — bundles are read from `REXTBOOKS_KEY_BUNDLES` (JSON env var,
  the hosted path) or `key_bundles.json` beside the app (gitignored); each
  top-level key is the passcode. Entries accept `{"label", "provider",
  "model", "keys": {...}}` or the flat shorthand `{"label", "gemini": "…"}`.
  `resolve_passcode()` compares ids in constant time; a bundle with no LLM key
  is ignored; malformed config is reported once and skipped rather than
  blocking boot.
- Resolution is **per request** via a `threading.local`: `get_llm_provider`,
  `get_llm_model`, `get_api_key`, `api_key_source` ("bundle") and
  `get_pexels_key` all consult the unlocked bundle first. Nothing is written to
  `local_settings.json`, so two people on the same instance cannot overwrite
  each other — the answer to "does the last master key win?" is **no**.
- Writes to anything a bundle supplies (`set_api_key`, `set_pexels_key`,
  `set_llm_provider`, and `set_llm_model` when the bundle pins a model) raise
  `RuntimeError`; `api_save_settings` turns that into a clear 400.
- `get_secret_key()` signs a session cookie that holds only an opaque bundle
  id — `REXTBOOKS_SECRET_KEY` when set (recommended on Render, so redeploys
  don't log everyone out), otherwise a value generated once into
  `local_settings.json`.
- `POST /api/settings/unlock` / `/lock`, rate-limited to 10 attempts per 5
  minutes per IP; wrong passcode 401, then 429. The passcode is never stored,
  echoed, or logged.
- Settings UI: a quiet **🔑 Key bundle** field (hidden unless the server has
  bundles configured) — passcode + Unlock when locked, `🔑 <label>` + Lock when
  unlocked, with managed controls disabled and a note saying so. The status
  line gained a `bundle` case.
- Verified over HTTP with two sessions: A unlocked "Mum" (Gemini + Pexels,
  provider forced to Gemini), B unlocked "Me" (DeepSeek + model), **A stayed on
  Mum after B unlocked**; apiKey/provider/Pexels writes from A were refused;
  lock fell back to DeepSeek's own saved key; bogus passcode 401; 11th attempt
  429. Then the same flow through the real Settings dialog.

**3. Mobile layout — a second presentation of the same DOM.** Everything is
inside the existing `max-width: 900px` query (plus `(hover: none)` rules), so
desktop is untouched.

- `.workspace` becomes a horizontal, scroll-snapping carousel of the two panes
  (native momentum, no gesture code); `static/js/mobile-view.js` (new) syncs the
  bottom tab bar with the scroll position, exposes `showMobileView()`, flips the
  carousel back to the outline if the window grows past the breakpoint, and
  delegates "tap anywhere on a `.block-row`" to the ordinary title click so the
  title text isn't the only hit target.
- Bottom tab bar (Outline | AI Assistant, 46px targets), a floating
  **✨ AI for this block** button that appears once a block is selected, and a
  collapsed "Tone, depth & context" toggle so the prompt + Generate stay above
  the fold. Generate is sticky at the bottom of the dock.
- The book switcher moves to its own full-width row on the topbar (it was
  hidden before — that would have left no way to change books on a phone).
- Touch rules under `(hover: none), (pointer: coarse)`: block tools/handles are
  always visible (they were `:hover`-only, so invisible on touch), 38–46px
  targets, and 16px inputs so iOS stops zooming on focus.
- `block.js` gained `.b-tool-mobile` **↑/↓ move buttons** — HTML5 drag-and-drop
  never fires on touch, so reordering had no path at all on a phone.
- `body` height uses `100dvh` (with `100vh` fallback) so phones don't lose the
  bottom of the layout to the collapsing toolbar.
- Verified: desktop at 1280px is still `display: grid` with the same two
  columns, no mobile chrome, block tools still hover-only and a row click still
  does *not* select; at 390×844 the workspace is a flex carousel (two 370px
  pages), the tab bar switches panes (scrollLeft 0 → 370) and syncs back,
  tapping a row selects + shows the AI shortcut which jumps to the dock with
  that block as the target, and the compact toggle expands the tone/depth group.

## 2026-11-16 (night, UI)

**Settings → Model is a proper dropdown now.**

It was an `<input list="…">` + `<datalist>`, and a datalist only shows its
options once the field is empty (typing/keeping a value filters the list to
nothing), so the arrow looked like a dead control. It also rendered in OS
chrome, unlike everything else in the app.

- **`static/js/combo.js` (new)** — a small reusable single-select combobox:
  button + themed listbox, ↑/↓/Enter/Space/Esc/Tab, click-outside to close,
  moved to `<body>` while open (containers using `backdrop-filter` trap fixed
  descendants), and it flips above the button when there's no room below.
  Exposes `setItems` / `setValue` / `getValue`, and a `CUSTOM` sentinel item
  that reports itself instead of becoming the selection.
- **`templates/index.html`** — the model field is now `<div class="combo">` +
  the same `#settings-model-input`, hidden, used only for a free-form name.
  So `onSave`/`onTest` still read one value, unchanged.
- **`static/js/settings-panel.js`** — the list is
  `default (gemini-3.8-flash)`, the provider's models, then **Custom model…**,
  which reveals the text input for any name the provider accepts (that
  capability was in the old helper text and still works). The button label
  follows typed text live.
- **`static/css/style.css`** — `.combo-*` shares the book-switcher's rules
  (`.book-picker-*`), so the two dropdowns are literally the same styling: the
  computed style of the two buttons is byte-identical (same background,
  border, radius, padding, 13px/600 type). The list needs `z-index: 70`
  (set inline at open) because the settings modal's backdrop is `z-index: 50`
  — at 40 the modal swallowed every click on the open list.
- Verified in the browser: opening shows 5 items with the saved model
  highlighted; a mouse click selects (`gemini-3.6-flash` in both the label and
  the hidden input, list closed); ↑/↓ + Enter selects too; "Custom model…"
  reveals and focuses the input, and typing updates the label
  (`gemini-9-experimental`), so Save still sends what the user sees.

## 2026-11-16 (night, later)

**Books now survive a redeploy: the browser keeps its own copy.**

The problem: books were never in the browser — only on the server's disk, which
a hosted instance wipes on every redeploy (and on free-tier spin-down), so a
book someone was working on simply disappeared with nothing to recover from.

- **`static/js/local-store.js` (new)** — a small IndexedDB store
  (`rextbooks-vault`) holding `{id, title, updatedAt, cachedAt, dirty, book}`
  per book. No dependency, and every operation degrades to a no-op when
  IndexedDB is unavailable (private mode), leaving the app exactly as before.
- **`static/js/store.js`** — `flush()` mirrors the book locally *before* the
  PUT, marked `dirty`, and re-mirrors the server's response as clean. So a save
  that never reaches the server (spin-down, dropped connection) still lands in
  the browser. The "Save failed" label became "Kept in this browser — server
  save failed", which is now true.
- **`static/js/main.js`** — on startup `restoreMissingBooks()` compares the
  vault with `/api/books`: a book the server no longer has is re-created with
  its **original id**, and a `dirty` copy is force-saved over an older server
  version (otherwise a failed save would silently revert on the next load).
  `openBook()` falls back to the vault if the server can't serve a book, and
  caching happens on open too, so unedited books survive as well. Delete removes
  both copies so nothing is resurrected; the startup path is wrapped so an
  unreachable server shows the empty state instead of an unhandled rejection.
- **`app.py` / `store.py`** — `POST /api/books/restore` →
  `store.restore_book(data)`: validates the id, **keeps the original id**, and
  only ever creates a missing book (an existing server copy is returned
  untouched), so this endpoint cannot roll back real work.
- **Verified against a scratch server with the book file deleted from disk**
  (exactly what a redeploy does): reload → `[vault] restored 1 book(s)`,
  `/api/books` lists it again, and the outline shows the original tree with its
  section text intact. A simulated failed save (`PUT` stubbed to reject) left
  `saveStatus: error` with a `dirty` vault record, and the next load pushed it
  back — server title became "Edited while offline", record clean. Deleting
  through the UI cleared server and vault (0 and 0) and the next reload did not
  bring it back.
- Known limits (documented in README/CLAUDE.md and the Render notes): the copy
  is per-browser, and uploaded files under `books/assets/` are not mirrored —
  remote images survive, local uploads may need re-adding. Server-side
  durability across devices would be a Render persistent disk (paid) or the
  stateless/BYOK variant.
- **The whole library is cached, not just the open book** (`mirrorLibrary` in
  `main.js`): after a book opens, any book this browser hasn't cached yet is
  fetched once in the background (fire-and-forget, skipped above 50 books), so a
  redeploy can't strand the books the user wasn't looking at. Verified on the
  real local library: 15 server books → 15 vault records, 0 dirty.
- **Fixed a real pre-existing bug found by that pass**: `store.list_books()`
  globbed `*.json` and so also returned the `<id>.usedimages.json` sidecars as
  phantom "books" (ids like `0596…usedimages`, title "Untitled") — they showed
  in the picker and made the vault try to download and restore them (HTTP 500).
  A real book must now have an `id` **and** a `nodes` list. The local library
  went from 20 listed to the 15 real books.
- Files synced to `dist-portable/Rextbooks/` including the new
  `static/js/local-store.js`.

## 2026-11-16 (later still)

**Export memory tuning for small hosted instances** (`pdfgen.py`,
`experiments/render/README.md`). No behaviour change locally beyond exports
queueing instead of running two browsers at once.

- `_MEMORY_FLAGS` are now passed to all three headless launches (PDF,
  `--dump-dom`, screenshot). The decisive one is `--disable-dev-shm-usage`:
  Docker's `/dev/shm` is 64 MB by default, which Chromium uses heavily, so
  exports on a 512 MB instance crash or get OOM-killed without it.
- `_BROWSER_LOCK` serialises browser launches, so a second export/preview
  waits instead of starting a second Chromium and doubling peak memory.
  Verified: two PDF exports requested concurrently complete in 4.0 s and
  7.6 s (wall 7.6 s) — one queued, exactly as intended. PDF (125 KB, `%PDF`),
  EPUB (valid zip) and the Pages zip (with a rasterized diagram) all still
  export correctly.
- `_run()` replaces the bare `subprocess.run(timeout=…)`: on POSIX the browser
  starts in its own session and the whole process group is SIGKILLed on
  timeout, because killing only the parent left zygote/renderer children
  holding their memory — one slow export could otherwise poison the instance.
  Windows keeps the plain path (no process-group equivalent).
- `experiments/render/README.md` gained a "Tuning a small instance" section:
  which symptom a longer timeout fixes (504/slow) versus one it can't (OOM),
  the serialisation and flags above, then Lite export → export chapters →
  `--threads 4` → bigger plan, and the optional `--max-requests` recycle.

## 2026-11-16 (night)

**Mermaid reliability: prompt rewritten as a format convention, and the
renderer made resilient to a single failure.**

- **`prompts.defaults.json` — `content.defaults.diagram_compact` rewritten.**
  It was a list of bans ("never use packet-beta, kanban, …", "never use ->-")
  that a small model obeys unreliably. It is now a *shape* to copy: one
  sentence of format (fence info string exactly `mermaid`, one type
  declaration, one indented statement per line), then two fully worked
  examples (`flowchart TD`, `mindmap`), then a condensed one-line skeleton
  for each of the other 15 verified types, then the shared rules (plain-word
  labels, `-->` / `->>` arrows only, ~10-12 items per diagram, vary the
  type), and finally — as a single factual sentence, not a block of
  prohibitions — the six type names that don't exist in Mermaid 10.9.1.
  `spark.defaults.diagram_size` got the same treatment in a shorter form.
- **Verified**: all 17 recommended types render under `mermaid@10.9.1` with
  the exact syntax the prompt now documents (17/17 OK). A real Gemini
  generation ("Supply chain risk", High length, High diagram frequency)
  produced **8 diagrams across 5 different types** (mindmap ×2,
  flowchart TD ×2, xychart-beta, sequenceDiagram ×2, quadrantChart) and
  **8/8 rendered** — previously this was the exact case that produced a
  mindmap error box.
- **`static/js/mermaid-render.js` — no failure caching, serialised renders,
  retries.** Root cause of "the same diagram renders on reload but not
  during generation": renders ran concurrently (`Promise.all` over blocks)
  and a failed render was cached as `svgCache.set(code, null)`, so one
  transient failure during streaming stayed broken for the life of the page
  even though the source was valid. Now: an `enqueue()` promise chain runs
  renders one at a time; only successes are cached; a failure logs
  `console.warn("[mermaid] render failed", …)` with the offending source,
  retries up to 2× after 700 ms, and leaves a click-to-retry box
  (`title` + `pre.dataset.mmdClick`) instead of a dead error.
- **Verified**: a section with one deliberately malformed `pie` plus one
  valid `flowchart` shows 1 error box + 1 rendered SVG (the failure no
  longer takes its neighbours with it), warns on each attempt, retries, and
  the click path re-attempts.
- **Layout clipping hardening** (`static/css/style.css`, `static/js/resize.js`).
  The AI pane's remembered drag width (up to 760px) was used as a *hard
  grid max*, so after dragging the divider wide the two columns could be
  wider than the window — and because `body` is `height:100vh;
  overflow:hidden` there was no scrollbar to reach the rest, which clips the
  right-hand panel at any zoom level. The track is now
  `minmax(280px, min(var(--ai-pane-w, 384px), 46vw))` and
  `mountPaneResizer()` clamps the stored width on startup. Verified at
  1400/1100/950/860px with a deliberately over-wide stored value: no
  horizontal overflow at any of them (860px folds to the stacked layout).
- **The "app cuts short while generating" bug — root cause found and fixed**
  (`static/js/mermaid-render.js`). Mermaid mounts each render in a temporary
  `<div id="dmmd-…">` appended to `<body>` and normally removes it again; a
  render that *throws* (or two that overlap) leaves it behind. Those leftovers
  are ordinary in-flow elements, so they stacked **below** `.workspace` inside
  the `body` flex column and squeezed the workspace: measured on a real book,
  three leftovers took 338px and the panes shrank from ~765px to 427px tall.
  Every diagram rendered therefore made the UI shorter, and because the page
  can't scroll there was no way to reach the rest — which is why zooming
  didn't help. `sweepStrayRenderings()` now removes any `body > div[id^="dmmd-"]`
  / `mmd-` after every render (success or failure) and at the start of a pass.
  Verified: strays 3 → 0, `.workspace` bottom 522 → 860 (full window), pane
  heights 427 → 713/765, with 3 diagrams rendered and 0 errors.
- **`xychart-beta` axis repair** (`rendering.py`, `_clean_xychart_axis`).
  A real saved diagram in the user's own book failed with "Lexical error …
  Unrecognized text" because its axis was `x-axis [0%, 20%, 40%]` — the
  bracket form is a band scale and rejects `%`. The symbols are never
  meaningful to Mermaid, so `_repair_mermaid_source` now strips punctuation
  from `x-axis [...]` labels (quoting anything with a space) for
  `xychart-beta`. That diagram now renders without being edited; verified the
  repaired form plus a currency-label variant both render under 10.9.1.
- Synced `prompts.defaults.json`, `rendering.py`, `static/js/mermaid-render.js`,
  `static/js/resize.js` and `static/css/style.css` into
  `dist-portable/Rextbooks/`.

## 2026-11-16 (late)

**Added an isolated Render deployment experiment (no application code touched).**
Purpose: answer "does full functionality fit on Render's free 512 MB tier?"
before committing to any hosting or stateless-port work.

- **`experiments/render/Dockerfile`** — python:3.12-slim + Debian `chromium`
  (so `pdfgen.find_browser()` finds `/usr/bin/chromium` by name, no
  `REXTBOOKS_CHROME` needed) + Liberation/DejaVu fonts; installs the project's
  own `requirements.txt` plus gunicorn (deployment-only, so `requirements.txt`
  is unchanged); `COPY`s only runtime files; `BOOKS_DIR=/data/books`; runs
  `gunicorn app:app` with `--worker-class gthread --threads 8 --timeout 1200
  --forwarded-allow-ips="*"` (gthread so an SSE generation can stream while
  other requests are answered; forwarded-ips so Flask builds `https://` preview
  URLs for Chromium).
- **`.dockerignore`** (repo root, additive) — the Render service uses Root
  Directory = repo root so the Dockerfile can copy the app from there, which
  makes the whole repo the build context. This keeps `.venv/`, `dist-portable/`,
  `docs/`, `books/`, `.env`, `local_settings.json` and `prompts.local.json` out
  of both the upload and the image.
- **`experiments/render/README.md`** — exact Render dashboard values (Root
  Directory blank, Runtime Docker, Dockerfile Path, build context blank, health
  check `/health`, free instance), env vars, the test checklist, how to read an
  OOM, and an optional `render.yaml` blueprint snippet.
- **Validated locally**: gunicorn cannot run on Windows at all (`fcntl` import
  fails — worth recording), so the same WSGI shape was exercised with waitress
  (`app:app`, 8 threads, temp `BOOKS_DIR`): `/health` ok, `/render` produced
  MathML + bold, **PDF export 200 / 81 KB valid `%PDF`**, **EPUB 200 / valid
  zip**, and an SSE generation streamed `start` + deltas to `done` through the
  production server with no errors. gunicorn flags themselves are standard and
  will be exercised by the first Render build.
- The venv was used for the waitress/gunicorn check only; both were uninstalled
  again, so nothing was added to `requirements.txt`.

## 2026-11-16 (evening)

**Feature: LaTeX math now renders (was showing raw `$…$`).** Reported with a
generated section whose formulas ("`$CY = \frac{V \times S}{T}$`") appeared as
plain text.

- **What already existed:** only `md.ESCAPED_CHARS.append("$")` in
  `rendering.py`, which consumes `\$42`-style escapes so a stray backslash
  doesn't leak through. There was no MathJax/KaTeX anywhere (the `katex` hits in
  `docs/` are Mermaid's own stylesheet).
- **Approach: server-side LaTeX → MathML** in `rendering.py`, not a client-side
  KaTeX/MathJax. Reason: `render_markdown` is the single render used by the live
  preview, PDF, Pages and (via `book_to_html`) EPUB, and Chromium renders MathML
  Core natively while EPUB3 supports MathML — so there is no CDN dependency, no
  script-timing problem in the headless export passes, and exports match the
  preview exactly. New dependency: **`latex2mathml`** (pure Python).
- **Delimiters**: `$…$`, `$$…$$`, `\(…\)`, `\[…\]`. Guards: a `$` must not be
  backslash-escaped, no space just inside the pair, inline math stays on one
  line, and the body must contain a letter or a TeX command — that last rule is
  what keeps currency out ("$5 and $7", "$5-$7" are left alone). Fenced blocks
  and inline code spans are split out first and never touched, so `$x$` inside
  code stays literal. Invalid TeX raises inside `latex2mathml` and the source is
  left exactly as written (no worse than before). Missing package degrades to
  the same pass-through.
- **Styling**: `.math-block` (centred, overflow-x) and `.math-inline`
  (nowrap) added to `style.css`, `export.py`'s print CSS and `epub.py`'s
  `_epub_css`. Display math is wrapped in its own `<div>` so it can't be split
  across a PDF page (`break-inside: avoid`).
- Verified: 10 render cases (inline, `$$`, paren/bracket, code fence, inline
  code, currency, escaped dollar, invalid TeX, table cell) all behave; in a real
  browser 9 `<math>` elements render with real dimensions and the currency/code
  text is untouched (screenshot checked); EPUB contains `<math>`/`<mfrac>` in
  the chapter XHTML plus the new CSS; a PDF exported from a scratch server
  contains the formula as real MathML glyphs (𝑪𝒀 = 𝑽 × 𝑺 over 𝑻 in the
  extracted text, no raw `\frac`), and the print stylesheet rasterised through
  headless Chromium shows a correctly stacked fraction.
- `rendering.py`, `export.py`, `epub.py`, `requirements.txt` and
  `static/css/style.css` synced to `dist-portable/Rextbooks/`; `latex2mathml`
  installed into `dist-portable/Rextbooks/pylibs` from the main `.venv`. Server
  restarted.

## 2026-11-16 (later)

**Fix: "⚠ diagram could not be rendered" — the model invented an arrow token.**
Reported with a generated `sequenceDiagram` whose messages used `A->-B: …`.
Mermaid's parser rejected it ("Trying to inactivate an inactive participant"),
so the reader got the error box and the raw source instead of a diagram.

- **Reproduced against mermaid@10.9.1** (the client's pinned build): in a
  sequenceDiagram `->` and `-->` are tolerated, but `->-` is a parse error; in
  `flowchart` / `graph` / `stateDiagram` / `classDiagram` a bare `->` is a parse
  error while `-->` is valid. `-->`, `-->>`, `-.->`, `==>` are all fine.
- **`rendering.py` now repairs Mermaid source at render time**
  (`_repair_mermaid_source` / `_repair_mermaid_blocks`): `->-` → `->>`,
  `--->` → `-->>` in sequence diagrams, and a bare `->` (with or without
  spaces) → `-->` in flowchart/graph/state/class diagrams. Lines containing
  quotes are skipped so a literal label like `A["a -> b"]` is never rewritten.
  Running it on every render (not just at generation) also heals diagrams
  already saved to books, and covers PDF/EPUB/Pages, which all share
  `render_markdown`. It runs after the text-fence rescue, so a diagram that
  arrived in a ```text fence is repaired too.
- **Prompt guardrail** (`prompts.defaults.json`, `content.defaults.diagram_compact`):
  "Use real Mermaid arrows only: --> in flowcharts, graphs and state diagrams;
  ->> or -->> in sequence diagrams — never ->-, a bare -> in a flowchart, or =>."
- Verified offline (broken sequence repaired; valid sequence untouched;
  flowchart/state arrows fixed; `-.->` and `==>` preserved; quoted labels
  untouched; text-fenced diagram rescued and repaired) and end to end: the
  broken markdown through the live `/render` endpoint comes back as `->>`, and
  that exact served source parses and renders in the browser against
  mermaid@10.9.1.
- `rendering.py` + `prompts.defaults.json` re-synced to
  `dist-portable/Rextbooks/`; server restarted.

## 2026-11-16 (morning)

**Fix: Gemini still wrote ~40% of DeepSeek's length at Length = High.** Reported
with two generated files of the same section: Gemini 763 words total / 618 prose
/ 3 `##` sections vs DeepSeek 1,782 / 1,702 / 7. Not a context-window limit —
the same model produced 2,500-word sections in testing — it simply ignored the
word-count instruction, and run-to-run variance is large.

- **Measured first.** Five prompt variants of the High-length text, each run
  live on both providers. Adding a *structural* quota (number of `##`
  subsections × paragraphs each) moved Gemini from 618 prose words to 1,100-2,600
  depending on wording — Prose-vs-total, tables and code fences excluded.
- **Chosen wording** (`content.defaults.length.high` in the golden file): "write
  at least 1,500 words (1,600-2,000 is the sweet spot) across at least five `##`
  subsections, each 2-4 substantial paragraphs", plus a six-angle coverage list
  (mechanism, deployment, worked example with numbers, failure modes,
  counter-arguments, where it pays off) and "if you covered the ground early, add
  another section instead of stopping".
- **Mechanical floor** (`app.py`): a prompt cannot guarantee this, so a finished
  section under `_LENGTH_MIN_WORDS` (Low 0, Medium 500, High 1,700 prose words)
  is extended once via `shared.length_extension` — the text so far is sent as the
  assistant turn and the model is asked to add new sections at the end, never to
  repeat. `MAX_LENGTH_EXTENSIONS = 1`; the overlap trimmer from the truncation
  path also guards against restated text. Refines are excluded (`min_words=0`),
  since a revision should not silently grow the draft, and list modes
  (outline/subheadings/spark) never get a floor.
- **Measured after**: Gemini 1,886 / 2,563 prose words (both extended from
  ~1,400), DeepSeek 2,026 (no extension) — same band for the first time.
  Offline tests cover: short→one extension, already-long→no extension,
  still-short→stops after one, `min_words=0`→never extends, and the prose
  counter ignoring fences/table rows. UI shows "N words so far — extending to
  the requested length…" while the second round runs; generation at High now
  sometimes makes two API calls (~20-40s).
- `app.py` + `prompts.defaults.json` re-synced to `dist-portable/Rextbooks/`;
  server restarted (102 prompt blocks now, `shared.length_extension` added).

## 2026-11-16 (early)

**Fix: every Gemini diagram came out as `flowchart LR`.** Reported from real
generation: the diagram guidance ordered a left-to-right flow for long chains,
and the model generalised that to *always* using `LR`, so every section got the
same shape regardless of content.

- **First, what the app can actually draw.** The client loads Mermaid **10.9.1**
  (`mermaid-render.js`), so the menu has to be limited to that version. Rendered
  a probe page in a real browser against the same CDN build: **17 types render**
  (flowchart/graph, sequenceDiagram, stateDiagram-v2, classDiagram, erDiagram,
  journey, gantt, pie, quadrantChart, mindmap, timeline, xychart-beta,
  sankey-beta, block-beta, requirementDiagram, gitGraph, C4Context/C4Container)
  and **six do not exist there** (`packet-beta`, `kanban`, `architecture-beta`,
  `radar-beta`, `treemap-beta`, `zenuml`). The rest of the list that prompted
  this (swimlanes, Wardley maps, Ishikawa, Venn, Cynefin, use-case diagrams) are
  not Mermaid diagram types at all. `block-beta` only parsed once each block was
  on its own line — noted in the help text.
- **Golden prompt updated** (`prompts.defaults.json`, the single source of
  truth): `content.defaults.diagram_compact` is now a per-type menu with when to
  use each type, the explicit do-not-use list, a "match Mermaid's exact syntax —
  malformed syntax shows an error box" warning with safe fallbacks, "vary the
  type across subsections", and the same page-size limits as before (10-12
  nodes, short labels, no LaTeX/HTML). `content.rules.diagram.on` gained a
  RULE-level sentence to pick a fitting type rather than defaulting to a
  left-to-right flowchart. `spark.defaults.diagram_size` got the same treatment
  (it had the identical LR bias).
- Verified live on `gemini-3.5-flash-lite` with Diagram frequency = High, three
  different sections: **timeline, sequenceDiagram, pie, flowchart, mindmap** —
  no more all-LR — and all **10 generated diagrams parse and render** in
  Mermaid 10.9.1 (checked in the browser against the exact CDN build the app
  uses). Prompt preview on the running server confirms the new text is live.
- `prompts.defaults.json` re-synced to `dist-portable/Rextbooks/`; server
  restarted (the golden file is read at import).
- Note for later: if a `prompts.local.json` override exists for
  `content.defaults.diagram_compact`, it shadows this golden change until that
  block is reset in Settings → Advanced.

## 2026-11-15 (late night)

**Feature: prompt text moved out of code into a golden JSON file, editable from
Settings → Advanced.** Requested by the user: one authoritative file the app is
"injected" from, a UI to tweak it (e.g. what "Beginner" or "Technical" mean),
and a reset that reverts to the *current* golden text — so a later prompt fix in
the repo also flows into a reset.

- **`prompts.defaults.json`** (repo root, committed) now holds every prompt
  string the app sends: 101 blocks across 8 groups (Shared, Outline &
  subheadings, Content, Tone & depth, Context & task, Spark, Spark modes, Image
  search). Each block carries `group`, `label`, `help`, `tier` and `text`.
  Blocks with `"tier": "careful"` are parsed by the app (the `1. ` list format,
  the `mermaid` fence info string, ```image-search blocks, Spark's `# ` title
  line, the image judge's one-word verdict) and the panel shows ⚠ for those.
- **`prompt_store.py`** loads the golden file at import (missing/invalid =
  clear RuntimeError, since a silent fallback would mean running prompts nobody
  can find) and resolves `get(key)` against **`prompts.local.json`** (sparse
  overrides, gitignored, mtime-cached). `blocks()`, `set_overrides()`,
  `reset()` and `check_placeholders()` back the API; writes are atomic
  (tmp + replace) and UTF-8.
- **Reset semantics are exactly as asked**: an override is *deleted*, never
  snapshotted, so reset always yields whatever `prompts.defaults.json` says at
  that moment. Verified by mutating the golden text in-process and confirming
  the reset prompt picked it up.
- **Refactor with no behaviour change**: `prompts.py`, `sparks.py` and
  `images.py` now only choose and assemble blocks. `SYSTEM_PROMPTS`,
  `_TONE_HINT`, `_DEPTH_HINT`, `OVERRIDE_NOTE`, `CONTINUATION_PROMPT`,
  `DEFAULT_TEMPLATES`, Spark mode text and the image judge/rewrite prompts are
  gone from code; `style_line()`, `override_note()` and `continuation_prompt()`
  read live (overrides apply on the next generation, no restart).
  **Golden test: captured 60 assembled prompt sets before the refactor
  (3 modes × length × diagram/image frequency, no-images/no-diagrams,
  use-images, summary/terminology toggles, every tone and depth, refine,
  standing preference, em-dash ask, context + outline, all 10 Spark modes,
  both image utility prompts) and re-captured after — 60/60 byte-identical.**
  One character differed on the first pass (`("![...](...)")` vs `("![...]")`)
  and was fixed in the golden file; the diff is why the test exists.
- **API**: `GET /api/prompts`, `POST /api/prompts` (sparse updates, warn on
  dropped placeholders, reject unknown keys), `POST /api/prompts/reset`
  (`{keys:[…]}` or `{}` = all), `POST /api/prompts/preview` (assembles the real
  messages for a mode/tone/depth/length).
- **UI**: new *Advanced — prompt text* disclosure in ⚙ Settings
  (`static/js/prompts-panel.js`, markup + CSS): group selector, filter,
  per-block textarea, "edited" badge, ⚠ tier marker, per-block Reset, Save,
  Reset all (confirmed), and a Preview pane that renders the assembled
  system/user messages.
- Verified end to end on an isolated server (temp `BOOKS_DIR`, temp settings
  and temp `prompts.local.json`), driven in a real browser: 101 blocks render,
  groups populate, editing `tone.technical` + Save persists (`modified: true`),
  the Preview output contains the edit, per-block Reset restores the golden text
  and clears the badge, Reset all returns all 101 to unmodified. Placeholder
  validation flags a template that drops `{title}`; unknown keys are rejected
  with 400.
- `.gitignore` now ignores `prompts.local.json`. `CLAUDE.md` gained a "Prompts:
  the words are data" section and the portable-sync list now includes
  `prompt_store.py` + `prompts.defaults.json`; README documents the panel. All
  changed files (including the new golden JSON) synced to
  `dist-portable/Rextbooks/`.

## 2026-11-15 (night)

**Fix: Length = High produced roughly half the content on Gemini that it did on
DeepSeek.** Reported from a real Gemini section ("Nature", 791 words) generated
with Length set to High.

- The Length DEFAULTs were adjectives, not targets: High was just "Go deep —
  cover the subsection thoroughly, with more examples, nuance and supporting
  detail than a brief overview would." DeepSeek reads that as ~2,000 words;
  Gemini's lite models read it as ~800. Nothing in the prompt gave either model
  a number to hit, so the setting was effectively provider-dependent.
- `prompts.py` `_content_system_prompt` now gives concrete ranges — Low
  200-350 words, Medium 600-900, High 1,400-2,000 — plus "use '##' subheadings
  to structure it" and an explicit anti-padding clause ("reach that length with
  real content … never with padding, repetition or restating the same point")
  so the range can't be satisfied by waffle. Still DEFAULTS, so the user's own
  prompt (or the book's standing preference) can override them.
- Measured on the same section prompt with the same model: 3 runs of the new
  High setting produced **2,033 / 1,713 / 1,772 words** with 8-10 `##`
  headings, against 791 before. Wall-clock went from ~10s to ~27-32s per
  section, which is expected for ~2.5x the output.
- `prompts.py` re-synced to `dist-portable/Rextbooks/`; server restarted.

## 2026-11-15 (evening)

**Fix: sections still coming out cut off — Gemini sometimes ends the stream with
no `finish_reason` at all.** Reported after the continuation fix with a
Psychology section saved as 864 chars ending `- Mind: The private, internal`.

- **Diagnosis (not a model-size problem).** Reproduced against the live API with
  the user's own model (`gemini-3.5-flash-lite`) and the same prompt: one of
  three attempts returned **152 chars in 2.7 s with `finish_reason: None`** —
  the server just closed the SSE stream mid-sentence, no error chunk, no
  terminal chunk ("…consciousness, memory, and"). The other two completed
  normally (3.5k / 2.6k chars, `finish_reason: "stop"`). So it is an
  intermittent provider-side abort, not an output-token limit and not the model
  being too small. `meta["truncated"]` was false for it, which is why the
  continuation added earlier never fired — that path only keyed off
  `finish_reason` being "length"/"MAX_TOKENS".
- **`llm.stream_chat` now reports it** as `meta["incomplete"]`: a stream that
  ends without any terminal chunk never reported a finish reason.
- **`app.py` continues on that signal too**, but only when the text visibly
  stopped mid-thought (`_looks_unfinished`): an unterminated ``` fence, or a tail
  that doesn't end on terminal punctuation / a closing bracket / emphasis marker
  / a table row. The shape check is deliberately gated on "no finish_reason at
  all", so a normal reply is never second-guessed, and it only applies to prose
  modes (content, spark) — list modes rely on `truncated` alone, since a
  finished numbered list legitimately ends without punctuation. Status copy now
  distinguishes the two causes ("hit its output limit" vs "the reply stopped
  early"), and `done` still carries `truncated` for the client's warning.
- Verified offline (fake stream with `finish_reason=None` → one continuation,
  stitched text, `done: {truncated: False, continuations: 1}`; shape-check table
  including `- Mind: The private, internal` → unfinished, `**bold**` / `| a | b |`
  / closed fences → finished) and live: a real Gemini stream deliberately closed
  after 309 chars, no finish_reason → continued automatically, final text 7,362
  chars ending on a complete sentence. Four unmodified live runs of the same
  Psychology section completed cleanly at 6–10k chars.
- Also found **two processes listening on port 5000 at once** again (PIDs 10052
  and 20684, different parent shells). Both killed, one clean server started
  (detached, logging to `%TEMP%\rext-server.log`) — a stale server is exactly
  the kind of thing that makes a fix look like it "didn't work", since the
  browser may be talking to the copy with the old code.
- `app.py`, `llm.py` and `static/js/ai-dock.js` re-synced to
  `dist-portable/Rextbooks/`.

## 2026-11-15 (later still)

**Gemini model list in Settings, and a pasted API key now saves itself.**

- **More Gemini models to toggle between** (`config.PROVIDERS["gemini"]`).
  `models` was `["gemini-3.8-flash"]`; it is now
  `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`,
  `gemini-3.1-flash-lite` (newest first, default first). That list is what
  `/api/settings` returns as `models` and what `settings-panel.js` fills the
  `<datalist>` behind the Model field with, so the field is a dropdown of
  suggestions that still accepts any typed name. Requested by the user so they
  can switch models while comparing which one stops timing out.
- **A pasted key is saved without hunting for Save.** The key input had no
  Enter handler at all — the dialog isn't a `<form>`, so pasting a key and
  pressing Enter silently discarded it, and the key only persisted if the user
  then clicked Save. `settings-panel.js` now commits the key on Enter and on
  `change` (leaving the field), and "Test key" saves the key it just tested
  when the test passes. New `savePastedKey()` deliberately does *not* call
  `applyLlmState()`, which would repaint the model field from the server and
  throw away a model name typed but not yet saved; it only clears the key box,
  flips its placeholder to "saved — leave blank to keep", and updates the
  status line. Values under 20 characters are treated as a half-finished paste
  and left alone (Save still accepts anything).
- **Test key works on a saved key**: with the field empty it now tests the key
  already stored for that provider (the server already fell back to it) instead
  of demanding a re-paste.
- Settings copy and README updated to say the key saves on Enter and that the
  Model field is a dropdown of known names.
- Verified on an isolated scratch server (port 5099, temp `BOOKS_DIR` and
  temp `config._SETTINGS_FILE` so the real key was never touched), driven in a
  real browser: the dropdown lists all four Gemini models for both providers'
  fields; pasting a key + Enter gives "API key saved on this machine ✓",
  `/api/settings` reports `keySource: settings`, the temp settings file contains
  it; a later Save of author/model keeps the key; the blur path saves too; and
  reopening the dialog shows "saved — leave blank to keep". Already-correct
  behaviour confirmed beforehand with the test client: unrelated saves
  (author, model) preserve `providerKeys`.
- `config.py`, `static/js/settings-panel.js` and `templates/index.html`
  re-synced to `dist-portable/Rextbooks/`.

## 2026-11-15 (later)

**Fix: Gemini content generation stopping mid-sentence (silent output-limit
cut-off).** Reported by the user: sections generated with Gemini stop
mid-sentence and get saved that way.

- **Diagnosis (reproduced against the real API, on the user's own preset).**
  `gemini-3.5-flash-lite` via the OpenAI-compatible endpoint, no `max_tokens`
  sent, so the provider applies its own output cap — and on that endpoint the
  hidden thinking pass counts against the *same* budget. When it runs out, the
  stream simply ends with `finish_reason: "length"` and the text stops
  **mid-word** (confirmed: `max_tokens=150`/`400` both end `…depending on` /
  `…number of vert`). That matches the evidence in the saved book — the
  section "Deadlock Detection and Recovery — Content" ends `…If the vict`.
  `app.py` already emitted a "hit its output limit" status for that case, but
  `onDone` immediately overwrote it with "Content updated ✓", so the user had
  no way to tell a cut-off from a clean finish, and the partial text was saved
  as if complete.
- **Automatic continuation instead of a cut-off** (`app.py`
  `_stream_chat_response`, `prompts.CONTINUATION_PROMPT`). When a round ends
  truncated, the server now re-asks the model with the text written so far as
  the assistant turn and "continue from exactly where it stopped, output only
  the remainder" as the final user turn, then appends the result. Up to
  `MAX_CONTINUATIONS = 2` rounds; deltas keep streaming so the UI never goes
  quiet. `_trim_continuation_overlap` drops a repeated opening — it checks
  whether the start of the new text already appears in the tail of the old
  (10+ chars), not just exact prefix repeats, because a model resuming inside
  a word restarts at the start of that sentence (`…If the vict` → `If the
  victim is chosen…`); when it does trim, the corrected text is sent as a
  `revise` event so the client's buffer matches. Every truncation is logged to
  stderr with the finish reason and character count.
- **The cut is no longer reported as success.** The `done` event now carries
  `{truncated, continuations}`; `api.js` passes it to `onDone`, and
  `ai-dock.js` shows "Content saved, but the model hit its output limit — the
  ending may be missing…" (error styling) instead of "Content updated ✓" when
  even the continuation rounds ran out. Bulk generate counts and reports
  cut-short blocks in its final summary (`streamOnce` now resolves
  `{text, truncated}`).
- Verified: (1) offline, with a fake `llm.stream_chat` — clean continuation
  stitches correctly, an overlapping continuation is de-duplicated to one
  clean sentence, and a stream that is *always* truncated stops after 2
  continuations with `truncated: true` in the done payload; (2) live against
  Gemini, forcing round 1 to cut at `max_tokens=260` — round 1 reported
  `length`, round 2 finished `stop`, final text 9,964 chars ending on a
  complete sentence with no duplicated content, `done: {truncated: False,
  continuations: 1}`.
- `app.py`, `prompts.py`, `static/js/ai-dock.js` and `static/js/api.js`
  re-synced to `dist-portable/Rextbooks/`.
- Note: sections already saved truncated stay truncated — regenerating (or
  editing) that section is the only way to repair them.

## 2026-11-15

**Fix: Gemini diagrams still landing in ```text fences, and Gemini collapsing
bulleted lists onto one line.** Reported by the user with two screenshots from a
real Gemini section on management functions/roles: a management-cycle diagram
shown as a dark code block of raw `flowchart LR` source, and Mintzberg's roles
rendered as a paragraph of literal asterisks ("...organization: * **Figurehead:**
... * **Leader:** ...").

- **Renderer now recognises a diagram by its body, not just its fence label**
  (`rendering.py`). The previous entry added a prompt RULE forbidding a figure
  inside a ```text / ```plaintext fence; Gemini ignored it and did exactly that
  again, so the prompt alone clearly isn't authoritative. A new
  `_relabel_diagram_fences` pass treats a text/plain/mermaid/mmd/unlabelled
  fence as a diagram when its first non-blank line starts with a Mermaid diagram
  keyword (`flowchart`/`graph` + direction, `sequenceDiagram`, `erDiagram`, …) —
  the same `<figure class="mermaid-figure">` output as a ```mermaid fence, so
  the client, PDF and EPUB paths all pick it up unchanged. A text fence whose
  contents is genuinely literal text is still rendered as a code block.
- **Inline bullet runs reflowed into real lists** (`rendering.py`,
  `_reflow_inline_lists`). Markdown only starts a list item at the beginning of
  a line, so "lead-in: * item * item * item" on one line was rendering as
  literal asterisks. A conservative pre-`md.convert` pass now splits such a line
  into a proper `- ` list. Guardrails so prose can never be mangled: needs 2+
  separators, never matches inside a code fence, skips headings/quotes/tables/
  indented code/lines already starting with a list marker, never treats a lone
  ` *word* ` emphasis marker as a separator, requires each item to be 8+ chars
  and multi-word, and requires the lead-in to end with ":" unless there are 3+
  items.
- **Prompt** (`prompts.py` content RULES, and the same rule in `sparks.py`): a
  new invariant telling the model to write every list as a real Markdown list,
  one item per line, never inline `*` / `•` separated. RULE rather than DEFAULT
  because the renderer's line-based parsing is what depends on it.
- Verified: rendering the exact reported text through `render_markdown` (and
  through the live `/render` endpoint via Flask's test client, with `BOOKS_DIR`
  and `config._SETTINGS_FILE` pointed at temp dirs and the real `./books`
  untouched) produces 2 mermaid figures, 3 `<li>` items, keeps a genuinely
  literal ```text block as a code block, and leaves `*emphasis*` in prose alone.
  No data migration needed — the fix is at render time, so already-saved broken
  sections display correctly after a server restart.
- `rendering.py`, `prompts.py` and `sparks.py` re-synced to `dist-portable/Rextbooks/`.

## 2026-11-14 (later still)

**Fix: mojibake in Gemini-generated text, and Gemini drawing diagrams as ASCII
art.** Reported from a real Gemini section: "product or serviceâ€"" instead of
"product or service—", plus a 2x2 efficiency/effectiveness diagram emitted as
a ```text block made of box-drawing characters.

- **Encoding (real bug, affected DeepSeek too).** `requests` falls back to
  ISO-8859-1 for any `text/*` response that doesn't declare a charset, and
  Gemini's SSE endpoint sends `text/event-stream` with no charset. So
  `iter_lines(decode_unicode=True)` was decoding perfectly good UTF-8 bytes as
  Latin-1: `—` (E2 80 94) became `â€"`, box-drawing characters became runs of
  `â`, and it was written into the book that way. `llm.stream_chat` now sets
  `resp.encoding = "utf-8"` before reading the stream — SSE is UTF-8 by spec,
  so the spec wins over the header. The non-streaming paths were already
  correct (`resp.json()` guesses UTF-8 from the bytes).
  Note: this only fixes *new* generations — sections already saved with
  mojibake keep it until regenerated (mapping is reversible if we want a
  repair pass).
- **Prompt (why Gemini drew ASCII art).** The diagram RULE said "every diagram
  must be a valid Mermaid fenced code block ... with plain-text labels" — the
  word "text" plus a model that likes to draw carried it into a ```text box.
  The rule now names the failure modes explicitly: only ```mermaid, short
  plain-word labels, no LaTeX/HTML, no ASCII art, no box-drawing characters,
  and never a figure inside a ```text / ```plaintext fence. It lives in RULES
  (an invariant the renderer depends on), not DEFAULTS, so it applies to every
  provider and is not user-overridable; DeepSeek already complied, so nothing
  changes for it.
- Verified: a fake SSE response that reproduces requests' Latin-1 fallback
  decodes cleanly (em dash + box-drawing intact, no `â`), the same text parses
  correctly out of the `/api/ai/generate` event stream, and the built system
  prompt contains the new prohibitions. `llm.py` + `prompts.py` re-synced to
  `dist-portable/Rextbooks/`.

---

## 2026-11-14 (later)

**Fix: Gemini preset pointed at retired model names; Test key too impatient.**
Reported from a real run: Test key on `gemini-2.5-flash` returned HTTP 404
("no longer available to new users … use models/gemini-3.8-flash"), and the
same test against `gemini-3.8-flash` died at
`Read timed out (read timeout=30)`.

- `config.PROVIDERS["gemini"]`: default/known model is now
  `gemini-3.8-flash` instead of `2.5-flash` / `2.5-pro` / `2.0-flash`, all of
  which Google has retired for new keys. `utility_model` is now `None` (reuse
  the content model) — the cheap non-thinking Flash models are precisely the
  ones that get retired first, so depending on one was a latent break; the
  hidden-thinking guard now rests on `llm.py`'s visible-output floor instead.
  Comment records that a retired name fails loudly with a suggested
  replacement, so the free-text Model field plus the Test-key message is the
  intended recovery path — no code change needed next time.
- `llm.py`: `_UTILITY_TOKEN_FLOOR` 256 → 1024 (a cap, not a cost), so a
  thinking model's hidden pass cannot starve a 50-token judge call.
  `test_key()` timeout was `(10, 30)` → `(10, 90)` — a cold first call to a
  thinking model legitimately exceeded 30s; a timeout now says so in plain
  language ("didn't answer within 90s … try Test key again, or choose a faster
  model") instead of dumping a `HTTPSConnectionPool` traceback. A 404 from
  Test key also appends "the model name may have been retired … paste that
  into Model".
- `_error_detail()` now unwraps Google's list-wrapped error body
  (`[{"error": {...}}]`) — that's why the raw JSON was being shown verbatim
  rather than just the message.
- README / `.env.example` examples updated; `config.py` + `llm.py` re-synced to
  `dist-portable/Rextbooks/`.
- Verified with a fake transport: new default, no retired names offered,
  utility call uses the content model with `max_tokens` 1024 and no
  `reasoning_effort`, list-wrapped errors parsed, 404 hint present, timeout
  wording correct, and DeepSeek's `reasoning_effort="none"` / `max_tokens=50`
  path untouched.

---

## 2026-11-14

**Selectable generation provider: DeepSeek ⇄ Google Gemini.** The app now talks
to any OpenAI-compatible chat endpoint through one client, and the provider +
model are a Settings choice rather than a hardcoded constant. Both providers
are built in; each keeps its own API key and model, so switching back and forth
never means re-entering anything, and the switch applies on the next request
with no restart.

- `config.py`: replaced `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` / `_ENV_API_KEY`
  with a `PROVIDERS` preset table (label, base URL, default/known models,
  utility model, context budget, env-var names, key placeholder) plus per-call
  accessors — `get_llm_provider()`, `get_llm_model()`, `get_llm_base_url()`,
  `get_api_key(provider)`, `llm_profile()` (server-only, has the key) and
  `llm_status()`/`llm_providers()` (browser-safe: key presence only). The old
  constants were import-time snapshots, which would have made a Settings switch
  require a restart; resolution is now per call, same reasoning as the existing
  `SEND_FILE_MAX_AGE_DEFAULT = 0`. `CONTEXT_CHAR_BUDGET` became
  `get_context_char_budget()`, so the budget is sized per provider.
- Keys are now stored per provider (`providerKeys` in `local_settings.json`).
  The old single `deepseekApiKey` field is still read, and the first write
  migrates it into `providerKeys.deepseek` — existing installs, including the
  portable copy, keep working untouched.
- New `llm.py` is the old `deepseek.py` body made provider-agnostic (base URL,
  model and key come from the active preset). `deepseek.py` is now a three-line
  alias so older imports keep working.
- DeepSeek-specific guardrails, and how they're expressed for Gemini without
  leaking into DeepSeek (all via preset capability flags, never `if provider`):
  - `reasoning_effort="none"` (skips DeepSeek's hidden reasoning pass, which
    otherwise eats a `max_tokens=50` judge call's whole budget and returns an
    empty reply) is only sent to a provider whose preset says it supports it.
    Gemini gets a non-thinking `utility_model` (`gemini-2.0-flash`) for those
    short internal calls instead, plus a 256-token visible-output floor if a
    caller explicitly asks for "none". `images.py` now passes `utility=True` and
    no longer names DeepSeek.
  - New provider-agnostic `finish_reason` handling in `llm.py`: a silent
    truncation (`length` / `MAX_TOKENS`) sets `meta["truncated"]` and the SSE
    wrapper emits a "response may be cut short" status instead of the stream
    just ending; a safety block with no content (`SAFETY`,
    `PROHIBITED_CONTENT`, `content_filter`, …) raises an error naming the
    provider instead of looking like "the model returned nothing". Error
    messages now include the provider's own `error.message`.
- `app.py`: `/health` and `/api/settings` report provider/label/model;
  `/api/settings` accepts `provider` + `model`; `/api/settings/test` tests the
  selected provider/model and explains a missing key by provider name; the SSE
  `start` payload carries provider/label/model.
- Settings dialog: new **Provider** select (applies immediately on change) and
  **Model** field (free text + per-provider suggestions, blank = default), both
  repainted from server state; the key field is relabelled per provider and
  shows "saved — leave blank to keep" like the Pexels field. "Remove key" is
  scoped to the provider on screen. `ai-dock.js` no longer says "Contacting
  DeepSeek".
- Docs: README (provider setup, env vars, file tables) and `.env.example`.
- **Verified** with a redirect-settings scratch instance + fake transport:
  both providers' URL/model/params, no `reasoning_effort` sent to Gemini, no
  utility-model override for DeepSeek, truncation/block/HTTP-error paths,
  per-provider model and key persistence, legacy-key migration, `/health`, and
  the real Settings UI driven in a browser (switch, save, reload, remove).
  Every changed file was then synced into `dist-portable/Rextbooks/`, and the
  embedded interpreter compiles them.

Gotcha hit during verification, worth remembering: the first scratch server
survived `kill_terminal` (the shell dies, the python child doesn't) and kept
holding port 5099, so a second server bound the same port and requests were
answered by the stale one — exactly the "two processes, one port" trap already
noted in CLAUDE.md. Also, bare `python` in a fresh terminal here is *not* the
interpreter that has the app's deps; use `.venv\Scripts\python.exe`.

---

## 2026-10-05

**EPUB validity investigation (no code changes).** User reported that every
EPUB from the app fails to upload to Google Play Books: it processes for a
long time, then fails. Exported their real "Business Management" book (a
read-only copy in a scratch `BOOKS_DIR`, settings file redirected): 20.3 MB
EPUB from 18.2 MB of images (69 files, largest 1.5 MB), 188 files, chapter
XHTML files at most ~65 KB. Size looks very unlikely to be the cause.

Ran W3C EPUBCheck 5.1.0 (with a portable JRE, both downloaded into the
scratchpad only): **0 fatal, 3 errors, 1 warning.**
- **ERROR RSC-005, duplicate IDs.** Each section's Markdown is rendered
  separately, and the `toc` extension slugs headings per section. When a
  chapter's sections are concatenated into one `chN.xhtml`, recurring
  headings collide: `id="summary"` had 59 extra copies and
  `what-this-means-for-you-as-a-strategist` had 22. Only heading IDs collide
  (no footnote IDs in this book). Nav links target node anchors, so
  navigation isn't broken; the file is just invalid. EPUBCheck reports it
  once per affected file, hence 3 errors.
- **WARNING OPF-085, invalid UUID.** `dc:identifier` is
  `urn:uuid:<32 hex chars>`, the raw book id with no dashes, but a `urn:uuid`
  must be 8-4-4-4-12 formatted.

Everything else passed: mimetype first and stored, manifest complete, no
broken references, no remote resources, image media types match the actual
bytes, and all XML is well-formed. A separate cosmetic issue spotted while
reading `epub.py`: `_xmlify`'s `&`-escaping turns any named HTML entity
(e.g. `&nbsp;`, which Chrome's DOM serialisation emits for U+00A0) into
visible literal text. Not present in this book.

Not fixed yet; reported to the user with the fixes (dedupe or prefix
heading IDs per chapter, and format the UUID properly) and a suggested
small-EPUB upload test to tell a file problem apart from a Play Books-side
one.

---

**Custom export colour palettes.** A dashed "+ New palette" tile now follows
the last palette in the Export dialog. It opens an inline editor: a name
field, one row per palette role (Background, Body text, Headings, Accent,
Muted — each with a short description of what it colours in the export), a
native colour picker plus a synced hex field per role, and a live mini-page
preview. The editor starts from whichever palette is currently selected.
Saving selects the new palette. Custom palettes get a red ✕ at their
top-right corner on hover (always visible on touch screens, where there's no
hover); built-ins never do. Deleting asks for confirmation, and if the
deleted palette was selected the book falls back to "Popular". Escape closes
the editor first, then the dialog.

- **Storage**: global, in `local_settings.json` under `customPalettes`
  (`config.get_custom_palettes` / `save_custom_palette` /
  `delete_custom_palette`), not per book, so a palette made once is
  available to every book. Keys are `custom-<10 hex>` so they can never
  collide with a built-in.
- **One integration point**: `palettes.get()` now resolves custom keys, and
  every export path already goes through it (PDF via the `/preview` render,
  EPUB, running-header and page-number stamping). No export code changed.
  An unknown or deleted custom key falls back to the default palette rather
  than erroring.
- **Validation** (`palettes._clean`): every role must be strict `#RRGGBB`.
  This is load-bearing: the values are interpolated straight into export CSS,
  and the exports append alpha suffixes like `{accent}22`, which a 3-digit
  hex would turn into invalid CSS. Labels are stripped and capped at 40
  chars; max 50 custom palettes. Stored palettes are re-validated on every
  read too, since `local_settings.json` is a hand-editable file.
- **XSS**: the old swatch renderer built tiles with `innerHTML` including
  `p.label`, harmless for hard-coded names but an injection hole once names
  are user-typed. Tiles are now built with `createElement`/`textContent`.
- **Ordering**: Flask sorts JSON object keys by default, so custom palettes
  would have landed alphabetically mid-grid. The API marks them
  `custom: true` with a `created` timestamp, and the client orders built-ins
  first, then customs oldest-first, then "+".
- Palettes are re-fetched each time the dialog opens, so one created in
  another tab shows up.
- **API**: `GET /api/palettes` (built-ins + customs), `POST /api/palettes`
  (201, or 400 with a readable reason), `DELETE /api/palettes/<key>` (400 for
  a built-in, 404 for unknown).

Verified on an isolated server (scratch `BOOKS_DIR`, and
`config._SETTINGS_FILE` redirected to a scratch file, because palettes live
in the settings file, not the books dir; the real `local_settings.json` hash
was confirmed unchanged afterwards). 17/17 API checks passed, including
rejecting a CSS-injection attempt, 3-digit hex, missing roles, a blank name,
and deletion of a built-in, plus custom colours (and alpha-suffixed variants)
appearing in the real export HTML. Headless-Chrome UI test: "+" is always
last; built-ins have no ✕; editor rows prefill from the selected palette;
hex ↔ picker ↔ preview stay in sync; invalid hex is flagged and reverts on
blur; Escape closes only the editor; a name containing `<b>` renders as
literal text; the ✕ is invisible until hover; two customs stay in creation
order; deleting the selected one falls back to Popular; deletion persists.
Screenshots checked in both dark and light themes. One fix came out of that:
role descriptions were truncated with an ellipsis, so they now wrap. A real
PDF export with a custom dark palette and page numbers rendered correctly
(3 pages, 4 outline entries, cover in the custom colours).

Synced all 8 changed files to `dist-portable/Rextbooks/` (hash-verified).
The production server on port 5000 was the user's own `python app.py`
terminal process, so it was left for the user to restart rather than killed.

---

## 2026-10-02

**Portable build verification (no code changes).** User asked to "recompile"
`dist-portable/Rextbooks/` and confirm it's current. Hash-compared every
root `.py` file plus everything under `static/js`, `static/css`, and
`templates/` against the main tree (byte-for-byte, via `hashlib.sha256` —
not a line-count/timestamp check) — all already identical, since this
session's fixes (the image-rendering saga's `ai-dock.js`/`block.js` changes,
and `app.py`/`images.py`/`prompts.py` for the hallucinated-image-tag fix)
were copied over incrementally as they were made. Confirmed `pylibs`
satisfies every `requirements.txt` pin (Flask 3.1.3, Markdown 3.10.3,
requests 2.34.2, python-dotenv 1.2.3, Pillow 12.3.0, pypdf 6.19.0, reportlab
5.0.1 — all well above the stated minimums). Then actually ran the portable
build's own embedded interpreter (`dist-portable/Rextbooks/python/python.exe`,
not the project's dev `.venv`) against a scratch `BOOKS_DIR`, and fetched
`/`, `/api/books`, and the two most-recently-fixed static files over real
HTTP — confirmed `block.js` serves the retry-before-placeholder logic and
`ai-dock.js` serves the `waitForBlockImages` fix, not stale copies. Portable
build is confirmed current; nothing needed copying this time.

(Mid-task note: the Bash tool's shell lost its PATH to Git-for-Windows'
Unix tools partway through this check — `diff`, `grep`, `mkdir`, `curl`,
`ls`, `sleep` all started failing with "command not found" for no apparent
reason, which **silently produced false-positive "DIFFERS" results** in an
early `diff`-based comparison loop, since `! diff -q ... > /dev/null 2>&1`
reports true both when files differ *and* when `diff` itself fails to run.
Caught by cross-checking with a `hashlib`-based Python comparison instead,
which gave a clean, trustworthy answer. Switched to the PowerShell tool for
the rest of the task once Bash's coreutils access proved unreliable —
worth remembering: an empty-diff result from a shell loop like that isn't
trustworthy on its own if the shell's own tool availability hasn't been
verified first.)

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
