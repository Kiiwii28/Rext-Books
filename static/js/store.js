// In-memory book state + tree mutations + debounced autosave + pub/sub.

import { saveBook } from "./api.js";

const listeners = new Set();
// Ephemeral "pick" state — never saved to the book.
//   pickMode:  null | "context" | "spark"
const emptyPick = () => ({
  pickMode: null,
  contextIds: [], contextTarget: null,   // extra context for the next generation
  sparkIds: [], sparkAnchor: null, sparkModalOpen: false,  // Spark cross-breed
});
let state = {
  book: null,          // { id, title, topic, nodes: [...] }
  selectedId: null,    // node id, or null = whole book
  saveStatus: "idle",  // idle | dirty | saving | saved | error
  ...emptyPick(),
};

let saveTimer = null;

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function emit() {
  for (const fn of listeners) fn(state);
}

export const getState = () => state;
export const getBook = () => state.book;
export const getSelectedId = () => state.selectedId;

// Set when a block is freshly created so the tree can drop it into edit mode.
// Peeked (not consumed) on render; cleared once the user commits or moves away.
let pendingEdit = null;
export const getPendingEdit = () => pendingEdit;
export function clearPendingEdit() { pendingEdit = null; }

export const DEFAULT_SETTINGS = { tone: "Informative", depth: "Intermediate", palette: "popular" };

export function setBook(book) {
  pendingEdit = null;
  if (book && !book.settings) book.settings = { ...DEFAULT_SETTINGS };
  else if (book) book.settings = { ...DEFAULT_SETTINGS, ...book.settings };
  state = { ...state, book, selectedId: null, saveStatus: "saved", ...emptyPick() };
  emit();
}

export const getSetting = (k) => (state.book?.settings || DEFAULT_SETTINGS)[k];

export function setSetting(k, v) {
  mutate((book) => { book.settings = { ...DEFAULT_SETTINGS, ...book.settings, [k]: v }; });
}

export function select(id) {
  if (id !== pendingEdit) pendingEdit = null;
  const changed = id !== state.selectedId;
  state = { ...state, selectedId: id, ...(changed ? emptyPick() : {}) };
  emit();
}

// ---- pick state: extra context + Spark (ephemeral, never saved) -----------

export const getPickMode = () => state.pickMode;
export const isContextPick = () => state.pickMode === "context";
export const isSparkPick = () => state.pickMode === "spark";

export const getContextIds = () => state.contextIds;
export const getContextTarget = () => state.contextTarget;
export const getSparkIds = () => state.sparkIds;
export const getSparkAnchor = () => state.sparkAnchor;
export const isSparkModalOpen = () => state.sparkModalOpen;

export function startContextPick(targetId) {
  const on = state.pickMode !== "context";
  state = { ...state, ...emptyPick(), pickMode: on ? "context" : null,
            contextIds: on ? state.contextIds : [], contextTarget: targetId ?? null };
  emit();
}

export function startSparkPick(anchorId) {
  const on = state.pickMode !== "spark";
  state = { ...state, ...emptyPick(), pickMode: on ? "spark" : null,
            sparkAnchor: anchorId ?? null };
  emit();
}

export function endPick() {
  if (!state.pickMode) return;
  state = { ...state, pickMode: null };
  emit();
}

export function toggleContext(id) {
  if (!id || id === state.contextTarget) return;
  const set = new Set(state.contextIds);
  set.has(id) ? set.delete(id) : set.add(id);
  state = { ...state, contextIds: [...set] };
  emit();
}

export function removeContext(id) {
  state = { ...state, contextIds: state.contextIds.filter((x) => x !== id) };
  emit();
}

export function clearContext() {
  state = { ...state, contextIds: [], pickMode: state.pickMode === "context" ? null : state.pickMode };
  emit();
}

export function toggleSpark(id) {
  if (!id) return;
  let ids = state.sparkIds.includes(id)
    ? state.sparkIds.filter((x) => x !== id)
    : [...state.sparkIds, id];
  if (ids.length > 2) ids = ids.slice(-2);       // keep only the two most recent
  const openModal = ids.length === 2;
  state = { ...state, sparkIds: ids, sparkModalOpen: openModal || state.sparkModalOpen,
            pickMode: openModal ? null : state.pickMode };
  emit();
}

export function removeSpark(id) {
  const ids = state.sparkIds.filter((x) => x !== id);
  state = {
    ...state, sparkIds: ids,
    sparkModalOpen: ids.length === 2 && state.sparkModalOpen,
    pickMode: ids.length < 2 ? "spark" : state.pickMode,
  };
  emit();
}

