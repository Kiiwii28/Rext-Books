// Export modal: choose format (PDF / EPUB / Markdown / JSON), a colour
// palette, and which parts of the book to actually include, then download.

import * as store from "./store.js";
import { getPalettes, getHealth, exportHref, printHref } from "./api.js";

const TYPE_ICON = { heading: "H", subheading: "S", section: "¶" };

let els = {};
let palettes = {};
let fmt = "pdf";
let pdfNative = true;
let included = new Set();   // node ids currently included in the export
let collapsed = new Set();  // node ids whose children are currently hidden in the tree
let contentOpen = false;    // whether the "Content to include" section itself is expanded

export async function mountExport(refs) {
  els = refs;

  try { pdfNative = (await getHealth()).pdf !== false; } catch { pdfNative = false; }
  try { palettes = await getPalettes(); } catch { palettes = {}; }
  renderSwatches();

  els.openBtn.addEventListener("click", open);
  els.closeBtn.addEventListener("click", close);
  els.cancelBtn.addEventListener("click", close);
  els.backdrop.addEventListener("click", (e) => { if (e.target === els.backdrop) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.backdrop.hidden) close(); });

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

  els.goBtn.addEventListener("click", go);
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

function renderSwatches() {
  els.grid.innerHTML = "";
  for (const [key, p] of Object.entries(palettes)) {
    const btn = document.createElement("button");
    btn.className = "swatch";
    btn.dataset.key = key;
    btn.title = p.label;
    btn.innerHTML =
      `<span class="sw-strip">` +
      [p.bg, p.heading, p.accent, p.text].map((c) => `<i style="background:${c}"></i>`).join("") +
      `</span><span class="sw-name">${p.label}</span>`;
    btn.addEventListener("click", () => {
      store.setSetting("palette", key);
      markSelected();
    });
    els.grid.append(btn);
  }
}

function markSelected() {
  const cur = store.getSetting("palette");
  els.grid.querySelectorAll(".swatch").forEach((s) => s.classList.toggle("selected", s.dataset.key === cur));
}

function syncFormat() {
  els.paletteField.hidden = fmt !== "pdf" && fmt !== "epub";
  // Lite only actually compresses anything server-side for a native PDF
  // render or an EPUB — the no-native-renderer PDF fallback just opens the
  // browser's own print dialog, nothing here to shrink.
  els.liteField.hidden = !(fmt === "epub" || (fmt === "pdf" && pdfNative));
  if (fmt === "pdf") {
    els.note.textContent = pdfNative
      ? "A styled PDF will download — cover page, contents, working links, and a bookmarks/navigation pane matching your headings."
      : "No PDF renderer on the server, so this opens a print-ready page — choose “Save as PDF” (turn on “Background graphics”).";
  } else if (fmt === "epub") {
    els.note.textContent = "An .epub file for e-readers — same look as the PDF, with a working table of contents." +
      (pdfNative ? "" : " (No headless browser on the server, so any Mermaid diagrams stay as plain text.)");
  } else if (fmt === "md") {
    els.note.textContent = "A .md file will download. Local images use absolute URLs to this server.";
  } else {
    els.note.textContent = "The raw book file — re-import it with the Import button to restore this book.";
  }
}

function open() {
  const book = store.getBook();
  if (!book) return;
  included = new Set(allIds(book.nodes || []));
  collapsed = new Set();
  collapseAll(book.nodes || []);
  setContentOpen(false);
  renderContentTree();
  markSelected();
  els.liteCheckbox.checked = false;   // opt-in each time — default export unless asked otherwise
  syncFormat();
  els.backdrop.hidden = false;
}
function close() { els.backdrop.hidden = true; }

function go() {
  const book = store.getBook();
  if (!book) return;
  const palette = store.getSetting("palette");
  const exclude = excludedIds();
  const lite = els.liteCheckbox.checked;
  if (fmt === "md" || fmt === "json" || fmt === "epub") {
    window.location.href = exportHref(book.id, fmt, palette, exclude, lite);
  } else if (pdfNative) {
    window.location.href = exportHref(book.id, "pdf", palette, exclude, lite);
  } else {
    window.open(printHref(book.id, palette, exclude), "_blank", "noopener");
  }
  close();
}
