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
let wasBulk = false;
let bulkRunning = false;
let oaOpen = false;         // "Overarching prompt" disclosure — collapsed by default
let oaLastBookId = undefined;   // re-seed the textarea only when the book actually changes
let oaSaveTimer = null;

// A bulk queue is "in view" (prompt box = shared instruction, dock shows the
// N-block summary) whenever the picker is open OR there's a queued selection
// left over from switching to the context picker. It's "armed" — Generate
// actually runs it — once there are 2+ queued blocks.
const bulkInView = () => store.isBulkPick() || store.getBulkIds().length >= 1;
const bulkArmed = () => store.getBulkIds().length >= 2;

export function mountDock(refs) {
  els = refs;

  buildChips(els.tones, TONES, "tone");
  buildChips(els.depths, DEPTHS, "depth");

  els.useImages.addEventListener("change", () => {
    store.setSetting("useImages", els.useImages.checked);
  });

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
      if (!promptDirty && !bulkInView()) refreshPrompt();
    });
  });

  els.prompt.addEventListener("input", () => { promptDirty = true; });
  els.count.addEventListener("input", () => { if (!promptDirty) refreshPrompt(); });
  els.resetBtn.addEventListener("click", () => {
    promptDirty = false;
    if (bulkInView()) els.prompt.value = "";
    else refreshPrompt();
  });
  els.generateBtn.addEventListener("click", run);
  els.stopBtn.addEventListener("click", stop);
  els.addContextBtn.addEventListener("click", () => {
    if (!store.getBook()) return;
    // While a bulk queue is armed, there's no single "target" node to exclude
    // from picking — each queued block excludes only itself, at generate time.
    store.startContextPick(store.getBulkIds().length >= 2 ? null : current.targetId);
  });
  els.sparkBtn.addEventListener("click", () => {
    if (!store.getBook()) return;
    store.startSparkPick(store.getSelectedId());
  });
  els.bulkBtn?.addEventListener("click", () => {
    if (!store.getBook()) return;
    store.startBulkPick();
  });

  els.oaToggle.addEventListener("click", () => setOaOpen(!oaOpen));
  els.oaInput.addEventListener("input", () => {
    updateOaBadge();
    clearTimeout(oaSaveTimer);
    oaSaveTimer = setTimeout(commitOa, 600);   // debounced — typing shouldn't re-render the tree on every keystroke
  });
  els.oaInput.addEventListener("blur", commitOa);
  els.oaClear.addEventListener("click", () => {
    els.oaInput.value = "";
    updateOaBadge();
    commitOa();
  });
}

/** Persist the textarea's current value to the book's settings (debounced
 *  while typing, flushed immediately on blur/Clear). A no-op if nothing
 *  actually changed, so it doesn't mark the book dirty for free. */
function commitOa() {
  clearTimeout(oaSaveTimer);
  const v = els.oaInput.value;
  if (v !== store.getSetting("overarchingPrompt")) store.setSetting("overarchingPrompt", v);
}

function updateOaBadge() {
  els.oaBadge.hidden = !(els.oaInput.value || "").trim();
}

function setOaOpen(open) {
  oaOpen = open;
  els.oaBody.hidden = !open;
  els.oaToggle.setAttribute("aria-expanded", String(open));
  els.oaToggle.classList.toggle("is-open", open);
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

  // Re-seed the overarching-prompt textarea only when the book itself changes
  // (never on every re-render — that would stomp on what the user is typing).
  if (bookId !== oaLastBookId) {
    oaLastBookId = bookId;
    clearTimeout(oaSaveTimer);
    els.oaInput.value = state.book ? (store.getSetting("overarchingPrompt") || "") : "";
    updateOaBadge();
    setOaOpen(false);
  }

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

  els.imagesRow.hidden = mode !== "content";
  els.useImages.checked = !!store.getSetting("useImages");

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

  applyBulkView(state);
}

/** Whenever there's a bulk queue — being picked, or just sitting there while
 *  the user switched over to add context — the dock drives N sequential
 *  generations instead of one. Overrides what `updateDock` just set. */
