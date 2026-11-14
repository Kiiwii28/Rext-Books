// Export modal: choose format (PDF / EPUB / Markdown / JSON), a colour
// palette, and which parts of the book to actually include, then download.

import * as store from "./store.js";
import {
  getPalettes, createPalette, deletePalette, getHealth, getSettings, saveSettings, exportHref, printHref,
} from "./api.js";

const TYPE_ICON = { heading: "H", subheading: "S", section: "¶" };
const DEFAULT_PALETTE = "popular";

// The five document roles a palette colours — same keys palettes.py uses.
const ROLES = [
  { key: "bg", label: "Background", hint: "The page colour behind everything" },
  { key: "text", label: "Body text", hint: "Paragraphs, lists and table text" },
  { key: "heading", label: "Headings", hint: "Chapter and section titles, bold text" },
  { key: "accent", label: "Accent", hint: "Links, cover band, heading rules, table headers" },
  { key: "muted", label: "Muted", hint: "Captions, borders and secondary text" },
];
const HEX = /^#?([0-9a-f]{6})$/i;

let els = {};
let palettes = {};
let fmt = "pdf";
let pdfNative = true;
let included = new Set();   // node ids currently included in the export
let collapsed = new Set();  // node ids whose children are currently hidden in the tree
let contentOpen = false;    // whether the "Content to include" section itself is expanded
let advOpen = false;        // "Advanced" disclosure (author/diagrams-as-images/lite/numbering/page numbers)
let authorLoaded = "";      // the author value as fetched, to know whether the field was actually edited
let draft = {};             // colours being edited in the new-palette editor, keyed by role
let roleInputs = {};        // role -> { color, hex } inputs in the editor

export async function mountExport(refs) {
  els = refs;

  try { pdfNative = (await getHealth()).pdf !== false; } catch { pdfNative = false; }
  buildRoleRows();

  els.openBtn.addEventListener("click", open);
  els.closeBtn.addEventListener("click", close);
  els.cancelBtn.addEventListener("click", close);
  els.backdrop.addEventListener("click", (e) => { if (e.target === els.backdrop) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || els.backdrop.hidden) return;
    // Escape backs out of the palette editor first, then the dialog.
    if (!els.peEditor.hidden) closeEditor();
    else close();
  });
  els.peCancel.addEventListener("click", closeEditor);
  els.peSave.addEventListener("click", saveDraft);
  els.peName.addEventListener("keydown", (e) => { if (e.key === "Enter") saveDraft(); });

  els.formatSeg.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      fmt = b.dataset.fmt;
      els.formatSeg.querySelectorAll(".seg-btn").forEach((x) => x.classList.toggle("active", x === b));
      syncFormat();
    });
  });

  els.selectAllBtn.addEventListener("click", () => {
    included = new Set(allIds(store.getBook()?.nodes || []));
    renderContentTree();
  });
  els.selectNoneBtn.addEventListener("click", () => {
    included = new Set();
    renderContentTree();
  });

  els.contentToggle.addEventListener("click", () => setContentOpen(!contentOpen));
  els.advToggle.addEventListener("click", () => setAdvOpen(!advOpen));

  els.goBtn.addEventListener("click", go);
}

function setAdvOpen(open) {
  advOpen = open;
  els.advBody.hidden = !open;
  els.advToggle.setAttribute("aria-expanded", String(open));
  els.advToggle.classList.toggle("is-open", open);
}

// ---- content-to-include tree (cascading select, like the context picker) --

function allIds(nodes, acc = []) {
  for (const n of nodes) { acc.push(n.id); allIds(n.children || [], acc); }
  return acc;
}
function subtreeIds(node, acc = []) {
  acc.push(node.id);
  for (const c of node.children || []) subtreeIds(c, acc);
  return acc;
}
function subtreeCounts(node) {
  let total = 0, inc = 0;
  (function rec(n) {
    total++;
    if (included.has(n.id)) inc++;
    for (const c of n.children || []) rec(c);
  })(node);
  return { total, inc };
}

function toggleInclude(node) {
  const { total, inc } = subtreeCounts(node);
  const turnOn = inc < total;   // indeterminate or fully-off -> select the whole subtree; fully-on -> clear it
  for (const id of subtreeIds(node)) turnOn ? included.add(id) : included.delete(id);
  renderContentTree();
}

