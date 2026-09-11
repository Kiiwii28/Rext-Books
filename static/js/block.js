// Render one block (heading / subheading / section) with its hover toolbar,
// plus the in-place Markdown editor + image uploader for section blocks.

import * as store from "./store.js";
import { renderMarkdown, uploadImage } from "./api.js";
import { setEditLock } from "./tree.js";
import { renderMermaidIn } from "./mermaid-render.js";

const TYPE_LABEL = { heading: "Heading", subheading: "Subheading", section: "Section" };

const esc = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// A broken image (404, hot-link block, bad URL) becomes a tidy caption box
// rather than the browser's big grey placeholder.
function figurePlaceholder(alt) {
  const fig = document.createElement("figure");
  fig.className = "fig-placeholder";
  fig.innerHTML = `<span class="fig-icon" aria-hidden="true">▨</span>` +
    `<figcaption>${esc(alt || "Figure")}</figcaption>`;
  return fig;
}
function replaceBrokenImg(img) {
  const holder = img.closest("p, figure");
  const fig = figurePlaceholder(img.getAttribute("alt"));
  (holder && holder.children.length === 1 && !holder.textContent.trim() ? holder : img)
    .replaceWith(fig);
}
function watchImages(el) {
  el.querySelectorAll("img:not([data-imgchk])").forEach((img) => {
    img.dataset.imgchk = "1";
    if (img.complete && img.naturalWidth === 0) replaceBrokenImg(img);
    else img.addEventListener("error", () => replaceBrokenImg(img), { once: true });
  });
}

// Small markdown render cache so re-renders during editing are cheap.
const mdCache = new Map();
async function renderInto(el, text, { mermaid = true } = {}) {
  const key = text || "";
  if (mdCache.has(key)) {
    el.innerHTML = mdCache.get(key);
  } else {
    try {
      const html = await renderMarkdown(key);
      mdCache.set(key, html);
      el.innerHTML = html;
    } catch {
      el.textContent = key;
      return;
    }
  }
  watchImages(el);
  if (mermaid && el.querySelector("pre.mermaid")) renderMermaidIn(el);
}