function applyBulkView(state) {
  renderBulkChips(state);

  const nowBulk = bulkInView();

  if (nowBulk && !wasBulk) {
    promptDirty = false;
    els.prompt.value = "";
    els.prompt.placeholder =
      "Optional — one extra instruction applied to every selected block (e.g. “add more diagrams”)";
    subMode = "content";
    subModeUserSet = false;
  } else if (!nowBulk && wasBulk && !bulkRunning) {
    els.prompt.placeholder = "";
    promptDirty = false;
    refreshPrompt();
  }
  wasBulk = nowBulk;
  if (!nowBulk) return;

  const ids = store.getBulkIds();
  const bt = store.getBulkType();
  const n = ids.length;
  const bmode = bt === "heading" ? "subheadings"
    : bt === "subheading" ? (subMode === "subheadings" ? "subheadings" : "content")
    : "content";

  els.subModeRow.hidden = bt !== "subheading";
  els.subModeRow.querySelectorAll(".seg-btn")
    .forEach((x) => x.classList.toggle("active", x.dataset.sub === subMode));
  els.refineRow.hidden = true;
  els.imagesRow.hidden = bmode !== "content";
  els.countRow.hidden = bmode !== "subheadings";
  if (bmode === "subheadings") els.countRow.querySelector("span").textContent = "Subheadings per block";

  els.modeChip.textContent = "bulk";
  els.modeChip.dataset.mode = bmode;
  els.targetPath.textContent = n
    ? `${n} ${bt}${n > 1 ? "s" : ""} — generated one at a time`
    : "Pick sibling blocks in the outline";

  const verb = bmode === "subheadings"
    ? (bt === "heading" ? "subheadings" : "sub-topics") : "content";
  els.generateBtn.textContent = n >= 2 ? `Generate ${verb} ×${n}` : "Pick 2 or more blocks";
  els.generateBtn.disabled = !!ctrl || !state.book || n < 2;
}

/** The queued bulk-generation blocks — shown as removable chips regardless of
 *  which picker (bulk or context) is currently open, so switching over to add
 *  context doesn't make the queue disappear from view. */
function renderBulkChips(state) {
  const ids = store.getBulkIds();
  if (els.bulkQueue) els.bulkQueue.hidden = ids.length === 0;
  if (!els.bulkChips) return;
  els.bulkChips.innerHTML = "";
  for (const id of ids) {
    const hit = store.findNode(id);
    if (!hit) continue;
    const chip = document.createElement("span");
    chip.className = "ctx-chip bulk-chip";
    chip.innerHTML =
      `<b>${TYPE_ICON[hit.node.type] || "·"}</b>` +
      `<span>${escapeHtml(hit.node.title || "(untitled)")}</span>` +
      `<button title="Remove from bulk" aria-label="Remove">✕</button>`;
    chip.querySelector("button").addEventListener("click", () => store.removeBulk(id));
    els.bulkChips.append(chip);
  }
}

const TYPE_ICON = { heading: "H", subheading: "S", section: "¶" };

function nodeOwnLen(node) {
  return (node.content || "").length + (node.title || "").length + 6;
}

