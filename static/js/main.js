// Bootstrap: load a book, wire the panels, keep the UI in sync with the store.

import * as store from "./store.js";
import * as api from "./api.js";
import * as vault from "./local-store.js";
import { mountTree, renderTree } from "./tree.js";
import { mountDock, updateDock } from "./ai-dock.js";
import { mountExport } from "./export-panel.js";
import { mountSpark, updateSpark } from "./spark-panel.js";
import { mountPaneResizer } from "./resize.js";
import { mountMobileView, updateMobileSelection, showMobileView } from "./mobile-view.js";
import { mountSettings, openIfNoKey } from "./settings-panel.js";
import { mountPromptsPanel } from "./prompts-panel.js";
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
  peEditor: $("palette-editor"),
  peName: $("pe-name"),
  peRoles: $("pe-roles"),
  pePreview: $("pe-preview"),
  peError: $("pe-error"),
  peCancel: $("pe-cancel"),
  peSave: $("pe-save"),
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
  providerSelect: $("settings-provider"),
  modelPicker: $("settings-model-picker"),
  modelInput: $("settings-model-input"),
  modelNote: $("settings-model-note"),
  bundleField: $("settings-bundle-field"),
  bundleToggle: $("settings-bundle-toggle"),
  bundlePopover: $("settings-bundle-popover"),
  bundlePopoverClose: $("settings-bundle-close"),
  bundleLocked: $("settings-bundle-locked"),
  bundleActive: $("settings-bundle-active"),
  bundleInput: $("settings-bundle-input"),
  bundleUnlock: $("settings-bundle-unlock"),
  bundleLock: $("settings-bundle-lock"),
  bundleLabel: $("settings-bundle-label"),
  bundleNote: $("settings-bundle-note"),
  keyLabel: $("settings-key-label"),
  keyDest: $("settings-key-dest"),
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

const promptsEls = {
  panel: $("prompts-panel"),
  group: $("prompts-group"),
  filter: $("prompts-filter"),
  list: $("prompts-list"),
  status: $("prompts-status"),
  saveBtn: $("prompts-save"),
  resetAll: $("prompts-reset-all"),
  previewMode: $("preview-mode"),
  previewTone: $("preview-tone"),
  previewDepth: $("preview-depth"),
  previewLength: $("preview-length"),
  previewRun: $("preview-run"),
  previewOut: $("preview-out"),
};

mountTree(els.tree, { onSelect: (id) => store.select(id) });
mountDock(dockEls);
mountExport(exportEls);
mountSpark(sparkEls);
mountPaneResizer();
mountSettings(settingsEls);
mountMobileView({
  workspace: document.querySelector(".workspace"),
  nav: $("mobile-nav"),
  aiJump: $("mobile-ai-jump"),
  aiPane: document.querySelector(".ai-pane"),
  compactToggle: $("ai-compact-toggle"),
  tree: els.tree,
});
mountPromptsPanel(promptsEls);
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
  // Mobile: offer "AI for this block" only once something is selected.
  const selected = state.selectedId ? store.findNode(state.selectedId) : null;
  updateMobileSelection(selected && selected.node ? selected.node.title : "");
});

function paintSaveState(status) {
  const map = {
    idle: "",
    dirty: "Unsaved…",
    saving: "Saving…",
    saved: "Saved",
    error: "Kept in this browser — server save failed",
  };
  els.saveState.textContent = map[status] ?? "";
  els.saveState.dataset.status = status;
}

// ---- book switching ----------------------------------------------------

/** Push this browser's copies back to a server that lost them.
 *
 * A hosted deployment wipes its disk on every redeploy and free-tier
 * spin-down, which used to mean every saved book was gone for good. Each book
 * this browser has opened is mirrored in IndexedDB (local-store.js), so on the
 * first load after a wipe the missing ones are re-created — same ids, same
 * content. A copy whose save never reached the server (``dirty``) is pushed
 * back even if the server still has an older version of it, so a failed save
 * can't silently revert. Returns how many books were written back. */
async function restoreMissingBooks(serverBooks) {
  const local = await vault.listBooks();
  if (!local.length) return 0;
  const have = new Set(serverBooks.map((b) => b.id));
  let restored = 0;
  for (const rec of local) {
    if (!rec.book) continue;
    try {
      if (!have.has(rec.id)) {
        await api.restoreBook(rec.book);
        await vault.putBook(rec.book);          // clean now: the server has it
        restored += 1;
      } else if (rec.dirty) {
        const saved = await api.saveBook(rec.id, rec.book);
        await vault.putBook(saved && saved.id ? saved : rec.book);
        restored += 1;
      }
    } catch (err) {
      console.warn("[vault] could not restore", rec.id, err);
    }
  }
  if (restored) console.info(`[vault] wrote ${restored} book(s) back to the server`);
  return restored;
}

async function refreshPicker(selectId) {
  let books = await api.listBooks();
  const restored = await restoreMissingBooks(books);
  if (restored) books = await api.listBooks();   // re-list so they show up
  setPickerBooks(books);
  if (selectId) setPickerValue(selectId);
  mirrorLibrary(books);   // fire-and-forget: unopened books become recoverable too
  return books;
}

/** Copy every book this browser hasn't cached yet.
 *
 * Opening a book caches it, but a redeploy shouldn't only spare whichever one
 * happened to be open — so the rest of the library is cached in the background,
 * once. Skipped for a very large library (a fresh browser would otherwise pull
 * every book at once) and never awaited, so it can't delay the UI. */
async function mirrorLibrary(books) {
  if (!books.length || books.length > 50) return;
  const cached = new Set((await vault.listBooks()).map((r) => r.id));
  for (const meta of books) {
    if (cached.has(meta.id)) continue;
    try {
      const full = await api.getBook(meta.id);
      await vault.putBook(full);
    } catch (err) {
      console.warn("[vault] could not cache", meta.id, err);
    }
  }
}

async function openBook(id) {
  let book = null;
  try {
    book = await api.getBook(id);
  } catch (err) {
    // Server can't serve it (wiped and not yet restored, or offline) — fall
    // back to this browser's copy rather than showing an empty app.
    book = await vault.getBook(id);
    if (!book) throw err;
  }
  store.setBook(book);
  vault.putBook(book);   // cache on open, so unedited books survive too
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
  await vault.removeBook(book.id);   // leaving it cached would resurrect it on the next load
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

// ---- import a book from a .zip bundle (or a plain .json) ----------------
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
  try {
    const books = await refreshPicker();
    const last = localStorage.getItem(LAST_BOOK);
    const target = books.find((b) => b.id === last) || books[0];
    if (target) await openBook(target.id);
    else { els.emptyState.hidden = false; els.tree.hidden = true; els.startTopic.focus(); }
  } catch (err) {
    console.error("initial load failed", err);
    els.emptyState.hidden = false;
    els.tree.hidden = true;
  }
  openIfNoKey();   // guides a first-time / freshly-packaged install straight to Settings
})();