function renderContentTree() {
  const book = store.getBook();
  els.contentTree.innerHTML = "";
  if (book) els.contentTree.append(buildList(book.nodes || []));

  const all = book ? allIds(book.nodes || []) : [];
  const total = all.length;
  const n = all.filter((id) => included.has(id)).length;
  const summary = total === 0 ? ""
    : n === total ? `All ${total} blocks included.`
    : n === 0 ? "Nothing selected — pick at least one block to export."
    : `${n} of ${total} blocks included.`;
  els.contentHint.textContent = summary;
  els.contentSummary.textContent = total === 0 ? "" : n === total ? `${total}/${total}` : `${n}/${total}`;
  els.goBtn.disabled = total > 0 && n === 0;
}

/** Collapse every node that has children — shown by default so the tree opens
 *  tidy (just top-level headings) and the user drills down as they like. */
function collapseAll(nodes) {
  for (const n of nodes) {
    if ((n.children || []).length) { collapsed.add(n.id); collapseAll(n.children); }
  }
}

function setContentOpen(open) {
  contentOpen = open;
  els.contentBody.hidden = !open;
  els.contentToggle.setAttribute("aria-expanded", String(open));
  els.contentToggle.classList.toggle("is-open", open);
}

function buildList(nodes) {
  const ul = document.createElement("ul");
  ul.className = "ect-list";
  for (const n of nodes) {
    const { total, inc } = subtreeCounts(n);
    const hasChildren = (n.children || []).length > 0;
    const li = document.createElement("li");
    li.className = "ect-item" + (hasChildren && collapsed.has(n.id) ? " ect-collapsed" : "");
    const row = document.createElement("label");
    row.className = "ect-row" + (inc === total ? " ect-checked" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = inc === total;
    cb.indeterminate = inc > 0 && inc < total;
    cb.addEventListener("change", () => toggleInclude(n));
    const chevron = document.createElement("button");
    chevron.type = "button";
    chevron.className = "ect-chevron" + (hasChildren ? "" : " is-hidden");
    chevron.textContent = "▸";
    chevron.title = collapsed.has(n.id) ? "Expand" : "Collapse";
    chevron.tabIndex = hasChildren ? 0 : -1;
    chevron.addEventListener("click", (e) => {
      // Stop the click reaching the <label> row, which would otherwise also
      // toggle the checkbox (the label's default action for any inner click).
      e.preventDefault();
      e.stopPropagation();
      if (!hasChildren) return;
      collapsed.has(n.id) ? collapsed.delete(n.id) : collapsed.add(n.id);
      renderContentTree();
    });
    const kind = document.createElement("span");
    kind.className = "ect-kind";
    kind.textContent = TYPE_ICON[n.type] || "·";
    const title = document.createElement("span");
    title.className = "ect-title";
    title.textContent = n.type === "section" ? "Content" : (n.title || "(untitled)");
    row.append(cb, chevron, kind, title);
    li.append(row);
    if (hasChildren) li.append(buildList(n.children));
    ul.append(li);
  }
  return ul;
}

/** Collect ids of fully-excluded subtrees only. The export backend prunes a
 *  node's *entire* subtree when its id is excluded, so a partially-included
 *  ancestor (indeterminate checkbox) must never be added here — only nodes
 *  with zero included descendants are, and recursion stops there since the
 *  backend already drops everything underneath. */
function collectExcluded(nodes, acc) {
  for (const n of nodes) {
    const { inc } = subtreeCounts(n);
    if (inc === 0) acc.push(n.id);
    else collectExcluded(n.children || [], acc);
  }
  return acc;
}

/** Ids to leave OUT of the export, or null if everything's included
 *  (the common case — keeps the export URL unchanged by default). */
function excludedIds() {
  const book = store.getBook();
  if (!book) return null;
  const ex = collectExcluded(book.nodes || [], []);
  return ex.length ? ex : null;
}

async function loadPalettes() {
  try { palettes = await getPalettes(); } catch { palettes = {}; }
  renderSwatches();
}

/** Built-ins in the order the server sends them, then custom palettes
 *  oldest-first — so a new palette always appears last, right before "+".
 *  (Flask sorts JSON keys, so server order alone would interleave them.) */
function orderedPalettes() {
  const entries = Object.entries(palettes);
  const builtIn = entries.filter(([, p]) => !p.custom);
  const custom = entries.filter(([, p]) => p.custom)
    .sort(([, a], [, b]) => (a.created || 0) - (b.created || 0));
  return [...builtIn, ...custom];
}

function renderSwatches() {
  els.grid.innerHTML = "";
  for (const [key, p] of orderedPalettes()) {
    // A wrapper rather than the button itself carries the delete control —
    // a <button> can't legally contain another <button>.
    const wrap = document.createElement("div");
    wrap.className = "swatch-wrap" + (p.custom ? " is-custom" : "");

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "swatch";
    btn.dataset.key = key;
    btn.title = p.label;
    const strip = document.createElement("span");
    strip.className = "sw-strip";
    for (const c of [p.bg, p.heading, p.accent, p.text]) {
      const i = document.createElement("i");
      i.style.background = c;
      strip.append(i);
    }
    const name = document.createElement("span");
    name.className = "sw-name";
    name.textContent = p.label;   // user-typed for custom palettes — never innerHTML
    btn.append(strip, name);
    btn.addEventListener("click", () => {
      store.setSetting("palette", key);
      markSelected();
    });
    wrap.append(btn);

    if (p.custom) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "sw-del";
      del.title = `Delete “${p.label}”`;
      del.setAttribute("aria-label", `Delete palette ${p.label}`);
      del.textContent = "✕";
      del.addEventListener("click", () => removePalette(key, p.label));
      wrap.append(del);
    }
    els.grid.append(wrap);
  }

  const add = document.createElement("button");
  add.type = "button";
  add.className = "swatch swatch-add";
  add.title = "Create your own palette";
  add.setAttribute("aria-label", "Create a custom palette");
  add.innerHTML = `<span class="sw-add-plus">+</span><span class="sw-name">New palette</span>`;
  add.addEventListener("click", openEditor);
  els.grid.append(add);

  markSelected();
}