export function openSparkModal() { state = { ...state, sparkModalOpen: true, pickMode: null }; emit(); }
export function closeSpark() { state = { ...state, ...emptyPick() }; emit(); }

// ---- tree helpers ---------------------------------------------------------

const CHILD_TYPE = { heading: "subheading", subheading: "section", section: null };
export const childTypeOf = (type) => CHILD_TYPE[type] ?? null;

let idc = 0;
export function newId() {
  idc += 1;
  return `n${Date.now().toString(36)}${idc.toString(36)}`;
}

export function makeNode(type, title = "", content = "") {
  return { id: newId(), type, title, content, collapsed: false, children: [] };
}

export function walk(nodes, fn, parent = null) {
  for (const n of nodes) {
    fn(n, parent);
    walk(n.children || [], fn, n);
  }
}

export function findNode(id, nodes = state.book?.nodes || [], parent = null) {
  for (const n of nodes) {
    if (n.id === id) return { node: n, parent, siblings: nodes };
    const hit = findNode(id, n.children || [], n);
    if (hit) return hit;
  }
  return null;
}

export function pathTo(id) {
  const chain = [];
  function rec(nodes, trail) {
    for (const n of nodes) {
      const next = [...trail, n];
      if (n.id === id) { chain.push(...next); return true; }
      if (rec(n.children || [], next)) return true;
    }
    return false;
  }
  rec(state.book?.nodes || [], []);
  return chain;
}

// ---- mutations (each schedules a save) -----------------------------------

function mutate(fn) {
  if (!state.book) return;
  fn(state.book);
  state = { ...state, book: { ...state.book }, saveStatus: "dirty" };
  emit();
  if (saving) resaveQueued = true;
  else scheduleSave();
}

export function updateTitle(id, title) {
  mutate(() => { const h = findNode(id); if (h) h.node.title = title; });
}

export function setContent(id, content) {
  mutate(() => { const h = findNode(id); if (h) h.node.content = content; });
}

export function toggleCollapse(id) {
  mutate(() => { const h = findNode(id); if (h) h.node.collapsed = !h.node.collapsed; });
}

export function setAllCollapsed(collapsed) {
  mutate((book) => walk(book.nodes, (n) => {
    if ((n.children || []).length) n.collapsed = collapsed;
  }));
}

export function addChild(parentId, title = "") {
  let created = null;
  mutate((book) => {
    if (parentId == null) {
      created = makeNode("heading", title);
      book.nodes.push(created);
    } else {
      const h = findNode(parentId);
      if (!h) return;
      const ct = childTypeOf(h.node.type);
      if (!ct) return;
      created = makeNode(ct, title);
      h.node.children = h.node.children || [];
      h.node.children.push(created);
      h.node.collapsed = false;
    }
    if (created && !title) pendingEdit = created.id;
  });
  return created;
}

/** "Recurse": add a nested child subheading under a heading or subheading,
 *  so the tree can go arbitrarily deep. */
export function addRecurseChild(parentId) {
  let created = null;
  mutate(() => {
    const h = findNode(parentId);
    if (!h || (h.node.type !== "heading" && h.node.type !== "subheading")) return;
    created = makeNode("subheading", "");
    h.node.children = h.node.children || [];
    // insert before an existing section child so content stays last
    const secIdx = h.node.children.findIndex((c) => c.type === "section");
    if (secIdx === -1) h.node.children.push(created);
    else h.node.children.splice(secIdx, 0, created);
    h.node.collapsed = false;
    pendingEdit = created.id;
  });
  return created;
}

export function addSiblingAfter(id, title = "") {
  let created = null;
  mutate(() => {
    const h = findNode(id);
    if (!h) return;
    created = makeNode(h.node.type, title);
    const i = h.siblings.indexOf(h.node);
    h.siblings.splice(i + 1, 0, created);
    if (!title) pendingEdit = created.id;
  });
  return created;
}

export function removeNode(id) {
  mutate(() => {
    const h = findNode(id);
    if (!h) return;
    const i = h.siblings.indexOf(h.node);
    if (i !== -1) h.siblings.splice(i, 1);
  });
  if (state.selectedId === id) select(null);
}

/** Move `id` to be before `beforeId` among the same sibling list. */
export function reorder(id, beforeId) {
  mutate(() => {
    const src = findNode(id);
    if (!src) return;
    const i = src.siblings.indexOf(src.node);
    src.siblings.splice(i, 1);
    if (beforeId == null) {
      src.siblings.push(src.node);
    } else {
      const target = src.siblings.findIndex((n) => n.id === beforeId);
      src.siblings.splice(target === -1 ? src.siblings.length : target, 0, src.node);
    }
  });
}

