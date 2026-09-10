// Recursively render the outline into #tree and wire native drag-and-drop.
// Strategy: full re-render on every store change (trees are small). DnD only
// needs to compute a drop target among siblings of the same type.

import * as store from "./store.js";
import { createBlock } from "./block.js";

let container = null;
let onSelect = () => {};
let dragId = null;
let pendingRerender = null;
let editLock = false;

// Held while a section body editor is open — focus moves between the textarea,
// toolbar buttons and a file input, so the .b-title focus heuristic isn't enough.
export function setEditLock(on) {
  editLock = on;
  if (!on) forceRender();
}
export function forceRender() {
  pendingRerender = null;
  requestAnimationFrame(() => renderTree(store.getState()));
}

export function mountTree(el, { onSelect: sel }) {
  container = el;
  onSelect = sel;
  container.addEventListener("dragover", onDragOver);
  container.addEventListener("drop", onDrop);
  container.addEventListener("dragend", clearDropMarkers);
  container.addEventListener("focusout", () => {
    if (!pendingRerender) return;
    pendingRerender = null;
    requestAnimationFrame(() => renderTree(store.getState()));
  });
}

export function renderTree(state) {
  const book = state.book;

  // Don't tear down the DOM while the user is editing inside it.
  const editing = container.querySelector(".b-title.editing");
  if (editLock || (editing && container.contains(document.activeElement))) {
    pendingRerender = true;
    return;
  }
  pendingRerender = null;

  const pm = state.pickMode;  // null | "context" | "spark"
  container.classList.toggle("pick-mode", !!pm);
  container.dataset.pick = pm || "";
  container.innerHTML = "";
  if (!book || !book.nodes.length) return;

  const ctx = {
    mode: pm,
    picked: new Set(pm === "spark" ? state.sparkIds : state.contextIds || []),
    target: pm === "context" ? state.contextTarget : null,
    full: pm === "spark" && state.sparkIds.length >= 2,
  };
  const frag = document.createDocumentFragment();
  for (const node of book.nodes) frag.append(renderNode(node, state.selectedId, ctx));
  container.append(frag);

  const pe = store.getPendingEdit();
  if (pe) {
    const block = container.querySelector(`.block[data-id="${pe}"]`);
    if (block && block._beginEdit) block._beginEdit();
  }
}

function renderNode(node, selectedId, ctx) {
  const picked = ctx.picked.has(node.id);
  const block = createBlock(node, {
    selectedId,
    onChange: { select: onSelect },
    context: ctx.mode && {
      mode: ctx.mode,
      pick: true,
      picked,
      isTarget: node.id === ctx.target,
      disabled: (node.id === ctx.target) || (ctx.mode === "spark" && ctx.full && !picked),
      toggle: (id) => (ctx.mode === "spark" ? store.toggleSpark(id) : store.toggleContext(id)),
    },
  });

  wireDrag(block);

  if (block._childMount && !node.collapsed) {
    for (const child of node.children || []) {
      block._childMount.append(renderNode(child, selectedId, ctx));
    }
  }
  return block;
}

// ---- drag and drop (siblings only) -------------------------------------

function wireDrag(block) {
  const handle = block.querySelector(".b-handle");
  if (!handle) return;   // no drag handle in context-pick mode
  handle.addEventListener("dragstart", (e) => {
    dragId = block.dataset.id;
    block.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragId);
  });
  handle.addEventListener("dragend", () => {
    block.classList.remove("dragging");
    dragId = null;
    clearDropMarkers();
  });
}

function siblingContainerFor(id) {
  const hit = store.findNode(id);
  if (!hit) return null;
  const parent = hit.parent;
  if (!parent) return container;
  const pBlock = container.querySelector(`.block[data-id="${parent.id}"]`);
  return pBlock?._childMount || null;
}

function onDragOver(e) {
  if (!dragId) return;
  const list = siblingContainerFor(dragId);
  if (!list) return;
  const over = e.target.closest(".block");
  // only allow dropping within the same sibling list
  if (!over || over.parentElement !== list || over.dataset.id === dragId) {
    // still allow "drop at end" when hovering the list area
    if (e.target === list || list.contains(e.target)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      markAtEnd(list);
    }
    return;
  }
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";

  const rect = over.getBoundingClientRect();
  const after = e.clientY > rect.top + rect.height / 2;
  clearDropMarkers();
  over.classList.add(after ? "drop-after" : "drop-before");
}

function markAtEnd(list) {
  clearDropMarkers();
  const last = [...list.children].filter((c) => c.classList.contains("block")).pop();
  if (last && last.dataset.id !== dragId) last.classList.add("drop-after");
  else list.classList.add("drop-into-end");
}

function onDrop(e) {
  if (!dragId) return;
  e.preventDefault();
  const before = container.querySelector(".drop-before");
  const after = container.querySelector(".drop-after");
  let beforeId = null;
  if (before) beforeId = before.dataset.id;
  else if (after) {
    const sib = after.nextElementSibling;
    beforeId = sib && sib.classList.contains("block") ? sib.dataset.id : null;
  }
  const moving = dragId;
  clearDropMarkers();
  store.reorder(moving, beforeId);
}

function clearDropMarkers() {
  container.querySelectorAll(".drop-before,.drop-after,.drop-into-end")
    .forEach((el) => el.classList.remove("drop-before", "drop-after", "drop-into-end"));
}
