// Settings modal: configure the generation provider, its model and its API
// key at runtime — no file editing, no restart needed. Every provider keeps
// its own model and key, so switching back and forth (or handing the same
// build to someone else, with their own key saved locally on their machine
// and never sent back to the browser once saved) costs nothing.

import { getSettings, saveSettings, testApiKey, unlockKeyBundle, lockKeyBundle } from "./api.js";
import * as store from "./store.js";
import { mountCombo, CUSTOM } from "./combo.js";

let els = {};
let blurbDefault = "";
let providers = [];   // last /api/settings provider list (browser-safe: no keys)
let modelCombo = null;

export async function mountSettings(refs) {
  els = refs;

  // The model is chosen from a themed dropdown (a native <select> renders its
  // open list in OS colours, and a <input list=datalist> only shows options
  // once the box is empty — neither matches the app). The hidden text input
  // stays the single source of the value, so Save/Test keep working unchanged;
  // "Custom model…" just reveals it for a free-form name.
  modelCombo = mountCombo(els.modelPicker, {
    onSelect: (value) => {
      if (value === CUSTOM) {
        els.modelInput.hidden = false;
        els.modelInput.value = "";
        modelCombo.setValue("");
        els.modelInput.focus();
        return;
      }
      els.modelInput.value = value;
      els.modelInput.hidden = true;
      modelCombo.setValue(value);
    },
  });
  els.modelInput.addEventListener("input", () => modelCombo.setValue(els.modelInput.value.trim()));

  els.openBtn.addEventListener("click", () => open());
  els.closeBtn.addEventListener("click", close);
  els.backdrop.addEventListener("click", (e) => { if (e.target === els.backdrop) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.backdrop.hidden) close(); });

  els.providerSelect.addEventListener("change", onProviderChange);

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
      paintPexelsUsage(await refreshBadge());
    } catch (err) {
      setInline(String(err.message || err), "err");
    }
  });

  els.testBtn.addEventListener("click", onTest);
  els.saveBtn.addEventListener("click", onSave);
  els.removeBtn.addEventListener("click", onRemove);
  els.bundleUnlock.addEventListener("click", onUnlockBundle);
  els.bundleLock.addEventListener("click", onLockBundle);
  els.bundleInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); onUnlockBundle(); }
  });
  els.blurbReset.addEventListener("click", () => { els.blurbInput.value = blurbDefault; });

  // Pasting a key is enough: commit it on Enter or when the field is left, so
  // nothing depends on discovering that the Save button is a separate step.
  // (Typing a key and pressing Enter used to do nothing at all — the settings
  // form isn't a <form>, so the keystroke was simply dropped and the key was
  // lost on close.)
  els.keyInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); savePastedKey(); }
  });
  els.keyInput.addEventListener("change", () => { savePastedKey(); });

  await refreshBadge();
}

async function refreshBadge() {
  let s;
  try { s = await getSettings(); }
  catch {
    s = { hasApiKey: false, keySource: "none", provider: "", providerLabel: "",
          model: "", models: [], defaultModel: "", keyPlaceholder: "", keysUrl: "",
          providers: [], author: "", blurbTemplate: "", blurbDefault: "",
          hasPexelsKey: false };
  }
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
  applyLlmState(s);
  els.authorInput.value = s.author || "";
  blurbDefault = s.blurbDefault || "";
  els.blurbInput.value = s.blurbTemplate || blurbDefault;
  els.blurbInput.placeholder = blurbDefault;
  const book = store.getBook();
  els.titleField.hidden = !book;
  if (book) els.titleInput.value = book.title || "";
  els.pexelsInput.value = "";
  els.pexelsInput.type = "password";
  els.pexelsToggle.textContent = "👁";
  els.pexelsInput.placeholder = s.hasPexelsKey ? "•••••••••••••• (saved — leave blank to keep)" : "Paste a Pexels API key…";
  paintPexelsUsage(s);
  setInline("");
  els.backdrop.hidden = false;
  els.keyInput.focus();
}

/** Paint everything that depends on the selected provider. All of it comes
 *  from the server, so it shows what's actually saved rather than whatever
 *  happens to be typed into the form right now. */
