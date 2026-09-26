// Bootstrap: load a book, wire the panels, keep the UI in sync with the store.

import * as store from "./store.js";
import * as api from "./api.js";
import { mountTree, renderTree } from "./tree.js";
import { mountDock, updateDock } from "./ai-dock.js";
import { mountExport } from "./export-panel.js";
import { mountSpark, updateSpark } from "./spark-panel.js";
import { mountPaneResizer } from "./resize.js";
import { mountSettings, openIfNoKey } from "./settings-panel.js";
import { mountTour } from "./tour.js";
import {
  mountBookPicker, setBooks as setPickerBooks, setValue as setPickerValue,
  updateCurrentTitle,
} from "./book-picker.js";

const $ = (id) => document.getElementById(id);
const LAST_BOOK = "rextbooks:lastBook";

const els = {
  tree: $("tree"),
  emptyState: $("empty-state"),
  newBtn: $("btn-new-book"),
  deleteBtn: $("btn-delete-book"),
  saveState: $("save-state"),
  expandAll: $("btn-expand-all"),
  collapseAll: $("btn-collapse-all"),
  startForm: $("start-form"),
  startTopic: $("start-topic"),
};

const dockEls = {
  modeChip: $("ai-mode-chip"),
  targetPath: $("ai-target-path"),
  advToggle: $("ai-advanced-toggle"),
  advBody: $("ai-advanced-body"),
  oaBadge: $("ai-overarching-badge"),
  oaInput: $("ai-overarching"),
  oaClear: $("ai-overarching-clear"),
  countRow: $("ai-count-row"),
  count: $("ai-count"),
  tones: $("ai-tones"),
  depths: $("ai-depths"),
  refineRow: $("ai-refine-row"),
  contentOptions: $("ai-content-options"),
  diagramFreq: $("ai-diagram-freq"),
  length: $("ai-length"),
  summaryRow: $("ai-summary-row"),
  summarySection: $("ai-summary-section"),
  termsRow: $("ai-terms-row"),
  terminologySection: $("ai-terms-section"),
  imagesBlock: $("ai-images-block"),
  imagesRow: $("ai-images-row"),
  useImages: $("ai-use-images"),
  imageOptions: $("ai-image-options"),
  imageFreq: $("ai-image-freq"),
  imageSources: $("ai-image-sources"),
  srcWikimedia: $("ai-src-wikimedia"),
  srcPexels: $("ai-src-pexels"),
  subModeRow: $("ai-submode-row"),
  addContextBtn: $("btn-add-context"),
  contextAllBtn: $("btn-context-all"),
  sparkBtn: $("btn-spark"),
  bulkBtn: $("btn-bulk"),
  contextChips: $("ai-context-chips"),
  bulkQueue: $("ai-bulk-queue"),
  bulkChips: $("ai-bulk-chips"),
  bulkClearBtn: $("btn-bulk-clear"),
  bulkDeleteBtn: $("btn-bulk-delete"),
  prompt: $("ai-prompt"),
  generateBtn: $("btn-generate"),
  stopBtn: $("btn-stop"),
  resetBtn: $("btn-reset-prompt"),
  status: $("ai-status"),
  stream: $("ai-stream"),
};

const exportEls = {
  openBtn: $("btn-export"),
  backdrop: $("export-modal"),
  closeBtn: $("export-close"),
  cancelBtn: $("export-cancel"),
  goBtn: $("export-go"),
  formatSeg: $("export-format"),
  paletteField: $("palette-field"),
  grid: $("palette-grid"),
  advToggle: $("export-advanced-toggle"),
  advBody: $("export-advanced-body"),
  authorField: $("author-field"),
  authorInput: $("export-author-input"),
  diagramsImagesField: $("diagrams-images-field"),
  diagramsImagesCheckbox: $("export-diagrams-images"),
  liteField: $("lite-field"),
  liteCheckbox: $("export-lite"),
  pagesNumberField: $("pages-number-field"),
  pagesNumberCheckbox: $("export-pages-number"),
  pageNumbersField: $("page-numbers-field"),
  pageNumbersCheckbox: $("export-page-numbers"),
  note: $("export-note"),
  contentToggle: $("export-content-toggle"),
  contentBody: $("export-content-body"),
  contentSummary: $("export-content-summary"),
  contentTree: $("export-content-tree"),
  contentHint: $("export-content-hint"),
  selectAllBtn: $("export-select-all"),
  selectNoneBtn: $("export-select-none"),
};

const sparkEls = {
  backdrop: $("spark-modal"),
  closeBtn: $("spark-close"),
  cancelBtn: $("spark-cancel"),
  resetBtn: $("spark-reset"),
  goBtn: $("spark-go"),
  stopBtn: $("spark-stop"),
  sources: $("spark-sources"),
  modes: $("spark-modes"),
  prompt: $("spark-prompt"),
  status: $("spark-status"),
  stream: $("spark-stream"),
};

const settingsEls = {
  openBtn: $("btn-settings"),
  backdrop: $("settings-modal"),
  closeBtn: $("settings-close"),
  status: $("settings-status"),
  keyInput: $("settings-key-input"),
  toggleBtn: $("settings-key-toggle"),
  authorInput: $("settings-author-input"),
  titleField: $("settings-title-field"),
  titleInput: $("settings-title-input"),
  blurbInput: $("settings-blurb-input"),
  blurbReset: $("settings-blurb-reset"),
  pexelsInput: $("settings-pexels-input"),
  pexelsToggle: $("settings-pexels-toggle"),
  pexelsClear: $("settings-pexels-clear"),
  pexelsUsage: $("settings-pexels-usage"),
  inline: $("settings-inline"),
  modelLine: $("settings-model"),
  testBtn: $("settings-test"),
  saveBtn: $("settings-save"),
  removeBtn: $("settings-remove"),
};

