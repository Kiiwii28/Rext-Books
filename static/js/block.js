// Render one block (heading / subheading / section) with its hover toolbar,
// plus the in-place Markdown editor + image uploader for section blocks.

import * as store from "./store.js";
import { renderMarkdown, uploadImage, searchImages } from "./api.js";
import { setEditLock } from "./tree.js";
import { renderMermaidIn } from "./mermaid-render.js";
import { applyMarkdownAction } from "./md-toolbar.js";

const TYPE_LABEL = { heading: "Heading", subheading: "Subheading", section: "Section" };
const EDITOR_HEIGHT_KEY = "rextbooks:editorHeight";   // remembered manual editor height, in px
const FS_SPLIT_KEY = "rextbooks:fsSplit";     // remembered fullscreen editor/preview split, 0..1
const FS_VIEW_KEY = "rextbooks:fsView";       // remembered fullscreen view mode: split | raw | preview

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
  if (pick && context.mode === "bulk" && context.indeterminate) wrap.classList.add("is-bulk-partial");
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
    checkbox.indeterminate = !!context.indeterminate;
    checkbox.disabled = !!context.disabled;
    checkbox.title = context.isTarget
      ? "This is the block you're generating on"
      : context.disabled
        ? (context.mode === "spark" ? "Spark takes exactly two blocks"
           : context.mode === "bulk" ? "Bulk generate needs siblings of the same kind"
           : "Use as context")
      : context.mode === "spark" ? "Pick for Spark"
      : context.mode === "bulk" && context.indeterminate ? "Some children included — click to select the rest"
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
    if (pick || node.type !== "section" || wrap.dataset.editing) return;
    wrap.dataset.editing = "1";
    setEditLock(true);
    body.hidden = true;

    const ed = document.createElement("div");
    ed.className = "b-section-edit";
    ed.innerHTML = `
      <div class="b-edit-head">
        <div class="b-edit-bar">
          <button class="b-tool" data-act="image" title="Insert an image">🖼&nbsp;Image</button>
          <span class="b-edit-hint">Markdown — you can also paste an image straight in</span>
          <span class="flex"></span>
          <div class="b-view-seg segmented" hidden>
            <button type="button" class="seg-btn" data-view="split">Split</button>
            <button type="button" class="seg-btn" data-view="raw">Raw</button>
            <button type="button" class="seg-btn" data-view="preview">Preview</button>
          </div>
          <button class="b-tool" data-act="fullscreen" title="Expand editor">⛶</button>
          <button class="btn ghost sm" data-act="cancel">Cancel</button>
          <button class="btn primary sm" data-act="done">Done</button>
        </div>
        <div class="b-image-panel" hidden></div>
        <div class="b-md-toolbar">
          <button class="b-tool" data-md="h1" title="Heading 1">H1</button>
          <button class="b-tool" data-md="h2" title="Heading 2">H2</button>
          <button class="b-tool" data-md="h3" title="Heading 3">H3</button>
          <button class="b-tool" data-md="h4" title="Heading 4">H4</button>
          <button class="b-tool" data-md="h5" title="Heading 5">H5</button>
          <button class="b-tool" data-md="h6" title="Heading 6">H6</button>
          <span class="md-sep"></span>
          <button class="b-tool md-bold" data-md="bold" title="Bold (Ctrl+B)">B</button>
          <button class="b-tool md-italic" data-md="italic" title="Italic (Ctrl+I)">I</button>
          <button class="b-tool md-strike" data-md="strike" title="Strikethrough">S</button>
          <button class="b-tool md-code" data-md="code" title="Inline code">&lt;/&gt;</button>
          <span class="md-sep"></span>
          <button class="b-tool" data-md="ul" title="Bulleted list">•︲list</button>
          <button class="b-tool" data-md="ol" title="Numbered list">1.list</button>
          <button class="b-tool" data-md="quote" title="Blockquote">❝</button>
          <span class="md-sep"></span>
          <button class="b-tool" data-md="link" title="Link (Ctrl+K)">🔗</button>
          <button class="b-tool" data-md="table" title="Insert table">▦&nbsp;Table</button>
          <button class="b-tool" data-md="codeblock" title="Code block">{ }</button>
          <button class="b-tool" data-md="hr" title="Horizontal rule">―</button>
        </div>
      </div>
      <textarea class="b-section-editor" spellcheck="true"></textarea>
      <div class="b-resize-handle" tabindex="0" role="separator" aria-orientation="horizontal"
           aria-label="Resize editor" title="Drag to resize · double-click to reset"></div>
      <div class="b-edit-preview markdown-body"></div>`;

    const ta = ed.querySelector(".b-section-editor");
    const preview = ed.querySelector(".b-edit-preview");
    const imagePanel = ed.querySelector(".b-image-panel");
    const resizeHandle = ed.querySelector(".b-resize-handle");
    const fsBtn = ed.querySelector('[data-act="fullscreen"]');
    const viewSeg = ed.querySelector(".b-view-seg");
    ta.value = node.content || "";

    // A manually-chosen height (drag, or remembered from last time) sticks —
    // typing no longer snaps it back to the auto-fit size.
    let manualHeight = readSavedHeight();
    if (manualHeight) ta.style.height = manualHeight + "px";
    else autosize(ta);

    let fullscreen = false;
    let backdrop = null;
    let swapModal = null;   // built lazily on first double-click, reused after that

    // ---- fullscreen: adjustable editor/preview split + view mode ----------
    let fsSplit = readSavedSplit();        // fraction of the split the editor pane gets, 0..1
    let viewMode = readSavedView();        // "split" | "raw" | "preview" — fullscreen only
    ed.classList.add(`view-${viewMode}`);
    viewSeg.querySelectorAll("[data-view]").forEach(
      (b) => b.classList.toggle("active", b.dataset.view === viewMode));

    function applyFsSplit() {
      ta.style.flex = `1 1 ${(fsSplit * 100).toFixed(2)}%`;
      preview.style.flex = `1 1 ${((1 - fsSplit) * 100).toFixed(2)}%`;
    }
    applyFsSplit();

    function setViewMode(mode) {
      viewMode = mode;
      ed.classList.remove("view-split", "view-raw", "view-preview");
      ed.classList.add(`view-${mode}`);
      viewSeg.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === mode));
      try { localStorage.setItem(FS_VIEW_KEY, mode); } catch {}
      if (mode !== "preview") ta.focus();
    }
    viewSeg.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-view]");
      if (btn) setViewMode(btn.dataset.view);
    });

    let t;
    const refreshPreview = () => {
      clearTimeout(t);
      t = setTimeout(() => renderInto(preview, ta.value), 300);
    };
    refreshPreview();
    ta.addEventListener("input", () => {
      if (manualHeight == null) autosize(ta);
      refreshPreview();
    });

    // ---- double-click an inserted image to swap it for a different one ----
    preview.addEventListener("dblclick", (e) => {
      const img = e.target.closest("img");
      if (!img) return;
      const idx = [...preview.querySelectorAll("img")].indexOf(img);
      if (idx !== -1) openImageSwap(idx);
    });

    function openImageSwap(idx) {
      // The preview is rendered from this same Markdown in document order, so
      // the Nth <img> in the DOM corresponds to the Nth ![...](...) match here.
      const matches = [...ta.value.matchAll(/!\[([^\]]*)\]\(([^)]+)\)/g)];
      const match = matches[idx];
      if (!match) return;
      const start = match.index;
      const end = start + match[0].length;
      // A following "\n*attribution*" caption line (this app's own insert
      // format) gets replaced along with the image, not left orphaned.
      const capMatch = ta.value.slice(end).match(/^\n\*[^\n]*\*/);
      const replaceEnd = end + (capMatch ? capMatch[0].length : 0);
      const currentAlt = match[1];

      if (!swapModal) swapModal = buildSwapModal();
      swapModal.open(currentAlt, async (it) => {
        const res = await uploadImage(store.getBook()?.id, { url: it.fullUrl });
        const alt = (it.title || "").replace(/[[\]]/g, "");
        const replacement = `![${alt}](${res.url})\n*${it.attribution}*`;
        ta.setRangeText(replacement, start, replaceEnd, "end");
        ta.dispatchEvent(new Event("input"));
      });
    }

    function buildSwapModal() {
      const backdropEl = document.createElement("div");
      backdropEl.className = "modal-backdrop ip-swap-backdrop";
      backdropEl.innerHTML = `
        <div class="modal modal-wide glass" role="dialog" aria-modal="true" aria-label="Replace image">
          <div class="modal-head">
            <h2>Replace image</h2>
            <button type="button" class="mini-btn ip-swap-close" aria-label="Close">✕</button>
          </div>
          <div class="modal-body">
            <div class="ip-swap-search"></div>
          </div>
        </div>`;
      document.body.append(backdropEl);

      let onPickCallback = null;
      const search = mountImageSearch(backdropEl.querySelector(".ip-swap-search"), {
        onPick: async (it, card, setSearchStatus) => {
          card.disabled = true;
          setSearchStatus("Replacing…", "busy");
          try {
            await onPickCallback?.(it);
            closeModal();
          } catch (err) {
            setSearchStatus(String(err.message || err), "err");
            card.disabled = false;
          }
        },
      });

      function closeModal() { backdropEl.hidden = true; }
      backdropEl.querySelector(".ip-swap-close").addEventListener("click", closeModal);
      backdropEl.addEventListener("click", (e) => { if (e.target === backdropEl) closeModal(); });

      return {
        el: backdropEl,
        open(startingQuery, onPick) {
          onPickCallback = onPick;
          search.setQuery(startingQuery || "");
          backdropEl.hidden = false;
        },
      };
    }

    ta.addEventListener("paste", (e) => {
      const file = [...(e.clipboardData?.items || [])]
        .find((i) => i.type.startsWith("image/"))?.getAsFile();
      if (!file) return;
      e.preventDefault();
      uploadAndInsert({ file }, ta);
    });

    // ---- drag-to-resize the textarea's height ----------------------------
    function maxHeight() { return Math.max(window.innerHeight - 200, 300); }
    function setHeight(px) {
      manualHeight = Math.min(Math.max(px, 120), maxHeight());
      ta.style.height = manualHeight + "px";
      try { localStorage.setItem(EDITOR_HEIGHT_KEY, String(Math.round(manualHeight))); } catch {}
    }
    // In fullscreen, the same handle instead drags the editor/preview split —
    // a fraction of the two panes' combined height, so it survives window
    // resizes cleanly (unlike a fixed pixel height).
    function setSplit(taPx, combinedPx) {
      fsSplit = Math.min(Math.max(taPx / combinedPx, 0.15), 0.85);
      applyFsSplit();
      try { localStorage.setItem(FS_SPLIT_KEY, fsSplit.toFixed(4)); } catch {}
    }
    resizeHandle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const startY = e.clientY;
      resizeHandle.setPointerCapture(e.pointerId);
      document.body.classList.add("is-resizing-y");

      if (fullscreen) {
        const combined = ta.getBoundingClientRect().height + preview.getBoundingClientRect().height;
        const startTa = ta.getBoundingClientRect().height;
        const onMove = (ev) => setSplit(startTa + (ev.clientY - startY), combined);
        const onUp = () => {
          resizeHandle.releasePointerCapture(e.pointerId);
          document.body.classList.remove("is-resizing-y");
          resizeHandle.removeEventListener("pointermove", onMove);
          resizeHandle.removeEventListener("pointerup", onUp);
          resizeHandle.removeEventListener("pointercancel", onUp);
        };
        resizeHandle.addEventListener("pointermove", onMove);
        resizeHandle.addEventListener("pointerup", onUp);
        resizeHandle.addEventListener("pointercancel", onUp);
        return;
      }

      const startH = ta.getBoundingClientRect().height;
      const onMove = (ev) => setHeight(startH + (ev.clientY - startY));
      const onUp = () => {
        resizeHandle.releasePointerCapture(e.pointerId);
        document.body.classList.remove("is-resizing-y");
        resizeHandle.removeEventListener("pointermove", onMove);
        resizeHandle.removeEventListener("pointerup", onUp);
        resizeHandle.removeEventListener("pointercancel", onUp);
      };
      resizeHandle.addEventListener("pointermove", onMove);
      resizeHandle.addEventListener("pointerup", onUp);
      resizeHandle.addEventListener("pointercancel", onUp);
    });
    resizeHandle.addEventListener("dblclick", () => {
      if (fullscreen) {
        fsSplit = 0.45;
        applyFsSplit();
        try { localStorage.removeItem(FS_SPLIT_KEY); } catch {}
        return;
      }
      manualHeight = null;
      try { localStorage.removeItem(EDITOR_HEIGHT_KEY); } catch {}
      autosize(ta);
    });
    resizeHandle.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      if (fullscreen) {
        const combined = ta.getBoundingClientRect().height + preview.getBoundingClientRect().height;
        setSplit(ta.getBoundingClientRect().height + (e.key === "ArrowDown" ? 16 : -16), combined);
        return;
      }
      setHeight(ta.getBoundingClientRect().height + (e.key === "ArrowDown" ? 24 : -24));
    });

    // ---- fullscreen: a lot more room, for longer or fiddlier edits -------
    // Panes use `backdrop-filter` (the "glass" look), which makes them a
    // containing block for `position: fixed` descendants — so the editor has
    // to actually move to <body> while fullscreen, not just gain a class,
    // or it ends up pinned inside the (blurred) pane instead of the viewport.
    function setFullscreen(on) {
      fullscreen = on;
      ed.classList.toggle("is-fullscreen", on);
      fsBtn.classList.toggle("active", on);
      fsBtn.title = on ? "Collapse editor" : "Expand editor";
      viewSeg.hidden = !on;   // Split/Raw/Preview only make sense with room to spare
      if (on) {
        applyFsSplit();
        backdrop = document.createElement("div");
        backdrop.className = "b-edit-fs-backdrop";
        backdrop.addEventListener("click", () => setFullscreen(false));
        document.body.append(backdrop, ed);
      } else {
        backdrop?.remove();
        backdrop = null;
        body.parentNode.insertBefore(ed, body.nextSibling);   // back to its spot in the tree
      }
      if (viewMode !== "preview") ta.focus();
    }

    ed.querySelector(".b-edit-bar").addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "done") close(ta.value);
      else if (act === "cancel") close(null);
      else if (act === "fullscreen") setFullscreen(!fullscreen);
      else if (act === "image") {
        imagePanel.hidden = !imagePanel.hidden;
        if (!imagePanel.hidden && !imagePanel.dataset.built) {
          buildImagePanel(imagePanel, ta);
          imagePanel.dataset.built = "1";
        }
      }
    });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); fullscreen ? setFullscreen(false) : close(null); }
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); close(ta.value); }
      if (e.ctrlKey || e.metaKey) {
        const k = e.key.toLowerCase();
        const shortcut = { b: "bold", i: "italic", k: "link" }[k];
        if (shortcut) { e.preventDefault(); applyMarkdownAction(ta, shortcut); }
      }
    });

    // ---- markdown formatting toolbar --------------------------------------
    const mdToolbar = ed.querySelector(".b-md-toolbar");
    // Buttons must not steal focus/selection from the textarea before the
    // action runs — a mousedown on a button blurs the textarea by default.
    mdToolbar.addEventListener("mousedown", (e) => e.preventDefault());
    mdToolbar.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-md]");
      if (!btn) return;
      applyMarkdownAction(ta, btn.dataset.md);
    });

    function close(value) {
      backdrop?.remove();
      swapModal?.el.remove();   // it's parked in <body>, not inside `ed`
      ed.remove();   // detach whether it's still in the tree or parked in <body> (fullscreen)
      delete wrap.dataset.editing;
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
      <button class="ip-tab" data-tab="search">Search</button>
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
      <div data-pane="search" hidden></div>
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

  // ---- image search: shared UI (also used by the double-click swap modal) --
  mountImageSearch(panel.querySelector('[data-pane="search"]'), {
    onPick: async (it, card, setSearchStatus) => {
      card.disabled = true;
      setSearchStatus("Adding…", "busy");
      try {
        const res = await uploadImage(store.getBook()?.id, { url: it.fullUrl });
        const alt = (it.title || "").replace(/[[\]]/g, "");
        // Attribution travels with the image as a caption line — required for
        // most Wikimedia Commons licences, and good practice for Pexels too.
        insertAtCaret(ta, `![${alt}](${res.url})\n*${it.attribution}*`);
        setSearchStatus("Image inserted ✓", "ok");
      } catch (err) {
        setSearchStatus(String(err.message || err), "err");
        card.disabled = false;
      }
    },
  });
}