async function removePalette(key, label) {
  if (!confirm(`Delete the palette “${label}”? This can't be undone.`)) return;
  try {
    await deletePalette(key);
  } catch (err) {
    alert(`Couldn't delete the palette: ${err.message}`);
    return;
  }
  delete palettes[key];
  if (store.getSetting("palette") === key) store.setSetting("palette", DEFAULT_PALETTE);
  renderSwatches();
}

// ---- new-palette editor ---------------------------------------------------

function buildRoleRows() {
  els.peRoles.innerHTML = "";
  for (const role of ROLES) {
    const row = document.createElement("div");
    row.className = "pe-role";

    const color = document.createElement("input");
    color.type = "color";
    color.id = `pe-color-${role.key}`;
    color.className = "pe-color";

    const text = document.createElement("label");
    text.className = "pe-role-text";
    text.htmlFor = color.id;
    const lbl = document.createElement("span");
    lbl.className = "pe-role-label";
    lbl.textContent = role.label;
    const hint = document.createElement("span");
    hint.className = "pe-role-hint";
    hint.textContent = role.hint;
    text.append(lbl, hint);

    const hex = document.createElement("input");
    hex.type = "text";
    hex.className = "pe-hex";
    hex.maxLength = 7;
    hex.spellcheck = false;
    hex.autocomplete = "off";
    hex.setAttribute("aria-label", `${role.label} hex colour`);

    color.addEventListener("input", () => setRole(role.key, color.value));
    hex.addEventListener("input", () => {
      const m = HEX.exec(hex.value.trim());
      hex.classList.toggle("is-invalid", !m);
      if (m) setRole(role.key, `#${m[1]}`, { fromHex: true });
    });
    // A half-typed/invalid hex snaps back to the last good colour on blur.
    hex.addEventListener("blur", () => {
      hex.value = draft[role.key];
      hex.classList.remove("is-invalid");
    });

    row.append(color, text, hex);
    els.peRoles.append(row);
    roleInputs[role.key] = { color, hex };
  }
}

function setRole(key, value, { fromHex = false } = {}) {
  value = value.toUpperCase();
  draft[key] = value;
  const { color, hex } = roleInputs[key];
  color.value = value.toLowerCase();
  if (!fromHex) hex.value = value;
  els.pePreview.style.setProperty(`--pe-${key}`, value);
}

function openEditor() {
  // Start from whichever palette is currently selected — tweaking one is
  // usually quicker than building from scratch.
  const base = palettes[store.getSetting("palette")] || palettes[DEFAULT_PALETTE] || {};
  for (const role of ROLES) setRole(role.key, base[role.key] || "#000000");
  els.peName.value = "";
  els.peError.hidden = true;
  els.peEditor.hidden = false;
  els.grid.querySelector(".swatch-add")?.classList.add("is-active");
  els.peName.focus();
}

function closeEditor() {
  els.peEditor.hidden = true;
  els.grid.querySelector(".swatch-add")?.classList.remove("is-active");
}

