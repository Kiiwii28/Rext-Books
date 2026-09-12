// Guided tutorial: a spotlighted, step-by-step walk through the app's
// features. Purely descriptive — the only thing it does to your actual book
// is expand the outline once at the start (so block-level steps have
// something real to point at); it never fakes clicks or triggers a
// generation on your behalf.

import * as store from "./store.js";

const PAD = 8;   // breathing room around the spotlighted element, in px

// Each step is either informational (`target: null`, shown centered) or
// points at a real element. `target` can be a selector string or a function
// (for "the first block", etc.) so a step can be skipped gracefully if
// nothing matching exists yet — e.g. no book open, or no section written.
const STEPS = [
  {
    title: "Welcome to Rextbooks 👋",
    body: "A quick walk through the outline, the AI assistant, and the " +
      "features layered on top. <b>Next</b> moves through it, <b>Skip</b> " +
      "ends it at any point — and this button always picks the tour back " +
      "up from here. A few steps only appear once a book with some " +
      "content is open.",
    target: null,
  },
  {
    title: "Your books",
    body: "Switch between saved books here. Everything autosaves as you " +
      "go, and older versions are kept automatically so a bad edit isn't " +
      "the end of the world.",
    target: "#book-picker",
  },
  {
    title: "New book",
    body: "Give it a topic and generate a starting outline — chapters " +
      "first, then subheadings and content underneath as you go.",
    target: "#btn-new-book",
  },
  {
    title: "Import",
    body: "Bring in a book exported earlier as a <b>.json</b> file — for " +
      "backups, or moving a book to another machine.",
    target: "#btn-import-book",
  },
  {
    title: "Export",
    body: "Download as a <b>PDF</b> (15 colour palettes, and a proper " +
      "bookmarks/navigation pane built from your headings), " +
      "<b>Markdown</b>, or the raw <b>JSON</b>.",
    target: "#btn-export",
  },
  {
    title: "Delete",
    body: "Removes the current book. Every save drops an automatic " +
      "snapshot first, so this is safer than it sounds.",
    target: "#btn-delete-book",
  },
  {
    title: "Settings",
    body: "Set or swap your DeepSeek API key here any time — takes effect " +
      "immediately, no restart needed.",
    target: "#btn-settings",
  },
  {
    title: "Theme",
    body: "Cycles through <b>Auto</b> (follows your system), <b>Light</b>, " +
      "and <b>Dark</b>.",
    target: "#btn-theme",
  },
  {
    title: "Resize the panels",
    body: "Drag this divider to give the outline or the AI panel more " +
      "room. Double-click it to reset the split.",
    target: "#pane-resizer",
  },
  {
    title: "Expand / collapse all",
    body: "Fold the whole outline down to just its headings, or open " +
      "everything back up, in one click.",
    target: ".tree-pane .pane-header-actions",
  },
  {
    title: "Your outline",
    body: "Each row is a block — a heading, a subheading, or a section of " +
      "body text. Click one to select it; the AI panel on the right " +
      "updates to match what you can generate for it.",
    target: () => document.querySelector(".tree .block"),
  },
  {
    title: "Has content?",
    body: "A bigger, dark-green chevron means something's already nested " +
      "underneath — a quick visual cue for which parts of the outline are " +
      "actually filled in.",
    target: () => document.querySelector(".tree .b-chevron.has-content"),
  },
  {
    title: "Block toolbar",
    body: "Hover any block to reveal: <b>✎</b> rename, <b>＋</b> add a " +
      "child, <b>↳</b> Recurse (nest a sub-topic underneath — trees can go " +
      "arbitrarily deep), <b>⧉</b> duplicate as a sibling, <b>🗑</b> delete.",
    target: () => document.querySelector(".tree .block .b-tools"),
  },
  {
    title: "Reorder",
    body: "Drag the ⠿ handle to move a block among its siblings.",
    target: () => document.querySelector(".tree .block .b-handle"),
  },
  {
    title: "Mode",
    body: "Shows what the AI panel is currently set up to generate — " +
      "outline, sub-topics, or content — decided automatically by " +
      "whatever's selected on the left.",
    target: "#ai-mode-chip",
  },
  {
    title: "Overarching prompt",
    body: "A standing instruction applied to <b>every</b> generation for this " +
      "book, so you don't have to keep retyping it — things like “consider a " +
      "historical perspective” or “don't use em-dashes.” Click to open it; " +
      "it stays put no matter what you click on next, and travels with the " +
      "book. <b>Clear</b> wipes it.",
    target: "#ai-overarching-toggle",
  },
  {
    title: "Tone & depth",
    body: "Pick a writing tone and a difficulty level. Every generation " +
      "uses these, and they're remembered per book.",
    target: ".ai-tags",
  },
  {
    title: "Extra context",
    body: "Feed other parts of the book into a generation as background. " +
      "Tick a heading and its whole subtree comes with it — untick " +
      "anything you don't want. Good for keeping terminology and tone " +
      "consistent across chapters.",
    target: "#btn-add-context",
  },
  {
    title: "⚡ Spark",
    body: "Pick exactly two blocks and one of ten modes (Contrarian, " +
      "Socratic Questioning, Metaphor Mapping, and more) to synthesise a " +
      "genuinely new section out of both.",
    target: "#btn-spark",
  },
  {
    title: "⧉ Bulk",
    body: "Select several sibling blocks and generate all of them — each " +
      "its own separate request, run one after another, sharing the same " +
      "tone, depth and context. You can even tick the blocks being " +
      "generated as context for one another.",
    target: "#btn-bulk",
  },
  {
    title: "The prompt",
    body: "Fully editable. Rules that keep the app working (output " +
      "format, scope) can't be overridden — but style, length, how many " +
      "diagrams or images, and everything else is yours to change, right " +
      "here in plain English.",
    target: "#ai-prompt",
  },
  {
    title: "Generate",
    body: "Streams the result straight into the outline. If a section " +
      "already has content, you'll get a <b>Replace</b> vs <b>Refine</b> " +
      "choice first.",
    target: "#btn-generate",
  },
  {
    title: "Editing a section",
    body: "Double-click a section's text (or its ✎ button) to open the " +
      "Markdown editor — live preview, an image picker, drag-to-resize, " +
      "and a <b>⛶</b> button to expand it to fill the screen for longer " +
      "edits.",
    target: () => document.querySelector(".tree .block-section .b-section-body"),
  },
  {
    title: "That's the tour",
    body: "Come back to this button any time — it always starts fresh " +
      "from the top. Happy writing!",
    target: null,
  },
];