mountTree(els.tree, { onSelect: (id) => store.select(id) });
mountDock(dockEls);
mountExport(exportEls);
mountSpark(sparkEls);
mountPaneResizer();
mountSettings(settingsEls);
mountTour($("btn-tutorial"));

els.tree.addEventListener("click", (e) => {
  if (e.target === els.tree && !store.getPickMode()) store.select(null);
});

const pickBanner = $("pick-banner");
const pickBannerText = $("pick-banner-text");
$("pick-banner-done").addEventListener("click", () => store.endPick());
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && store.getPickMode()) store.endPick();
});

function paintPickBanner(state) {
  const pm = state.pickMode;
  pickBanner.hidden = !pm;
  pickBanner.classList.toggle("spark", pm === "spark");
  pickBanner.classList.toggle("bulk", pm === "bulk");
  if (!pm) return;
  if (pm === "spark") {
    const n = state.sparkIds.length;
    pickBannerText.textContent = n < 2
      ? `Pick ${2 - n} more block${2 - n > 1 ? "s" : ""} to Spark`
      : "Two blocks picked — opening Spark…";
  } else if (pm === "bulk") {
    const n = state.bulkIds.length;
    pickBannerText.textContent = n < 1
      ? "Pick sibling blocks to generate in one batch"
      : `${n} block${n > 1 ? "s" : ""} picked — add more siblings, or ＋ Add context, then hit Generate`;
  } else {
    const t = state.contextTarget ? store.findNode(state.contextTarget)?.node : null;
    const name = t ? `"${t.title || "(untitled)"}"` : state.bulkIds.length ? "the bulk queue" : "the outline";
    const n = state.contextIds.length;
    pickBannerText.textContent =
      `Pick blocks for context (a parent selects its children) for ${name}` +
      (n ? ` — ${n} selected` : "");
  }
}

store.subscribe((state) => {
  renderTree(state);
  updateDock(state);
  updateSpark(state);
  paintSaveState(state.saveStatus);
  paintPickBanner(state);
  els.emptyState.hidden = !!state.book;
  els.tree.hidden = !state.book;
  els.deleteBtn.disabled = !state.book;
  document.getElementById("btn-export").disabled = !state.book;
  if (state.book) updateCurrentTitle(state.book.title || "Untitled");
});

function paintSaveState(status) {
  const map = { idle: "", dirty: "Unsaved…", saving: "Saving…", saved: "Saved", error: "Save failed" };
  els.saveState.textContent = map[status] ?? "";
  els.saveState.dataset.status = status;
}

// ---- book switching ----------------------------------------------------

async function refreshPicker(selectId) {
  const books = await api.listBooks();
  setPickerBooks(books);
  if (selectId) setPickerValue(selectId);
  return books;
}

async function openBook(id) {
  const book = await api.getBook(id);
  store.setBook(book);
  setPickerValue(id);
  localStorage.setItem(LAST_BOOK, id);
}

mountBookPicker($("book-picker"), { onChange: (id) => openBook(id) });

els.newBtn.addEventListener("click", () => {
  store.setBook(null);
  els.emptyState.hidden = false;
  els.tree.hidden = true;
  els.startTopic.focus();
});

els.deleteBtn.addEventListener("click", async () => {
  const book = store.getBook();
  if (!book || !confirm(`Delete "${book.title}"? This cannot be undone.`)) return;
  await api.deleteBook(book.id);
  localStorage.removeItem(LAST_BOOK);
  const books = await refreshPicker();
  if (books.length) openBook(books[0].id);
  else store.setBook(null);
});

els.startForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const topic = els.startTopic.value.trim();
  if (!topic) return;
  const book = await api.createBook(topic);
  els.startTopic.value = "";
  await refreshPicker(book.id);
  await openBook(book.id);
});

els.expandAll.addEventListener("click", () => store.setAllCollapsed(false));
els.collapseAll.addEventListener("click", () => store.setAllCollapsed(true));

// ---- theme toggle (auto → light → dark) -----------------------------
const THEME_KEY = "rextbooks:theme";
const THEME_CYCLE = ["auto", "light", "dark"];
const THEME_ICON = { auto: "◑", light: "☀", dark: "☾" };
const themeBtn = $("btn-theme");

function readTheme() {
  try { return localStorage.getItem(THEME_KEY) || "auto"; } catch { return "auto"; }
}
function applyTheme(t) {
  if (t === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  try {
    if (t === "auto") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, t);
  } catch {}
  themeBtn.textContent = THEME_ICON[t];
  themeBtn.title = t === "auto" ? "Theme: follows your device — click for light"
    : t === "light" ? "Theme: light — click for dark"
    : "Theme: dark — click for auto";
}
applyTheme(readTheme());
themeBtn.addEventListener("click", () => {
  applyTheme(THEME_CYCLE[(THEME_CYCLE.indexOf(readTheme()) + 1) % THEME_CYCLE.length]);
});

// ---- import a book from .json ----------------------------------------
$("btn-import-book").addEventListener("click", () => $("import-file").click());
$("import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const book = await api.importBook(file);
    await refreshPicker(book.id);
    await openBook(book.id);
  } catch (err) {
    alert("Import failed: " + (err.message || err));
  }
});

// ---- initial load -----------------------------------------------------

(async () => {
  const books = await refreshPicker();
  const last = localStorage.getItem(LAST_BOOK);
  const target = books.find((b) => b.id === last) || books[0];
  if (target) await openBook(target.id);
  else { els.emptyState.hidden = false; els.tree.hidden = true; els.startTopic.focus(); }
  openIfNoKey();   // guides a first-time / freshly-packaged install straight to Settings
})();
