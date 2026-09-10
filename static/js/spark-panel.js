// Spark modal — cross-breed two picked blocks into a new synthesised node.

import * as store from "./store.js";
import { streamGenerate, getSparkModes } from "./api.js";

let els = {};
let modes = {};                 // { key: {label, blurb, template} }
let selectedMode = "cross-pollinate";
let promptDirty = false;
let ctrl = null;
let wasOpen = false;

export async function mountSpark(refs) {
  els = refs;
  try { modes = await getSparkModes(); } catch { modes = {}; }
  renderModeGrid();

  els.closeBtn.addEventListener("click", cancel);
  els.cancelBtn.addEventListener("click", cancel);
  els.backdrop.addEventListener("click", (e) => { if (e.target === els.backdrop) cancel(); });
  els.resetBtn.addEventListener("click", () => { promptDirty = false; fillPrompt(); });
  els.prompt.addEventListener("input", () => { promptDirty = true; });
  els.goBtn.addEventListener("click", run);
  els.stopBtn.addEventListener("click", () => { ctrl?.abort(); ctrl = null; toggleBusy(false); setStatus("Stopped."); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && store.isSparkModalOpen() && !ctrl) cancel();
  });
}

function cancel() { if (!ctrl) store.closeSpark(); }

export function updateSpark(state) {
  const open = state.sparkModalOpen;
  els.backdrop.hidden = !open;
  if (!open) { wasOpen = false; return; }
  if (!wasOpen) {
    promptDirty = false;
    setStatus(""); els.stream.hidden = true; els.stream.textContent = "";
    toggleBusy(false);
  }
  wasOpen = true;
  renderSources(state);
  syncModeGrid();
  if (!promptDirty) fillPrompt();
}

// ---- mode grid ----

function renderModeGrid() {
  els.modes.innerHTML = "";
  for (const [key, m] of Object.entries(modes)) {
    const b = document.createElement("button");
    b.className = "spark-mode";
    b.dataset.key = key;
    b.innerHTML = `<b>${escapeHtml(m.label)}</b><span>${escapeHtml(m.blurb)}</span>`;
    b.addEventListener("click", () => {
      selectedMode = key;
      syncModeGrid();
      promptDirty = false;
      fillPrompt();
    });
    els.modes.append(b);
  }
  syncModeGrid();
}
function syncModeGrid() {
  els.modes.querySelectorAll(".spark-mode")
    .forEach((b) => b.classList.toggle("selected", b.dataset.key === selectedMode));
}

// ---- sources ----

function titles() {
  return store.getSparkIds().map((id) => store.findNode(id)?.node?.title || "(untitled)");
}

function renderSources(state) {
  els.sources.innerHTML = "";
  state.sparkIds.forEach((id, i) => {
    if (i === 1) {
      const x = document.createElement("span");
      x.className = "spark-x"; x.textContent = "×";
      els.sources.append(x);
    }
    const hit = store.findNode(id);
    const chip = document.createElement("span");
    chip.className = "spark-src";
    chip.innerHTML =
      `<b>${i === 0 ? "A" : "B"}</b>` +
      `<span>${escapeHtml(hit?.node?.title || "(untitled)")}</span>` +
      `<button title="Remove">✕</button>`;
    chip.querySelector("button").addEventListener("click", () => { if (!ctrl) store.removeSpark(id); });
    els.sources.append(chip);
  });
}

function fillPrompt() {
  const [a = "A", b = "B"] = titles();
  const tpl = modes[selectedMode]?.template || 'Combine "{a}" and "{b}".';
  els.prompt.value = tpl.replaceAll("{a}", a).replaceAll("{b}", b);
}

// ---- generate ----

function setStatus(msg, kind = "") {
  els.status.hidden = !msg;
  els.status.textContent = msg || "";
  els.status.className = `ai-status ${kind}`;
}
function toggleBusy(busy) {
  els.goBtn.hidden = busy;
  els.stopBtn.hidden = !busy;
  els.closeBtn.disabled = busy;
}

function run() {
  const book = store.getBook();
  const ids = store.getSparkIds();
  if (!book || ids.length !== 2 || ctrl) return;

  const payload = {
    bookId: book.id,
    sparkMode: selectedMode,
    aId: ids[0], bId: ids[1],
    prompt: els.prompt.value.trim(),
  };
  els.stream.hidden = false;
  els.stream.textContent = "";
  setStatus("Sparking…", "busy");
  toggleBusy(true);

  ctrl = streamGenerate(payload, {
    url: "/api/ai/spark",
    onDelta: (_p, full) => { els.stream.textContent = full; els.stream.scrollTop = els.stream.scrollHeight; },
    onDone: (full) => {
      ctrl = null;
      toggleBusy(false);
      if (!full.trim()) { setStatus("The model returned nothing.", "err"); return; }
      const [a, b] = titles();
      const fallback = `${modes[selectedMode]?.label || "Synthesis"}: ${a} × ${b}`;
      const anchor = store.getSparkAnchor();
      const newId = store.sparkInsert(anchor, full, fallback);
      store.closeSpark();
      if (newId) store.select(newId);
    },
    onError: (msg) => { ctrl = null; toggleBusy(false); setStatus(msg, "err"); },
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
