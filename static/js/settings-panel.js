// Settings modal: configure the DeepSeek API key at runtime — no file
// editing, no restart needed. Lets the same build be handed to someone else
// (their own key, saved locally on their machine, never sent back to the
// browser once saved) without touching source or a .env file.

import { getSettings, saveSettings, testApiKey } from "./api.js";

let els = {};

export async function mountSettings(refs) {
  els = refs;

  els.openBtn.addEventListener("click", () => open());
  els.closeBtn.addEventListener("click", close);
  els.backdrop.addEventListener("click", (e) => { if (e.target === els.backdrop) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.backdrop.hidden) close(); });

  els.toggleBtn.addEventListener("click", () => {
    const showing = els.keyInput.type === "text";
    els.keyInput.type = showing ? "password" : "text";
    els.toggleBtn.textContent = showing ? "👁" : "🙈";
  });

  els.pexelsToggle.addEventListener("click", () => {
    const showing = els.pexelsInput.type === "text";
    els.pexelsInput.type = showing ? "password" : "text";
    els.pexelsToggle.textContent = showing ? "👁" : "🙈";
  });
  els.pexelsClear.addEventListener("click", async () => {
    els.pexelsInput.value = "";
    try {
      await saveSettings({ pexelsApiKey: "" });
      setInline("Pexels key removed.", "ok");
      await refreshBadge();
    } catch (err) {
      setInline(String(err.message || err), "err");
    }
  });

  els.testBtn.addEventListener("click", onTest);
  els.saveBtn.addEventListener("click", onSave);
  els.removeBtn.addEventListener("click", onRemove);

  await refreshBadge();
}

async function refreshBadge() {
  let s;
  try { s = await getSettings(); }
  catch { s = { hasApiKey: false, keySource: "none", model: "", author: "", hasPexelsKey: false }; }
  els.openBtn.classList.toggle("needs-key", !s.hasApiKey);
  els.openBtn.title = s.hasApiKey ? "Settings" : "Settings — no API key set yet";
  return s;
}

/** Call once on startup — opens Settings automatically when nothing is
 *  configured at all (no .env, nothing saved), so a first launch isn't a
 *  dead end. Returns the settings so the caller can decide anything else. */
export async function openIfNoKey() {
  const s = await refreshBadge();
  if (!s.hasApiKey) await open(s);
  return s;
}

async function open(prefetched) {
  const s = prefetched || await refreshBadge();
  els.modelLine.textContent = s.model || "";
  paintStatus(s);
  els.keyInput.value = "";
  els.keyInput.type = "password";
  els.toggleBtn.textContent = "👁";
  els.authorInput.value = s.author || "";
  els.pexelsInput.value = "";
  els.pexelsInput.type = "password";
  els.pexelsToggle.textContent = "👁";
  els.pexelsInput.placeholder = s.hasPexelsKey ? "•••••••••••••• (saved — leave blank to keep)" : "Paste a Pexels API key…";
  setInline("");
  els.backdrop.hidden = false;
  els.keyInput.focus();
}

function close() { els.backdrop.hidden = true; }

function paintStatus(s) {
  const map = {
    settings: "✓ Using the key saved here in Settings.",
    env: "✓ Using the key from this machine's .env file.",
    none: "⚠ No API key configured yet — generation won't work until you add one below.",
  };
  els.status.textContent = map[s.keySource] || map.none;
  els.status.className = `ai-status ${s.keySource === "none" ? "err" : "ok"}`;
  els.status.hidden = false;
}

function setInline(msg, kind = "") {
  els.inline.hidden = !msg;
  els.inline.textContent = msg || "";
  els.inline.className = `ai-status ${kind}`;
}

async function onTest() {
  const key = els.keyInput.value.trim();
  if (!key) { setInline("Paste a key first.", "err"); return; }
  setInline("Testing…", "busy");
  els.testBtn.disabled = true;
  try {
    const res = await testApiKey(key);
    setInline(res.ok ? "Key works ✓" : (res.error || "Key test failed."), res.ok ? "ok" : "err");
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.testBtn.disabled = false;
  }
}

async function onSave() {
  const key = els.keyInput.value.trim();
  const author = els.authorInput.value.trim();
  const pexelsKey = els.pexelsInput.value.trim();
  els.saveBtn.disabled = true;
  try {
    const payload = { author };            // author is never secret — always round-tripped
    if (key) payload.apiKey = key;         // key input left blank means "leave the key alone"
    if (pexelsKey) payload.pexelsApiKey = pexelsKey;
    await saveSettings(payload);
    els.keyInput.value = "";
    els.pexelsInput.value = "";
    setInline("Saved ✓", "ok");
    paintStatus(await refreshBadge());
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.saveBtn.disabled = false;
  }
}

async function onRemove() {
  els.removeBtn.disabled = true;
  try {
    await saveSettings({ apiKey: "" });
    els.keyInput.value = "";
    setInline("Removed — reverted to .env, if this machine has one.", "ok");
    paintStatus(await refreshBadge());
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.removeBtn.disabled = false;
  }
}