function applyLlmState(s) {
  providers = s.providers || [];
  els.providerSelect.innerHTML = "";
  for (const p of providers) {
    const opt = document.createElement("option");
    opt.value = p.provider;
    opt.textContent = p.hasApiKey ? `${p.label} ✓` : p.label;
    els.providerSelect.appendChild(opt);
  }
  if (s.provider) els.providerSelect.value = s.provider;

  const info = providers.find((p) => p.provider === s.provider) || null;
  const label = s.providerLabel || (info ? info.label : "") || "this provider";

  els.modelInput.value = s.model || "";
  const known = [
    { value: "", label: s.defaultModel ? `${s.defaultModel} (default)` : "Provider default" },
    ...(s.models || [])
      .filter((m) => m !== s.defaultModel)
      .map((m) => ({ value: m, label: m })),
    { value: CUSTOM, label: "Custom model…" },
  ];
  modelCombo.setItems(known);
  modelCombo.setValue(s.model || "");
  // A saved name that isn't one of the presets (or a half-typed one) needs the
  // text input visible; a preset, including "default", doesn't.
  els.modelInput.hidden = known.some((k) => k.value === (s.model || ""));
  els.modelNote.textContent = info
    ? `${info.label} default: ${info.defaultModel}. Choose a model from the list, ` +
      `or pick "Custom model…" to type any name ${info.label} accepts.`
    : "";

  // A key bundle ("master key") supplies keys, and optionally the provider and
  // model, for this browser session only. Anything it supplies is disabled here
  // rather than silently ignored — editing it would change the shared file that
  // other people on the same instance are using.
  const bundle = s.keyBundle || { configured: false, unlocked: false };
  const managed = bundle.unlocked ? (bundle.providers || []) : [];
  els.providerSelect.disabled = !!bundle.unlocked;
  els.keyInput.disabled = managed.includes(s.provider);
  els.pexelsInput.disabled = managed.includes("pexels");
  if (bundle.unlocked) {
    els.keyInput.placeholder = managed.includes(s.provider)
      ? `Supplied by the "${bundle.label}" key bundle`
      : els.keyInput.placeholder;
    els.pexelsInput.placeholder = managed.includes("pexels")
      ? `Supplied by the "${bundle.label}" key bundle`
      : els.pexelsInput.placeholder;
  }
  paintKeyBundle(bundle);

  els.keyLabel.textContent = `${label} API key`;
  els.keyDest.textContent = label;
  els.keyInput.value = "";
  els.keyInput.type = "password";
  // Same convention as the Pexels field: a saved key is never echoed back, so
  // say one is saved rather than leaving the box looking empty.
  els.keyInput.placeholder = s.keySource === "settings"
    ? "•••••••••••••• (saved — leave blank to keep)"
    : (s.keyPlaceholder || "");
  els.toggleBtn.textContent = "👁";

  els.modelLine.textContent = `${label} · ${s.model || ""}`;
  paintStatus(s);
}

/** Pexels has no usage dashboard of its own — the only place this is ever
 *  visible is the response headers on each search call, which images.py
 *  records (config.py) every time it actually calls Pexels. Shows the
 *  last-known snapshot; nothing to show until a search has happened at
 *  least once. */
function paintPexelsUsage(s) {
  const u = s.pexelsUsage;
  if (!u || u.remaining == null || u.limit == null) { els.pexelsUsage.hidden = true; return; }
  const pct = u.limit ? Math.round((u.remaining / u.limit) * 100) : null;
  const resetIn = u.reset ? formatDuration(u.reset * 1000 - Date.now()) : null;
  const checkedAgo = u.checkedAt ? formatDuration(Date.now() - u.checkedAt * 1000) : null;
  els.pexelsUsage.textContent =
    `Usage: ${u.remaining.toLocaleString()} / ${u.limit.toLocaleString()} requests remaining` +
    (pct != null ? ` (${pct}%)` : "") +
    (resetIn ? ` · resets in ${resetIn}` : "") +
    (checkedAgo ? ` · as of ${checkedAgo} ago` : "");
  els.pexelsUsage.hidden = false;
}

function formatDuration(ms) {
  if (ms == null || !Number.isFinite(ms)) return null;
  const mins = Math.round(Math.abs(ms) / 60000);
  if (mins < 1) return "under a minute";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h < 48) return h > 0 ? `${h}h ${m}m` : `${m}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function close() { els.backdrop.hidden = true; }

/** The "master key" field: hidden entirely unless the server has bundles
 *  configured, so a normal single-user install never sees it. */
function paintKeyBundle(bundle) {
  const visible = !!bundle.configured;
  els.bundleField.hidden = !visible;
  if (!visible) return;
  const unlocked = !!bundle.unlocked;
  els.bundleLocked.hidden = unlocked;
  els.bundleActive.hidden = !unlocked;
  els.bundleInput.value = "";
  if (unlocked) {
    els.bundleLabel.textContent = bundle.label || "Key bundle";
    const which = (bundle.providers || []).join(", ") || "none";
    els.bundleNote.textContent =
      `Unlocked for this browser — ${which} supplied by the bundle` +
      (bundle.model ? `, model fixed to ${bundle.model}` : "") +
      `. Provider and key fields are managed here; lock it to edit them yourself.`;
  } else {
    els.bundleNote.textContent =
      "One key that fills in every provider key at once — no separate Gemini/" +
      "DeepSeek/Pexels keys needed. It unlocks this browser only and is never " +
      "stored on this machine.";
  }
}

async function onUnlockBundle() {
  const passcode = els.bundleInput.value.trim();
  if (!passcode) return;
  els.bundleUnlock.disabled = true;
  setInline("Unlocking…", "busy");
  try {
    const s = await unlockKeyBundle(passcode);
    applyLlmState(s);
    paintPexelsUsage(s);
    els.bundleInput.value = "";
    setInline(`Unlocked — using the "${s.keyBundle.label}" keys.`, "ok");
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.bundleUnlock.disabled = false;
  }
}

async function onLockBundle() {
  els.bundleLock.disabled = true;
  try {
    const s = await lockKeyBundle();
    applyLlmState(s);
    paintPexelsUsage(s);
    setInline("Locked — back to this machine's own keys.", "ok");
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.bundleLock.disabled = false;
  }
}

function paintStatus(s) {
  const who = s.providerLabel || "the selected provider";
  const map = {
    bundle: `✓ Using the ${who} key from your key bundle.`,
    settings: `✓ Using the ${who} key saved here in Settings.`,
    env: `✓ Using the ${who} key from this machine's .env file.`,
    none: `⚠ No ${who} API key configured yet — generation won't work until you add one below.`,
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