/** Replace (or create) the single `section` child under a subheading. */
export function upsertSection(subheadingId, content) {
  let sec = null;
  mutate(() => {
    const h = findNode(subheadingId);
    if (!h || h.node.type !== "subheading") return;
    h.node.children = h.node.children || [];
    sec = h.node.children.find((c) => c.type === "section");
    if (!sec) {
      sec = makeNode("section", `${h.node.title} — Content`, content);
      h.node.children.push(sec);
    } else {
      sec.content = content;
    }
    h.node.collapsed = false;
  });
  return sec;
}

/** Insert a Spark result (a subheading + its content section) near `anchorId`.
 *  Returns the new subheading's id. */
export function sparkInsert(anchorId, markdown, fallbackTitle = "Synthesis") {
  const md = (markdown || "").trim();
  const m = md.match(/^#{1,2}\s+(.+?)\s*#*\s*$/m);
  let title = fallbackTitle;
  let body = md;
  if (m) {
    title = m[1].trim().slice(0, 120);
    body = md.slice(0, m.index) + md.slice(m.index + m[0].length);
    body = body.replace(/^\s+/, "");
  }

  let createdId = null;
  mutate((book) => {
    const sub = makeNode("subheading", title);
    sub.children.push(makeNode("section", `${title} — Content`, body));
    createdId = sub.id;

    const hit = anchorId ? findNode(anchorId) : null;
    if (!hit) { book.nodes.push(wrapHeading(sub, title)); return; }

    if (hit.node.type === "heading") {
      const i = book.nodes.indexOf(hit.node);
      book.nodes.splice(i + 1, 0, wrapHeading(sub, title));
    } else if (hit.node.type === "section" && hit.parent) {
      const gp = findNode(hit.parent.id);
      const list = gp ? gp.siblings : book.nodes;
      const i = list.indexOf(gp ? gp.node : hit.parent);
      list.splice(i + 1, 0, sub);
    } else { // subheading (or an orphan section)
      const i = hit.siblings.indexOf(hit.node);
      hit.siblings.splice(i + 1, 0, sub);
    }
  });
  return createdId;
}

function wrapHeading(sub, title) {
  const h = makeNode("heading", title);
  h.children.push(sub);
  return h;
}

/** Return the section under a subheading, creating an empty one if needed.
 *  Never clobbers existing content (unlike upsertSection). */
export function ensureSection(subheadingId) {
  let sec = null;
  mutate(() => {
    const h = findNode(subheadingId);
    if (!h || h.node.type !== "subheading") return;
    h.node.children = h.node.children || [];
    sec = h.node.children.find((c) => c.type === "section");
    if (!sec) {
      sec = makeNode("section", `${h.node.title} — Content`, "");
      h.node.children.push(sec);
    }
    h.node.collapsed = false;
  });
  return sec;
}

export function appendChildren(parentId, type, titles) {
  const created = [];
  mutate((book) => {
    const list = titles.map((t) => makeNode(type, t));
    created.push(...list);
    if (parentId == null) {
      book.nodes.push(...list);
    } else {
      const h = findNode(parentId);
      if (!h) return;
      h.node.children = [...(h.node.children || []), ...list];
      h.node.collapsed = false;
    }
  });
  return created;
}

// ---- autosave -----------------------------------------------------------
// Saves are serialized: never more than one PUT in flight. If edits land while
// a save is running, we re-save once it finishes with the *latest* book — so a
// stale (older) request can never be the last write to land.

let saving = false;
let resaveQueued = false;

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flush, 800);
}

export async function flush() {
  clearTimeout(saveTimer);
  if (!state.book) return;
  if (saving) { resaveQueued = true; return; }

  saving = true;
  if (state.saveStatus !== "saving") { state = { ...state, saveStatus: "saving" }; emit(); }
  try {
    await saveBook(state.book.id, state.book);   // snapshot taken here, latest
    // Don't swap the `book` reference — that forces a full tree re-render which
    // would fight an in-progress inline edit. Only the status matters.
    state = { ...state, saveStatus: resaveQueued ? "dirty" : "saved" };
  } catch (err) {
    console.error("save failed", err);
    state = { ...state, saveStatus: "error" };
  } finally {
    saving = false;
    emit();
  }
  if (resaveQueued) { resaveQueued = false; flush(); }
}

window.addEventListener("beforeunload", () => {
  if (state.saveStatus === "dirty" && state.book) {
    navigator.sendBeacon?.(
      `/api/books/${state.book.id}`,
      new Blob([JSON.stringify(state.book)], { type: "application/json" })
    );
  }
});