/** Mounts the Wikimedia/Pexels search UI (source toggle, query box, result
 *  grid, status line) into `container`. `onPick(item, card, setStatus)` is
 *  called when a result is clicked — the caller decides what "picking"
 *  means (insert at the caret vs. replace an existing image), and gets the
 *  clicked card (to disable it) and this UI's own status-line setter to
 *  report progress/errors through the same line search errors use. Returns
 *  `{ setQuery(q) }` so a caller (the swap modal) can seed a starting query. */
function mountImageSearch(container, { onPick }) {
  container.innerHTML = `
    <div class="segmented ip-search-source" role="tablist">
      <button class="seg-btn active" data-source="wikimedia" role="tab" type="button">Wikimedia</button>
      <button class="seg-btn" data-source="pexels" role="tab" type="button">Pexels</button>
    </div>
    <div class="ip-link-row">
      <input type="text" class="ip-search-q" placeholder="e.g. neuron diagram, mitochondria, city skyline">
      <button class="btn primary sm ip-search-go">Search</button>
    </div>
    <div class="ip-search-results"></div>
    <div class="ip-status" hidden></div>`;

  const status = container.querySelector(".ip-status");
  const setS = (m, k = "") => { status.hidden = !m; status.textContent = m || ""; status.className = `ip-status ${k}`; };
  const searchInput = container.querySelector(".ip-search-q");
  const searchGoBtn = container.querySelector(".ip-search-go");
  const results = container.querySelector(".ip-search-results");
  const sourceBtns = container.querySelectorAll(".ip-search-source .seg-btn");
  let searchSource = "wikimedia";

  sourceBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.source === searchSource) return;
      searchSource = btn.dataset.source;
      sourceBtns.forEach((b) => b.classList.toggle("active", b === btn));
      results.innerHTML = "";
      setS("");
      if (searchInput.value.trim()) runSearch();
    });
  });

  async function runSearch() {
    const q = searchInput.value.trim();
    if (!q) return;
    results.innerHTML = "";
    searchGoBtn.disabled = true;
    setS("Searching…", "busy");
    try {
      const { results: items, pexelsConfigured } = await searchImages(q, 12, searchSource);
      renderResults(items);
      setS(
        items.length ? "" :
        searchSource === "pexels" && !pexelsConfigured ? "No Pexels API key configured yet — add one in ⚙ Settings." :
        searchSource === "pexels" ? "No results — try different words." :
          "No results — try different words, or switch to Pexels above.",
        items.length ? "" : "err",
      );
    } catch (err) {
      setS(String(err.message || err), "err");
    } finally {
      searchGoBtn.disabled = false;
    }
  }
  searchGoBtn.addEventListener("click", runSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); runSearch(); }
  });

  function renderResults(items) {
    results.innerHTML = "";
    for (const it of items) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "ip-result";
      card.title = it.attribution || it.title || "";
      card.innerHTML =
        `<img src="${it.thumbUrl}" alt="" loading="lazy">` +
        `<span class="ip-result-src ip-result-src-${it.source}">${it.source === "wikimedia" ? "Wikimedia" : "Pexels"}</span>`;
      card.addEventListener("click", () => onPick(it, card, setS));
      results.append(card);
    }
  }

  return {
    setQuery(q) { searchInput.value = q || ""; },
  };
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
  ta.dispatchEvent(new Event("input"));   // re-renders the preview; resizes unless the user set a manual height
  ta.focus();
}

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(640, Math.max(160, ta.scrollHeight + 4)) + "px";
}

function readSavedHeight() {
  try {
    const v = parseInt(localStorage.getItem(EDITOR_HEIGHT_KEY) || "", 10);
    return Number.isFinite(v) && v >= 120 ? v : null;
  } catch {
    return null;
  }
}

function readSavedSplit() {
  try {
    const v = parseFloat(localStorage.getItem(FS_SPLIT_KEY) || "");
    return Number.isFinite(v) && v >= 0.15 && v <= 0.85 ? v : 0.45;
  } catch {
    return 0.45;
  }
}

function readSavedView() {
  try {
    const v = localStorage.getItem(FS_VIEW_KEY);
    return v === "raw" || v === "preview" ? v : "split";
  } catch {
    return "split";
  }
}

function toolBtn(glyph, title, onClick) {
  const b = document.createElement("button");
  b.className = "b-tool";
  b.title = title;
  b.textContent = glyph;
  b.addEventListener("click", onClick);
  return b;
}
