// In-memory book state + tree mutations + debounced autosave + pub/sub.

import { saveBook } from "./api.js";

const listeners = new Set();
// Ephemeral "pick" state — never saved to the book.
//   pickMode:  null | "context" | "spark" | "bulk"
const emptyPick = () => ({
  pickMode: null,
  contextIds: [], contextTarget: null,   // extra context for the next generation
  sparkIds: [], sparkAnchor: null, sparkModalOpen: false,  // Spark cross-breed
  bulkIds: [], bulkType: null, bulkParent: null,  // bulk-generate over siblings
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

export const DEFAULT_SETTINGS = {
  tone: "Informative", depth: "Intermediate", palette: "popular", overarchingPrompt: "",
  useImages: false, useWikimedia: true, usePexels: true,
  imageFrequency: "Medium", diagramFrequency: "Medium", length: "Medium",
  summarySection: true, terminologySection: false,
};

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
export const isBulkPick = () => state.pickMode === "bulk";

export const getContextIds = () => state.contextIds;
export const getContextTarget = () => state.contextTarget;
export const getSparkIds = () => state.sparkIds;
export const getSparkAnchor = () => state.sparkAnchor;
export const isSparkModalOpen = () => state.sparkModalOpen;
export const getBulkIds = () => state.bulkIds;
export const getBulkType = () => state.bulkType;

// Spark is a standalone flow (pick exactly two nodes, open a modal); it's
// mutually exclusive with context/bulk picking. Context and bulk, though, are
// meant to be used together — you can add context *for* a bulk run, and even
// tick the blocks being bulk-generated as context for one another — so
// switching between those two pickers preserves both selections.
const clearSpark = () => ({ sparkIds: [], sparkAnchor: null, sparkModalOpen: false });

export function startContextPick(targetId) {
  const on = state.pickMode !== "context";
  state = {
    ...state, ...clearSpark(),
    pickMode: on ? "context" : (state.bulkIds.length ? "bulk" : null),
    contextTarget: on ? (targetId ?? null) : null,
  };
  emit();
}

export function startSparkPick(anchorId) {
  const on = state.pickMode !== "spark";
  state = { ...state, ...emptyPick(), pickMode: on ? "spark" : null,
            sparkAnchor: anchorId ?? null };
  emit();
}

/** Enter (or leave) bulk-generate pick mode. Keeps any picked context, and
 *  returns to the context picker on exit if one was queued up too. */
export function startBulkPick() {
  const on = state.pickMode !== "bulk";
  state = {
    ...state, ...clearSpark(),
    pickMode: on ? "bulk" : (state.contextIds.length ? "context" : null),
  };
  emit();
}

/** Close whichever picker is open. Context/bulk/spark selections are kept —
 *  they're consumed (and cleared) by whatever runs the generation. */
export function endPick() {
  if (!state.pickMode) return;
  state = { ...state, pickMode: null };
  emit();
}

/** Drop the bulk queue (after it's been run, or if the user abandons it). */
export function clearBulk() {
  state = { ...state, bulkIds: [], bulkType: null, bulkParent: null,
            pickMode: state.pickMode === "bulk" ? null : state.pickMode };
  emit();
}

export function removeBulk(id) {
  const ids = state.bulkIds.filter((x) => x !== id);
  state = { ...state, bulkIds: ids,
            bulkType: ids.length ? state.bulkType : null,
            bulkParent: ids.length ? state.bulkParent : null };
  emit();
}

export function toggleContext(id) {
  if (!id || id === state.contextTarget) return;
  const hit = findNode(id);
  if (!hit) return;
  // Ticking a node ticks its whole subtree; unticking removes the subtree too.
  const affected = [id];
  walk(hit.node.children || [], (n) => affected.push(n.id));
  const set = new Set(state.contextIds);
  const turningOn = !set.has(id);
  for (const x of affected) {
    if (x === state.contextTarget) continue;
    turningOn ? set.add(x) : set.delete(x);
  }
  state = { ...state, contextIds: [...set] };
  emit();
}

export function removeContext(id) {
  const hit = findNode(id);
  const drop = new Set([id]);
  if (hit) walk(hit.node.children || [], (n) => drop.add(n.id));
  state = { ...state, contextIds: state.contextIds.filter((x) => !drop.has(x)) };
  emit();
}

/** The picked context nodes whose parent isn't also picked — for tidy chips. */
export function contextRootIds() {
  const set = new Set(state.contextIds);
  return state.contextIds.filter(
    (id) => !pathTo(id).slice(0, -1).some((a) => set.has(a.id)),
  );
}

/** A node whose children stand in for it in the bulk picker: a container of
 *  further structure (subheadings), as opposed to a leaf that holds its own
 *  content (a section, or a subheading whose content already lives in a
 *  child section). Only containers get the "select the parent, get every
 *  child" shortcut — a node with a section child must stay individually
 *  pickable, or there'd be no way to bulk-(re)generate content for several
 *  already-written subheadings at once. */
export function isBulkContainer(node) {
  const kids = node?.children || [];
  return kids.length > 0 && !kids.some((k) => k.type === "section");
}

function finalizeBulk(set) {
  let ids = [...set];
  const anchor = ids.length ? findNode(ids[0]) : null;
  if (anchor) {
    const order = anchor.siblings.map((n) => n.id);
    ids.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  }
  state = {
    ...state, bulkIds: ids,
    bulkType: anchor ? anchor.node.type : null,
    bulkParent: anchor ? (anchor.parent?.id ?? null) : null,
  };
  emit();
}

/** Picking every child of a container in one go — same "one level, one kind"
 *  rule as an individual pick, just applied to the whole group at once. */
function toggleBulkChildren(node) {
  const kids = node.children || [];
  const kidIds = kids.map((k) => k.id);
  if (!kidIds.length) return;
  if (state.bulkIds.length) {
    const first = findNode(state.bulkIds[0]);
    const sameType = first && first.node.type === kids[0].type;
    const sameParent = (first?.parent?.id ?? null) === node.id;
    if (!sameType || !sameParent) return;
  }
  const set = new Set(state.bulkIds);
  const allIn = kidIds.every((x) => set.has(x));
  for (const x of kidIds) allIn ? set.delete(x) : set.add(x);
  finalizeBulk(set);
}

/** Toggle a node in the bulk set. Constrained to siblings of one type — but
 *  clicking a container (see isBulkContainer) selects/clears its whole set
 *  of children in one go, instead of requiring each to be ticked by hand. */
export function toggleBulk(id) {
  if (!id) return;
  const hit = findNode(id);
  if (!hit) return;
  if (isBulkContainer(hit.node)) return toggleBulkChildren(hit.node);

  const set = new Set(state.bulkIds);
  if (set.has(id)) {
    set.delete(id);
  } else {
    if (state.bulkIds.length) {
      const first = findNode(state.bulkIds[0]);
      const sameType = first && first.node.type === hit.node.type;
      const sameParent = (first?.parent?.id ?? null) === (hit.parent?.id ?? null);
      if (!sameType || !sameParent) return;
    }
    set.add(id);
  }
  finalizeBulk(set);
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