function renderContextChips(state) {
  const ctxPick = store.isContextPick();
  const sparkPick = store.isSparkPick();
  const bulkPick = store.isBulkPick();
  const bulkQueued = store.getBulkIds().length;
  const ids = store.getContextIds();
  const roots = store.contextRootIds();
  const idSet = new Set(ids);

  // Context and bulk are meant to be combined — picking one no longer locks
  // out the other. Spark is a separate, exclusive flow.
  els.addContextBtn.textContent = ctxPick ? "Done" : "＋ Add context";
  els.addContextBtn.classList.toggle("active", ctxPick);
  els.addContextBtn.disabled = !state.book || sparkPick;
  els.sparkBtn.classList.toggle("active", sparkPick || store.isSparkModalOpen());
  els.sparkBtn.disabled = !state.book || ctxPick || bulkPick || bulkQueued > 0;
  if (els.bulkBtn) {
    els.bulkBtn.classList.toggle("active", bulkPick);
    els.bulkBtn.disabled = !state.book || sparkPick;
    els.bulkBtn.textContent = bulkPick ? "Done"
      : bulkQueued ? `⧉ Bulk (${bulkQueued})`
      : "⧉ Bulk";
  }

  els.contextChips.innerHTML = "";
  els.contextChips.hidden = ids.length === 0;

  let bytes = 0;
  for (const id of ids) {
    const hit = store.findNode(id);
    if (hit) bytes += nodeOwnLen(hit.node);
  }
  for (const id of roots) {
    const hit = store.findNode(id);
    if (!hit) continue;
    let nested = 0;
    store.walk(hit.node.children || [], (n) => { if (idSet.has(n.id)) nested++; });
    const base = hit.node.type === "section"
      ? (hit.parent?.title ? `${hit.parent.title} · content` : "Section content")
      : (hit.node.title || "(untitled)");
    const chip = document.createElement("span");
    chip.className = "ctx-chip";
    chip.innerHTML =
      `<b>${TYPE_ICON[hit.node.type] || "·"}</b>` +
      `<span>${escapeHtml(base)}${nested ? ` <i>+${nested}</i>` : ""}</span>` +
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
  if (bulkInView()) return;   // the prompt box is a shared instruction here
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
  if (bulkArmed()) { runBulk(); return; }

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
    useImages: current.mode === "content" && store.getSetting("useImages"),
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
    onStatus: (msg) => setStatus(msg, "busy"),
    onRevise: (full) => {
      // The server just resolved ```image-search placeholders into real
      // images (or dropped ones with no match) — an unthrottled render so
      // this final correction can never be swallowed by throttledRenderSection.
      if (current.mode === "content" && sectionId) renderSection(sectionId, full);
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

// ---- bulk generate: N sibling blocks, one independent request each ----------

/** Run one generation to completion. Resolves with the full text (or "" if
 *  aborted). Writes into the tree exactly like the single-node flow. */
function streamOnce(payload, mode, targetId) {
  return new Promise((resolve, reject) => {
    let sectionId = null;
    const c = streamGenerate(payload, {
      onDelta: (_piece, full) => {
        if (mode === "content") {
          if (!sectionId) {
            const sec = store.ensureSection(targetId);
            sectionId = sec?.id ?? null;
            if (sectionId) store.select(sectionId);
          }
          throttledRenderSection(sectionId, full);
        } else {
          els.stream.textContent = full;
          els.stream.scrollTop = els.stream.scrollHeight;
        }
      },
      onStatus: (msg) => setStatus(msg, "busy"),
      onRevise: (full) => {
        if (mode === "content" && sectionId) renderSection(sectionId, full);
      },
      onDone: (full) => {
        if (mode === "content") {
          if (!sectionId) {
            const sec = store.ensureSection(targetId);
            sectionId = sec?.id ?? null;
          }
          if (sectionId) { store.setContent(sectionId, full); renderSection(sectionId, full); }
        } else {
          const titles = parseList(full);
          if (titles.length) store.appendChildren(targetId, "subheading", titles);
        }
        resolve(full);
      },
      onError: (msg) => reject(new Error(msg)),
    });
    ctrl = c;
    c.signal.addEventListener("abort", () => resolve(""), { once: true });
  });
}

async function runBulk() {
  const book = store.getBook();
  const ids = store.getBulkIds().slice();
  const bt = store.getBulkType();
  if (!book || ctrl || ids.length < 2 || !bt) return;

  const mode = bt === "heading" ? "subheadings"
    : bt === "subheading" ? (subMode === "subheadings" ? "subheadings" : "content")
    : "content";
  const count = Number(els.count.value) || 3;
  const tone = store.getSetting("tone");
  const depth = store.getSetting("depth");
  // Snapshot the context set now — it may include some of the very blocks
  // about to be generated (picked as context for one another); the backend
  // excludes each block from its own context automatically as it's generated.
  const contextIds = store.getContextIds().slice();
  const shared = els.prompt.value.trim();
  const topic = book.topic || book.title || "";

  store.clearBulk();             // the queue is consumed — drop it
  store.endPick();                // and close whichever picker was open
  toggleBusy(true);
  bulkRunning = true;
  els.stream.hidden = mode === "content";
  els.stream.textContent = "";

  let done = 0;
  for (let i = 0; i < ids.length && bulkRunning; i++) {
    const hit = store.findNode(ids[i]);
    if (!hit) continue;
    const targetId = bt === "section" ? (hit.parent?.id ?? null) : hit.node.id;
    if (!targetId) continue;

    const label = hit.node.title || "(untitled)";
    setStatus(`Generating ${i + 1} of ${ids.length}: ${label}…`, "busy");

    let prompt = fillTemplate(mode, { topic, count, selectedId: ids[i] });
    if (shared) prompt += `\n\n${shared}`;

    // Flush first: if an earlier block in this same run is picked as context
    // for this one, the server needs its freshly-generated content on disk.
    await store.flush();

    try {
      const full = await streamOnce(
        { mode, bookId: book.id, nodeId: targetId, count, prompt,
          tone, depth, refine: false, contextIds,
          useImages: mode === "content" && store.getSetting("useImages") },
        mode, targetId,
      );
      if (full && full.trim()) done += 1;
      else if (!bulkRunning) break;   // aborted
    } catch (err) {
      setStatus(`Stopped at “${label}”: ${err.message || err}`, "err");
      bulkRunning = false;
      break;
    }
  }

  const total = ids.length;
  bulkRunning = false;
  ctrl = null;
  toggleBusy(false);
  els.stream.hidden = true;
  lastSig = null;
  updateDock(store.getState());
  store.flush();
  setStatus(
    `Bulk generate: ${done} of ${total} done${done === total ? " ✓" : ""}`,
    done === total ? "ok" : done ? "" : "err",
  );
}

function stop() {
  if (bulkRunning) { bulkRunning = false; ctrl?.abort(); setStatus("Stopping…", ""); return; }
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