let els = null;          // { top, bottom, left, right, shield, card, ... }
let activeIndices = [];
let pos = 0;
let spotlightEl = null;

function resolveTarget(step) {
  if (!step.target) return null;
  const el = typeof step.target === "function" ? step.target() : document.querySelector(step.target);
  return el && el.offsetParent !== null ? el : null;
}

export function mountTour(button) {
  button?.addEventListener("click", start);
}

function start() {
  if (store.getBook()) store.setAllCollapsed(false);   // give every step something to point at
  activeIndices = STEPS.map((_, i) => i).filter((i) => !STEPS[i].target || resolveTarget(STEPS[i]));
  if (!activeIndices.length) return;
  pos = 0;
  buildOverlay();
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", onResize);
  render();
}

function end() {
  document.removeEventListener("keydown", onKey);
  window.removeEventListener("resize", onResize);
  spotlightEl?.classList.remove("tour-spotlight");
  spotlightEl = null;
  els?.root.remove();
  els = null;
}

function onKey(e) {
  if (e.key === "Escape") end();
  else if (e.key === "Enter") goNext();
  else if (e.key === "ArrowRight") goNext();
  else if (e.key === "ArrowLeft") goBack();
}

function onResize() {
  const step = STEPS[activeIndices[pos]];
  const target = resolveTarget(step);
  layout(target, step);
}

function goNext() {
  if (pos < activeIndices.length - 1) { pos++; render(); }
  else end();
}
function goBack() {
  if (pos > 0) { pos--; render(); }
}