/** Switching provider saves immediately — choosing a provider *is* the
 *  action, unlike the model/key fields, which are edits a Save commits.
 *  Leaves any typed-but-unsaved model/key behind, since both belong to the
 *  provider being switched away from. */
async function onProviderChange() {
  els.saveBtn.disabled = true;
  setInline("Switching provider…", "busy");
  try {
    const s = await saveSettings({ provider: els.providerSelect.value });
    applyLlmState(s);
    setInline(
      `Now using ${s.providerLabel}` +
        (s.hasApiKey ? "." : " — add a key for it below."),
      s.hasApiKey ? "ok" : "",
    );
  } catch (err) {
    setInline(String(err.message || err), "err");
    applyLlmState(await refreshBadge());   // revert the select to the real state
  } finally {
    els.saveBtn.disabled = false;
  }
}

/** Persist whatever is in the key box without touching the rest of the form.
 *  Deliberately not `applyLlmState()` afterwards: that repaints the model field
 *  from what's saved on the server, which would wipe a model name the user has
 *  typed but not yet saved. A very short value is presumed to be a half-typed
 *  paste and is ignored — the Save button still accepts anything.
 *  Returns true when a key was actually stored. */
async function savePastedKey({ silent = false } = {}) {
  const key = els.keyInput.value.trim();
  if (key.length < 20) return false;
  try {
    const s = await saveSettings({ apiKey: key, provider: els.providerSelect.value });
    els.keyInput.value = "";
    els.keyInput.type = "password";
    els.toggleBtn.textContent = "👁";
    els.keyInput.placeholder = "•••••••••••••• (saved — leave blank to keep)";
    els.openBtn.classList.toggle("needs-key", !s.hasApiKey);
    paintStatus(s);
    if (!silent) setInline("API key saved on this machine ✓", "ok");
    return true;
  } catch (err) {
    if (!silent) setInline(String(err.message || err), "err");
    return false;
  }
}

async function onTest() {
  // An empty field tests the key already saved for this provider — the server
  // falls back to it, so "does the key I stored earlier still work?" needs no
  // re-pasting.
  const key = els.keyInput.value.trim();
  setInline(key ? "Testing…" : "Testing the saved key…", "busy");
  els.testBtn.disabled = true;
  try {
    const res = await testApiKey(key, els.providerSelect.value, els.modelInput.value.trim());
    if (res.ok) {
      // Testing a key that works should also keep it — otherwise Test is a dead
      // end that silently throws away the paste.
      const saved = await savePastedKey({ silent: true });
      setInline((res.message || "Key works ✓") + (saved ? " — saved on this machine" : ""),
                "ok");
    } else {
      setInline(res.error || "Key test failed.", "err");
    }
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.testBtn.disabled = false;
  }
}

async function onSave() {
  const key = els.keyInput.value.trim();
  const author = els.authorInput.value.trim();
  const blurbTemplate = els.blurbInput.value.trim();
  const pexelsKey = els.pexelsInput.value.trim();
  els.saveBtn.disabled = true;
  try {
    // author/blurb are never secret — always round-tripped. Provider and
    // model are ordinary choices, so they are always sent too.
    const payload = {
      author, blurbTemplate,
      provider: els.providerSelect.value,
      model: els.modelInput.value.trim(),
    };
    if (key) payload.apiKey = key;         // key input left blank means "leave the key alone"
    if (pexelsKey) payload.pexelsApiKey = pexelsKey;
    const s = await saveSettings(payload);
    if (store.getBook()) {
      const title = els.titleInput.value.trim();
      if (title && title !== store.getBook().title) store.setBookTitle(title);
    }
    els.pexelsInput.value = "";
    applyLlmState(s);
    paintPexelsUsage(s);
    setInline("Saved ✓", "ok");
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.saveBtn.disabled = false;
  }
}

async function onRemove() {
  els.removeBtn.disabled = true;
  try {
    // Scoped to the provider on screen — removing DeepSeek's key must not
    // touch a Gemini key saved earlier.
    const s = await saveSettings({ apiKey: "", provider: els.providerSelect.value });
    applyLlmState(s);
    setInline(
      `Removed — ${s.providerLabel} now falls back to .env, if this machine has one.`,
      "ok",
    );
  } catch (err) {
    setInline(String(err.message || err), "err");
  } finally {
    els.removeBtn.disabled = false;
  }
}
