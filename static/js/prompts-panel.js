// Settings → Advanced: edit the prompt text the app sends to the model.
//
// The canonical text lives in prompts.defaults.json (golden); this panel edits
// sparse overrides in prompts.local.json. "Reset" deletes an override so the
// block falls back to whatever the golden file currently says.

import { getPrompts, savePrompts, resetPrompts, previewPrompt } from "./api.js";
import { TONES, DEPTHS } from "./prompts.js";

let els = {};
let blocks = [];
let loaded = false;
let activeGroup = "All";
let filterText = "";

export function mountPromptsPanel(refs) {
  els = refs;

  els.panel.addEventListener("toggle", () => {
    if (els.panel.open && !loaded) load();
  });
  els.saveBtn.addEventListener("click", save);
  els.resetAll.addEventListener("click", resetAll);
  els.group.addEventListener("change", () => { activeGroup = els.group.value; render(); });
  els.filter.addEventListener("input", () => { filterText = els.filter.value.trim().toLowerCase(); render(); });
  els.previewRun.addEventListener("click", runPreview);

  for (const t of TONES) els.previewTone.appendChild(new Option(t, t));
  for (const d of DEPTHS) els.previewDepth.appendChild(new Option(d, d));
  els.previewTone.insertBefore(new Option("(no tone)", ""), els.previewTone.firstChild);
  els.previewDepth.insertBefore(new Option("(no depth)", ""), els.previewDepth.firstChild);
}

function setStatus(msg, kind = "") {
  els.status.hidden = !msg;
  els.status.textContent = msg || "";
  els.status.className = `ai-status ${kind}`;
}

async function load() {
  setStatus("Loading prompts…", "busy");
  try {
    const res = await getPrompts();
    blocks = res.blocks || [];
    loaded = true;
    fillGroups();
    render();
    setStatus("");
  } catch (err) {
    setStatus(String(err.message || err), "err");
  }
}

function fillGroups() {
  const groups = [...new Set(blocks.map((b) => b.group))];
  els.group.innerHTML = "";
  els.group.appendChild(new Option("All groups", "All"));
  for (const g of groups) els.group.appendChild(new Option(g, g));
  els.group.value = groups.includes(activeGroup) ? activeGroup : "All";
  activeGroup = els.group.value;
}

function render() {
  els.list.innerHTML = "";
  const shown = blocks.filter((b) =>
    (activeGroup === "All" || b.group === activeGroup)
    && (!filterText || (b.label + " " + b.key + " " + b.help).toLowerCase().includes(filterText)));

  let lastGroup = null;
  for (const b of shown) {
    if (b.group !== lastGroup) {
      const h = document.createElement("h4");
      h.className = "prompts-group-head";
      h.textContent = b.group;
      els.list.appendChild(h);
      lastGroup = b.group;
    }
    els.list.appendChild(blockRow(b));
  }
  if (!shown.length) {
    const p = document.createElement("p");
    p.className = "export-note";
    p.textContent = "No prompts match that filter.";
    els.list.appendChild(p);
  }
}

function blockRow(b) {
  const row = document.createElement("div");
  row.className = "prompt-block";
  row.dataset.key = b.key;

  const head = document.createElement("div");
  head.className = "prompt-block-head";

  const label = document.createElement("span");
  label.className = "prompt-block-label";
  label.textContent = b.label;
  head.appendChild(label);

  if (b.tier === "careful") {
    const warn = document.createElement("span");
    warn.className = "prompt-tier";
    warn.textContent = "⚠ parsed";
    warn.title = "The app parses this text's shape — editing it can break that feature.";
    head.appendChild(warn);
  }
  if (b.modified) {
    const badge = document.createElement("span");
    badge.className = "prompt-badge";
    badge.textContent = "edited";
    head.appendChild(badge);
  }

  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "mini-link";
  reset.textContent = "Reset";
  reset.disabled = !b.modified;
  reset.addEventListener("click", () => resetOne(b.key));
  head.appendChild(reset);
  row.appendChild(head);

  if (b.help) {
    const help = document.createElement("p");
    help.className = "export-note";
    help.textContent = b.help;
    row.appendChild(help);
  }

  const ta = document.createElement("textarea");
  ta.className = "prompt-text";
  ta.rows = Math.min(10, Math.max(3, Math.ceil(b.value.length / 110)));
  ta.value = b.value;
  ta.dataset.key = b.key;
  ta.spellcheck = false;
  row.appendChild(ta);

  const orig = document.createElement("details");
  orig.className = "prompt-orig";
  const sum = document.createElement("summary");
  sum.textContent = "Golden text";
  orig.appendChild(sum);
  const pre = document.createElement("pre");
  pre.textContent = b.default;
  orig.appendChild(pre);
  row.appendChild(orig);

  return row;
}

function collectChanges() {
  const byKey = new Map(blocks.map((b) => [b.key, b.value]));
  const changes = {};
  for (const ta of els.list.querySelectorAll("textarea.prompt-text")) {
    const key = ta.dataset.key;
    if (ta.value !== byKey.get(key)) changes[key] = ta.value;
  }
  return changes;
}

async function save() {
  const changes = collectChanges();
  if (!Object.keys(changes).length) { setStatus("Nothing changed.", ""); return; }
  els.saveBtn.disabled = true;
  setStatus("Saving…", "busy");
  try {
    const res = await savePrompts(changes);
    blocks = res.blocks || [];
    render();
    const warn = (res.warnings || []).length
      ? " — note: " + res.warnings.join("; ") : "";
    setStatus(`Saved ${Object.keys(changes).length} prompt(s). Applies to the next generation.${warn}`,
              res.warnings && res.warnings.length ? "err" : "ok");
  } catch (err) {
    setStatus(String(err.message || err), "err");
  } finally {
    els.saveBtn.disabled = false;
  }
}

async function resetOne(key) {
  try {
    const res = await resetPrompts([key]);
    blocks = res.blocks || [];
    render();
    setStatus("Reset to the golden text.", "ok");
  } catch (err) {
    setStatus(String(err.message || err), "err");
  }
}

async function resetAll() {
  if (!confirm("Reset every prompt to the golden defaults in prompts.defaults.json?")) return;
  try {
    const res = await resetPrompts(null);
    blocks = res.blocks || [];
    render();
    setStatus("All prompts reset to the golden text.", "ok");
  } catch (err) {
    setStatus(String(err.message || err), "err");
  }
}

async function runPreview() {
  els.previewOut.textContent = "Building…";
  try {
    const res = await previewPrompt({
      mode: els.previewMode.value,
      tone: els.previewTone.value,
      depth: els.previewDepth.value,
      length: els.previewLength.value,
    });
    els.previewOut.textContent = (res.messages || [])
      .map((m) => `--- ${m.role} ---\n${m.content}`)
      .join("\n\n");
  } catch (err) {
    els.previewOut.textContent = String(err.message || err);
  }
}