async function saveDraft() {
  const customCount = Object.values(palettes).filter((p) => p.custom).length;
  const label = els.peName.value.trim() || `Custom ${customCount + 1}`;
  els.peSave.disabled = true;
  try {
    const { key, palette } = await createPalette({ label, ...draft });
    palettes[key] = palette;
    store.setSetting("palette", key);
    closeEditor();
    renderSwatches();
  } catch (err) {
    els.peError.textContent = err.message;
    els.peError.hidden = false;
  } finally {
    els.peSave.disabled = false;
  }
}

function markSelected() {
  const cur = store.getSetting("palette");
  els.grid.querySelectorAll(".swatch").forEach((s) => s.classList.toggle("selected", s.dataset.key === cur));
}

function syncFormat() {
  els.paletteField.hidden = fmt !== "pdf" && fmt !== "epub";
  // Author appears on the front page/byline of everything except the raw
  // JSON dump (nothing to render there).
  els.authorField.hidden = fmt === "json";
  els.diagramsImagesField.hidden = fmt !== "pages";
  // Lite only actually compresses anything server-side for a native PDF
  // render, an EPUB, or a Pages export — the no-native-renderer PDF
  // fallback just opens the browser's own print dialog, nothing to shrink.
  els.liteField.hidden = !(fmt === "epub" || fmt === "pages" || (fmt === "pdf" && pdfNative));
  els.pagesNumberField.hidden = fmt !== "pages";
  els.pageNumbersField.hidden = !(fmt === "pdf" && pdfNative);
  if (fmt === "pdf") {
    els.note.textContent = pdfNative
      ? "A styled PDF will download — cover page, contents, working links, and a bookmarks/navigation pane matching your headings."
      : "No PDF renderer on the server, so this opens a print-ready page — choose “Save as PDF” (turn on “Background graphics”).";
  } else if (fmt === "epub") {
    els.note.textContent = "An .epub file for e-readers — same look as the PDF, with a working table of contents." +
      (pdfNative ? "" : " (No headless browser on the server, so any Mermaid diagrams stay as plain text.)");
  } else if (fmt === "md") {
    els.note.textContent = "A .md file will download. Local images use absolute URLs to this server.";
  } else if (fmt === "pages") {
    els.note.textContent = "A .zip of Markdown notes mirroring the outline — one folder per heading, "
      + "Obsidian-style [[wikilinks]] between notes, and images in one shared assets/ folder. "
      + "Extract it straight into an Obsidian vault (or anywhere else that understands wikilinks).";
  } else if (fmt === "json") {
    els.note.textContent = "The raw book file — re-import it with the Import button to restore this book.";
  }
}

async function open() {
  const book = store.getBook();
  if (!book) return;
  included = new Set(allIds(book.nodes || []));
  collapsed = new Set();
  collapseAll(book.nodes || []);
  setContentOpen(false);
  setAdvOpen(false);
  closeEditor();
  renderContentTree();
  await loadPalettes();
  els.liteCheckbox.checked = false;   // opt-in each time — default export unless asked otherwise
  els.pagesNumberCheckbox.checked = false;
  els.diagramsImagesCheckbox.checked = false;
  els.pageNumbersCheckbox.checked = false;
  try {
    authorLoaded = (await getSettings()).author || "";
  } catch {
    authorLoaded = "";
  }
  els.authorInput.value = authorLoaded;
  syncFormat();
  els.backdrop.hidden = false;
}
function close() { els.backdrop.hidden = true; }

async function go() {
  const book = store.getBook();
  if (!book) return;
  const author = els.authorInput.value.trim();
  if (author !== authorLoaded) {
    try { await saveSettings({ author }); } catch { /* export still proceeds either way */ }
  }
  const palette = store.getSetting("palette");
  const exclude = excludedIds();
  const opts = {
    lite: els.liteCheckbox.checked,
    numbered: els.pagesNumberCheckbox.checked,
    diagramsAsImages: els.diagramsImagesCheckbox.checked,
    pageNumbers: els.pageNumbersCheckbox.checked,
  };
  if (fmt === "md" || fmt === "json" || fmt === "epub" || fmt === "pages") {
    window.location.href = exportHref(book.id, fmt, palette, exclude, opts);
  } else if (pdfNative) {
    window.location.href = exportHref(book.id, "pdf", palette, exclude, opts);
  } else {
    window.open(printHref(book.id, palette, exclude), "_blank", "noopener");
  }
  close();
}
