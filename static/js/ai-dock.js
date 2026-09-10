// The right-hand AI panel. Mode is derived from the selected block.

import * as store from "./store.js";
import { streamGenerate } from "./api.js";
import {
  resolveMode, hasSubTopics, fillTemplate, parseList, COUNT_LABEL, TONES, DEPTHS,
} from "./prompts.js";

let els = {};
let promptDirty = false;
let current = { mode: null, targetId: undefined };
let lastSig = null;   // book + selection signature; when it changes we refresh the prompt
let refineMode = "replace";
let subMode = "content";   // for a selected subheading: "content" | "subheadings"
let subModeUserSet = false;
let ctrl = null;
let renderThrottle = 0;

export function mountDock(refs) {
  els = refs;

  buildChips(els.tones, TONES, "tone");
  buildChips(els.depths, DEPTHS, "depth");

  els.refineRow.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      refineMode = b.dataset.refine;
      els.refineRow.querySelectorAll(".seg-btn")
        .forEach((x) => x.classList.toggle("active", x === b));
    });
  });

  els.subModeRow.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      subMode = b.dataset.sub;
      subModeUserSet = true;
      updateDock(store.getState());
      if (!promptDirty) refreshPrompt();
    });
  });

  els.prompt.addEventListener("input", () => { promptDirty = true; });
  els.count.addEventListener("input", () => { if (!promptDirty) refreshPrompt(); });
  els.resetBtn.addEventListener("click", () => { promptDirty = false; refreshPrompt(); });
  els.generateBtn.addEventListener("click", run);
  els.stopBtn.addEventListener("click", stop);
  els.addContextBtn.addEventListener("click", () => {
    if (!store.getBook()) return;
    store.startContextPick(current.targetId);
  });
  els.sparkBtn.addEventListener("click", () => {
    if (!store.getBook()) return;
    store.startSparkPick(store.getSelectedId());
  });
}

function buildChips(container, values, settingKey) {
  container.innerHTML = "";
  for (const v of values) {
    const chip = document.createElement("button");
    chip.className = "chip toggle";
    chip.textContent = v;
    chip.dataset.value = v;
    chip.setAttribute("role", "radio");
    chip.addEventListener("click", () => {
      store.setSetting(settingKey, v);
      syncChips(container, v);
      if (!promptDirty) refreshPrompt();
    });
    container.append(chip);
  }
}

function syncChips(container, value) {
  container.querySelectorAll(".chip").forEach((c) => {
    const on = c.dataset.value === value;
    c.classList.toggle("active", on);
    c.setAttribute("aria-checked", String(on));
  });
}

export function updateDock(state) {
  const bookId = state.book?.id || "";
  if (lastSig !== null && !lastSig.startsWith(bookId + "|")) promptDirty = false;

  const sig = `${bookId}|${state.book?.topic || ""}|${state.selectedId || ""}`;
  const changed = sig !== lastSig;

  // The selected node — is it a subheading? decide the default Sub-topics/Content.
  const selHit = state.selectedId ? store.findNode(state.selectedId) : null;
  const onSubheading = selHit?.node?.type === "subheading";
  if (changed) {
    subModeUserSet = false;
    subMode = onSubheading && hasSubTopics(selHit.node) ? "subheadings" : "content";
  }

  const { mode, targetId } = resolveMode(state.selectedId, onSubheading ? subMode : undefined);
  current = { mode, targetId };

  if (changed) {
    lastSig = sig;
    refineMode = "replace";
    els.refineRow.querySelectorAll(".seg-btn")
      .forEach((x) => x.classList.toggle("active", x.dataset.refine === "replace"));
    if (!promptDirty && !ctrl) refreshPrompt();
  }

  syncChips(els.tones, store.getSetting("tone"));
  syncChips(els.depths, store.getSetting("depth"));
  els.refineRow.hidden = !(mode === "content" && sectionHasContent());

  els.subModeRow.hidden = !onSubheading;
  els.subModeRow.querySelectorAll(".seg-btn")
    .forEach((x) => x.classList.toggle("active", x.dataset.sub === subMode));

  renderContextChips(state);

  els.modeChip.textContent = mode;
  els.modeChip.dataset.mode = mode;

  els.targetPath.textContent =
    mode === "outline"
      ? "Whole textbook"
      : store.pathTo(state.selectedId).map((n) => n.title || "(untitled)").join("  ›  ");

  const label = COUNT_LABEL[mode];
  els.countRow.hidden = !label;
  if (label) els.countRow.querySelector("span").textContent = label;

  const busy = !!ctrl;
  els.generateBtn.disabled = busy || !state.book;
  els.generateBtn.textContent =
    mode === "outline" ? "Generate outline"
    : mode === "subheadings" ? (onSubheading ? "Generate sub-topics" : "Generate subheadings")
    : sectionHasContent() ? "Regenerate content"
    : "Generate content";
}

const TYPE_ICON = { heading: "H", subheading: "S", section: "¶" };

function nodeFlatLen(node) {
  let n = 0;
  (function rec(x) {
    n += (x.content || "").length + (x.title || "").length + 6;
    for (const c of x.children || []) rec(c);
  })(node);
  return n;
}