export function createBlock(node, { selectedId, onChange, context }) {
  const wrap = document.createElement("div");
  wrap.className = `block block-${node.type}`;
  wrap.dataset.id = node.id;
  wrap.dataset.type = node.type;
  if (node.id === selectedId) wrap.classList.add("is-selected");
  if (node.collapsed) wrap.classList.add("is-collapsed");

  const pick = context && context.pick;
  if (pick && context.picked) wrap.classList.add(context.mode === "spark" ? "is-spark" : "is-context");
  if (pick && context.mode === "bulk" && context.picked) wrap.classList.add("is-bulk");
  if (pick && context.isTarget) wrap.classList.add("is-context-target");

  const hasChildren = (node.children || []).length > 0;
  const canHaveChildren = store.childTypeOf(node.type) !== null;

  // ---- row ----
  const row = document.createElement("div");
  row.className = "block-row";

  const handle = document.createElement("button");
  handle.className = "b-handle";
  handle.title = "Drag to reorder";
  handle.textContent = "⠿";
  handle.setAttribute("draggable", "true");

  const chevron = document.createElement("button");
  chevron.className = "b-chevron";
  chevron.textContent = "▸";
  chevron.title = node.collapsed ? "Expand" : "Collapse";
  if (!canHaveChildren) chevron.classList.add("is-hidden");
  if (hasChildren) chevron.classList.add("has-content");
  chevron.addEventListener("click", (e) => {
    e.stopPropagation();
    store.toggleCollapse(node.id);
  });

  // In a "pick" mode (context or spark) a checkbox replaces the drag handle and
  // the whole row toggles pick-membership instead of selecting the block.
  let checkbox = null;
  if (pick) {
    checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "b-ctx-check";
    checkbox.checked = !!context.picked;
    checkbox.disabled = !!context.disabled;
    checkbox.title = context.isTarget
      ? "This is the block you're generating on"
      : context.disabled
        ? (context.mode === "spark" ? "Spark takes exactly two blocks"
           : context.mode === "bulk" ? "Bulk generate needs siblings of the same kind"
           : "Use as context")
      : context.mode === "spark" ? "Pick for Spark"
      : context.mode === "bulk" ? "Include in bulk generation"
      : "Use as context";
    checkbox.addEventListener("click", (e) => e.stopPropagation());
    checkbox.addEventListener("change", () => context.toggle(node.id));
  }

  const titleEl = document.createElement("div");
  titleEl.className = "b-title";
  titleEl.textContent = node.title || "(untitled)";
  titleEl.addEventListener("click", () => {
    if (pick) { if (!context.disabled) context.toggle(node.id); }
    else onChange.select(node.id);
  });

  function beginEdit() {
    if (!node.title) titleEl.textContent = "";
    titleEl.contentEditable = "true";
    titleEl.classList.add("editing");
    titleEl.focus();
    document.getSelection()?.selectAllChildren(titleEl);
  }
  function commitEdit() {
    titleEl.contentEditable = "false";
    titleEl.classList.remove("editing");
    if (store.getPendingEdit() === node.id) store.clearPendingEdit();
    const v = titleEl.textContent.trim();
    if (v && v !== node.title) store.updateTitle(node.id, v);
    else titleEl.textContent = node.title || "(untitled)";
  }
  titleEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); titleEl.blur(); }
    if (e.key === "Escape") { titleEl.textContent = node.title; titleEl.blur(); }
  });
  titleEl.addEventListener("blur", commitEdit);
  titleEl.addEventListener("dblclick", beginEdit);

  const kind = document.createElement("span");
  kind.className = "b-kind";
  kind.textContent = TYPE_LABEL[node.type];

  // ---- toolbar ----
  const tools = document.createElement("div");
  tools.className = "b-tools";

  if (node.type === "section") {
    tools.append(toolBtn("✎", "Edit content", (e) => { e.stopPropagation(); openEditor(); }));
    tools.append(toolBtn("↻", "Reprompt with the AI", (e) => {
      e.stopPropagation();
      onChange.select(node.id);
      document.getElementById("ai-prompt")?.scrollIntoView({ block: "nearest" });
    }));
  } else {
    tools.append(toolBtn("✎", "Edit title", (e) => { e.stopPropagation(); beginEdit(); }));
  }

  if (canHaveChildren) {
    tools.append(toolBtn("＋", `Add ${store.childTypeOf(node.type)}`, (e) => {
      e.stopPropagation();
      const created = store.addChild(node.id, "");
      if (created) onChange.select(created.id);
    }));
  }
  if (node.type === "heading" || node.type === "subheading") {
    tools.append(toolBtn("↳", "Recurse — add a nested sub-topic", (e) => {
      e.stopPropagation();
      const created = store.addRecurseChild(node.id);
      if (created) onChange.select(created.id);
    }));
  }
  tools.append(toolBtn("⧉", "Add sibling below", (e) => {
    e.stopPropagation();
    const created = store.addSiblingAfter(node.id, "");
    if (created) onChange.select(created.id);
  }));
  tools.append(toolBtn("🗑", "Delete", (e) => {
    e.stopPropagation();
    if ((node.children || []).length && !confirm("Delete this block and everything inside it?")) return;
    store.removeNode(node.id);
  }));

  if (pick) {
    row.append(checkbox, chevron, titleEl, kind);
  } else {
    row.append(handle, chevron, titleEl, kind, tools);
  }
  wrap.append(row);
  wrap._beginEdit = beginEdit;

  // ---- section body ----
  let body = null;
  if (node.type === "section") {
    body = document.createElement("div");
    body.className = "b-section-body markdown-body";
    if (!(node.content || "").trim()) {
      body.classList.add("is-empty");
      body.textContent = "No content yet — use the AI panel, or click ✎ to write it.";
    } else {
      renderInto(body, node.content);
    }
    body.addEventListener("dblclick", openEditor);
    wrap.append(body);
    wrap._renderBody = (text, opts) => { body.classList.remove("is-empty"); renderInto(body, text, opts); };
  }

  // ---- children mount point ----
  if (canHaveChildren) {
    const kids = document.createElement("div");
    kids.className = "block-children";
    kids.dataset.parent = node.id;
    wrap.append(kids);
    wrap._childMount = kids;
    if (!hasChildren) wrap.classList.add("no-children");
  }

  // ---- section editor -------------------------------------------------
  function openEditor() {
    if (pick || node.type !== "section" || wrap.querySelector(".b-section-edit")) return;
    setEditLock(true);
    body.hidden = true;

    const ed = document.createElement("div");
    ed.className = "b-section-edit";
    ed.innerHTML = `
      <div class="b-edit-bar">
        <button class="b-tool" data-act="image" title="Insert an image">🖼&nbsp;Image</button>
        <span class="b-edit-hint">Markdown — you can also paste an image straight in</span>
        <span class="flex"></span>
        <button class="btn ghost sm" data-act="cancel">Cancel</button>
        <button class="btn primary sm" data-act="done">Done</button>
      </div>
      <div class="b-image-panel" hidden></div>
      <textarea class="b-section-editor" spellcheck="true"></textarea>
      <div class="b-edit-preview markdown-body"></div>`;

    const ta = ed.querySelector(".b-section-editor");
    const preview = ed.querySelector(".b-edit-preview");
    const imagePanel = ed.querySelector(".b-image-panel");
    ta.value = node.content || "";
    autosize(ta);

    let t;
    const refreshPreview = () => {
      clearTimeout(t);
      t = setTimeout(() => renderInto(preview, ta.value), 300);
    };
    refreshPreview();
    ta.addEventListener("input", () => { autosize(ta); refreshPreview(); });

    ta.addEventListener("paste", (e) => {
      const file = [...(e.clipboardData?.items || [])]
        .find((i) => i.type.startsWith("image/"))?.getAsFile();
      if (!file) return;
      e.preventDefault();
      uploadAndInsert({ file }, ta);
    });

    ed.querySelector(".b-edit-bar").addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "done") close(ta.value);
      else if (act === "cancel") close(null);
      else if (act === "image") {
        imagePanel.hidden = !imagePanel.hidden;
        if (!imagePanel.hidden && !imagePanel.dataset.built) {
          buildImagePanel(imagePanel, ta);
          imagePanel.dataset.built = "1";
        }
      }
    });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(null); }
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); close(ta.value); }
    });

    function close(value) {
      if (value !== null && value !== node.content) store.setContent(node.id, value);
      setEditLock(false);   // re-renders the tree from the store
    }

    body.parentNode.insertBefore(ed, body.nextSibling);
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }

  return wrap;
}