function buildOverlay() {
  const root = document.createElement("div");
  root.className = "tour-root";
  const strip = (cls) => { const d = document.createElement("div"); d.className = cls; return d; };
  // `blocker` swallows clicks everywhere (full viewport, invisible); `hole`
  // is the purely-visual dark surround with an actual rounded-rect cutout —
  // a single box-shadow spread big enough to blanket the viewport, clipped
  // to the box's own border-radius, so the cutout's corners are properly
  // rounded (four separate rectangular mask strips can't do that: their
  // straight edges always meet in a square notch, no matter the target's
  // own rounding).
  const blocker = strip("tour-blocker");
  const hole = strip("tour-hole");

  const card = document.createElement("div");
  card.className = "tour-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  card.setAttribute("aria-label", "Tutorial");
  card.innerHTML = `
    <div class="tour-card-head">
      <span class="tour-counter"></span>
      <button class="tour-skip" type="button">Skip</button>
    </div>
    <h3 class="tour-title"></h3>
    <p class="tour-body"></p>
    <div class="tour-card-foot">
      <button class="tour-back btn ghost sm" type="button">Back</button>
      <button class="tour-next btn primary sm sheen" type="button">Next</button>
    </div>`;

  card.querySelector(".tour-skip").addEventListener("click", end);
  card.querySelector(".tour-back").addEventListener("click", goBack);
  card.querySelector(".tour-next").addEventListener("click", goNext);

  root.append(blocker, hole, card);
  document.body.append(root);
  els = { root, blocker, hole, card };
}

async function render() {
  const myPos = pos;   // snapshot — a newer render() (rapid Next/Back/Skip) can outrace this one
  const step = STEPS[activeIndices[myPos]];

  spotlightEl?.classList.remove("tour-spotlight");
  spotlightEl = resolveTarget(step);
  spotlightEl?.classList.add("tour-spotlight");
  spotlightEl?.scrollIntoView({ block: "center" });

  // let the scroll (if any) and layout settle before measuring positions
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

  // the tour may have moved on (or ended) while we were waiting — a stale
  // render must not overwrite what the newer one already drew
  if (!els || myPos !== pos) return;

  els.card.querySelector(".tour-counter").textContent = `${myPos + 1} / ${activeIndices.length}`;
  els.card.querySelector(".tour-title").textContent = step.title;
  els.card.querySelector(".tour-body").innerHTML = step.body;
  els.card.querySelector(".tour-back").disabled = myPos === 0;
  els.card.querySelector(".tour-next").textContent = myPos === activeIndices.length - 1 ? "Done" : "Next";

  layout(spotlightEl, step);
}

function setRect(el, x, y, w, h) {
  el.style.left = x + "px";
  el.style.top = y + "px";
  el.style.width = Math.max(w, 0) + "px";
  el.style.height = Math.max(h, 0) + "px";
}

function layout(target, step) {
  if (!els) return;
  const vw = window.innerWidth, vh = window.innerHeight;

  if (!target) {
    // Zero-size hole, centered — the box-shadow spread still blankets the
    // whole viewport uniformly (no rounding artifacts on a zero-size box),
    // giving the same full-screen dim as before for informational steps.
    setRect(els.hole, vw / 2, vh / 2, 0, 0);
  } else {
    const r = target.getBoundingClientRect();
    const top = Math.max(r.top - PAD, 0);
    const bottom = Math.min(r.bottom + PAD, vh);
    const left = Math.max(r.left - PAD, 0);
    const right = Math.min(r.right + PAD, vw);
    setRect(els.hole, left, top, right - left, bottom - top);
  }

  positionCard(target);
}

function positionCard(target) {
  const card = els.card;
  const cw = card.offsetWidth, ch = card.offsetHeight;
  const margin = 14;
  const vw = window.innerWidth, vh = window.innerHeight;

  if (!target) {
    card.style.top = "50%";
    card.style.left = "50%";
    card.style.transform = "translate(-50%, -50%)";
    return;
  }
  card.style.transform = "none";

  const r = target.getBoundingClientRect();
  const spaceBelow = vh - r.bottom;
  const spaceAbove = r.top;
  let top;
  if (spaceBelow >= ch + margin + PAD || spaceBelow >= spaceAbove) {
    top = Math.min(r.bottom + PAD + margin, vh - ch - 10);
  } else {
    top = Math.max(r.top - PAD - margin - ch, 10);
  }
  const left = Math.min(Math.max(r.left + r.width / 2 - cw / 2, 10), vw - cw - 10);
  card.style.top = Math.max(top, 10) + "px";
  card.style.left = left + "px";
}