function renderContextChips(state) {
  const ctxPick = store.isContextPick();
  const sparkPick = store.isSparkPick();
  const ids = store.getContextIds();

  els.addContextBtn.textContent = ctxPick ? "Done" : "＋ Add context";
  els.addContextBtn.classList.toggle("active", ctxPick);
  els.addContextBtn.disabled = !state.book || sparkPick;
  els.sparkBtn.classList.toggle("active", sparkPick || store.isSparkModalOpen());
  els.sparkBtn.disabled = !state.book || ctxPick;

  els.contextChips.innerHTML = "";
  els.contextChips.hidden = ids.length === 0;
  let bytes = 0;
  for (const id of ids) {
    const hit = store.findNode(id);
    if (!hit) continue;
    bytes += nodeFlatLen(hit.node);
    const label = hit.node.type === "section"
      ? (hit.parent?.title ? `${hit.parent.title} · content` : "Section content")
      : (hit.node.title || "(untitled)");
    const chip = document.createElement("span");
    chip.className = "ctx-chip";
    chip.innerHTML =
      `<b>${TYPE_ICON[hit.node.type] || "·"}</b>` +
      `<span>${escapeHtml(label)}</span>` +
      `<button title="Remove" aria-label="Remove">✕</button>`;
    chip.querySelector("button").addEventListener("click", () => store.removeContext(id));
    els.contextChips.append(chip);
  }
  if (ids.length) {
    const hint = document.createElement("span");
    hint.className = "ctx-hint";
    const approx = bytes > 1200 ? `~${Math.round(bytes / 1000)}k chars` : `~${bytes} chars`;
    hint.textContent = `${ids.length} block${ids.length > 1 ? "s" : ""} · ${approx}`;
    els.contextChips.append(hint);
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function sectionHasContent() {
  if (current.mode !== "content" || !current.targetId) return false;
  const hit = store.findNode(current.targetId);
  const node = hit?.node;
  if (!node) return false;
  if (node.type === "section") return (node.content || "").trim().length > 0;
  const sec = (node.children || []).find((c) => c.type === "section");
  return !!(sec && (sec.content || "").trim());
}

function refreshPrompt() {
  const book = store.getBook();
  els.prompt.value = fillTemplate(current.mode, {
    topic: book?.topic || book?.title || "",
    count: Number(els.count.value) || 3,
    selectedId: store.getSelectedId(),
  });
}

function setStatus(msg, kind = "") {
  els.status.hidden = !msg;
  els.status.textContent = msg || "";
  els.status.className = `ai-status ${kind}`;
}

async function run() {
  const book = store.getBook();
  if (!book || ctrl) return;

  const refine = current.mode === "content" && sectionHasContent() && refineMode === "refine";

  const contextIds = store.getContextIds().slice();
  store.endPick();

  const payload = {
    mode: current.mode,
    bookId: book.id,
    nodeId: current.targetId,
    count: Number(els.count.value) || 3,
    prompt: els.prompt.value.trim(),
    tone: store.getSetting("tone"),
    depth: store.getSetting("depth"),
    refine,
    contextIds,
  };

  els.stream.hidden = current.mode === "content";
  els.stream.textContent = "";
  const ctxNote = contextIds.length ? ` with ${contextIds.length} context block${contextIds.length > 1 ? "s" : ""}` : "";
  setStatus((refine ? "Refining draft" : "Contacting DeepSeek") + ctxNote + "…", "busy");
  toggleBusy(true);

  let sectionId = null;

  ctrl = streamGenerate(payload, {
    onStart: () => setStatus(refine ? "Refining…" : "Generating…", "busy"),
    onDelta: (_piece, full) => {
      if (current.mode === "content") {
        if (!sectionId) {
          const sec = store.ensureSection(current.targetId);
          sectionId = sec?.id ?? null;
          if (sectionId) store.select(sectionId);
        }
        throttledRenderSection(sectionId, full);
      } else {
        els.stream.textContent = full;
        els.stream.scrollTop = els.stream.scrollHeight;
      }
    },
    onDone: (full) => {
      if (current.mode === "content") {
        if (!sectionId) {
          const sec = store.ensureSection(current.targetId);
          sectionId = sec?.id ?? null;
        }
        if (sectionId) { store.setContent(sectionId, full); renderSection(sectionId, full); }
        setStatus(full.trim() ? "Content updated ✓" : "The model returned nothing.",
                  full.trim() ? "ok" : "err");
      } else {
        const titles = parseList(full);
        if (titles.length && current.mode === "outline") {
          store.appendChildren(null, "heading", titles);
        } else if (titles.length) {
          store.appendChildren(current.targetId, "subheading", titles);
        }
        setStatus(
          titles.length
            ? `Added ${titles.length} ${current.mode === "outline" ? "headings" : "subheadings"} ✓`
            : "No list items found in the response.",
          titles.length ? "ok" : "err",
        );
        els.stream.hidden = true;
      }
      finish();
    },
    onError: (msg) => { setStatus(msg, "err"); finish(); },
  });
}

function stop() {
  ctrl?.abort();
  finish();
  setStatus("Stopped.", "");
}

function finish() {
  ctrl = null;
  toggleBusy(false);
  lastSig = null;
  updateDock(store.getState());
  store.flush();
}

function toggleBusy(busy) {
  els.generateBtn.hidden = busy;
  els.stopBtn.hidden = !busy;
}

function throttledRenderSection(id, text) {
  const now = Date.now();
  if (now - renderThrottle < 400) return;
  renderThrottle = now;
  renderSection(id, text, false);   // skip Mermaid on partial streamed text
}

function renderSection(id, text, mermaid = true) {
  const block = document.querySelector(`.block[data-id="${id}"]`);
  if (block && block._renderBody) block._renderBody(text, { mermaid });
}