// ---- image upload -----------------------------------------------------

async function uploadAndInsert(payload, ta, onStatus = null) {
  const bookId = store.getBook()?.id;
  if (!bookId) return;
  onStatus?.("Uploading…", "busy");
  try {
    const res = await uploadImage(bookId, payload);
    insertAtCaret(ta, res.markdown);
    onStatus?.(res.external ? "Linked external image ✓" : "Image inserted ✓", "ok");
    return res;
  } catch (err) {
    const msg = String(err.message || err);
    if (onStatus) onStatus(msg, "err");
    else alert("Image upload failed: " + msg);
  }
}

function buildImagePanel(panel, ta) {
  panel.innerHTML = `
    <div class="ip-tabs">
      <button class="ip-tab active" data-tab="paste">Paste / Drop</button>
      <button class="ip-tab" data-tab="upload">Upload file</button>
      <button class="ip-tab" data-tab="link">From link</button>
    </div>
    <div class="ip-panes">
      <div data-pane="paste"><div class="ip-drop" tabindex="0">Click here, then paste an image — or drag &amp; drop a file</div></div>
      <div data-pane="upload" hidden><input type="file" class="ip-file" accept="image/png,image/jpeg,image/gif,image/webp"></div>
      <div data-pane="link" hidden>
        <div class="ip-link-row">
          <input type="url" class="ip-url" placeholder="https://example.com/image.png">
          <button class="btn primary sm ip-add">Add</button>
        </div>
      </div>
    </div>
    <div class="ip-status" hidden></div>`;

  const status = panel.querySelector(".ip-status");
  const setS = (m, k = "") => { status.hidden = !m; status.textContent = m || ""; status.className = `ip-status ${k}`; };

  panel.querySelectorAll(".ip-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      panel.querySelectorAll(".ip-tab").forEach((x) => x.classList.toggle("active", x === tab));
      panel.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== tab.dataset.tab; });
    });
  });

  const drop = panel.querySelector(".ip-drop");
  drop.addEventListener("paste", (e) => { e.preventDefault(); grab(e.clipboardData); });
  ["dragover", "dragenter"].forEach((t) =>
    drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); grab(e.dataTransfer); });
  function grab(dt) {
    const file = [...(dt?.files || [])].find((f) => f.type.startsWith("image/"))
      || [...(dt?.items || [])].find((i) => i.type.startsWith("image/"))?.getAsFile();
    if (file) uploadAndInsert({ file }, ta, setS);
    else setS("No image found in what you pasted/dropped.", "err");
  }

  panel.querySelector(".ip-file").addEventListener("change", (e) => {
    if (e.target.files[0]) uploadAndInsert({ file: e.target.files[0] }, ta, setS);
  });
  panel.querySelector(".ip-add").addEventListener("click", () => {
    const url = panel.querySelector(".ip-url").value.trim();
    if (url) uploadAndInsert({ url }, ta, setS);
  });
}

function insertAtCaret(ta, text) {
  const s = ta.selectionStart ?? ta.value.length;
  const e = ta.selectionEnd ?? ta.value.length;
  const before = ta.value.slice(0, s);
  const after = ta.value.slice(e);
  const lead = !before || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const trail = !after || after.startsWith("\n") ? "\n" : "\n\n";
  ta.value = before + lead + text + trail + after;
  const pos = (before + lead + text).length;
  ta.selectionStart = ta.selectionEnd = pos;
  ta.dispatchEvent(new Event("input"));
  autosize(ta);
  ta.focus();
}

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(640, Math.max(160, ta.scrollHeight + 4)) + "px";
}

function toolBtn(glyph, title, onClick) {
  const b = document.createElement("button");
  b.className = "b-tool";
  b.title = title;
  b.textContent = glyph;
  b.addEventListener("click", onClick);
  return b;
}
