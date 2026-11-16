// Mobile view switching: one panel at a time, swiped or tapped like a native
// two-tab app.
//
// Everything here is inert above the 900px breakpoint — `isMobileLayout()`
// guards the JS and every visual rule lives inside the same media query in
// style.css, so the desktop layout is untouched. The swipe itself is native
// CSS scroll-snapping rather than a hand-rolled gesture handler: it gets real
// momentum and rubber-banding for free, and can't fight the vertical scrolling
// inside each panel.

const MQ = window.matchMedia("(max-width: 900px)");

let els = {};
let onViewChange = () => {};
let current = "tree";
let raf = 0;

export const isMobileLayout = () => MQ.matches;

export function mountMobileView(refs, opts = {}) {
  els = refs;
  onViewChange = opts.onViewChange || (() => {});
  const { workspace, nav, aiJump, aiPane, compactToggle } = els;
  if (!workspace || !nav) return;

  nav.addEventListener("click", (e) => {
    const btn = e.target.closest(".mobile-tab");
    if (btn) showMobileView(btn.dataset.view);
  });

  workspace.addEventListener("scroll", () => {
    if (!isMobileLayout()) return;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(syncFromScroll);
  }, { passive: true });

  aiJump?.addEventListener("click", () => showMobileView("ai"));

  // On a phone the title text is a small target, so a tap anywhere on the row
  // selects the block (which is what reveals the "AI for this block" button).
  // Re-uses the ordinary title click rather than duplicating selection logic,
  // and is skipped for controls inside the row. Desktop is unaffected: the
  // guard is the mobile breakpoint, and a click after a scroll never fires.
  els.tree?.addEventListener("click", (e) => {
    if (!isMobileLayout()) return;
    const row = e.target.closest(".block-row");
    if (!row || e.target.closest("button, input, label, a, .b-title")) return;
    row.querySelector(".b-title")?.click();
  });

  // Tone/depth/context are one tap away on a phone so the prompt box and the
  // Generate button stay above the fold.
  compactToggle?.addEventListener("click", () => {
    const open = aiPane.classList.toggle("is-compact-open");
    compactToggle.setAttribute("aria-expanded", String(open));
  });

  // Rotating or resizing across the breakpoint must not leave the carousel
  // scrolled to a stale position.
  const onLayoutChange = () => { if (!isMobileLayout()) resetScroll(); else showMobileView(current, { smooth: false }); };
  if (MQ.addEventListener) MQ.addEventListener("change", onLayoutChange);
  else MQ.addListener(onLayoutChange);
}

function panels() {
  return [...(els.workspace?.querySelectorAll(":scope > .pane") || [])];
}

function resetScroll() {
  if (els.workspace) els.workspace.scrollLeft = 0;
  setActiveTab("tree");
}

function setActiveTab(view) {
  current = view;
  for (const btn of els.nav.querySelectorAll(".mobile-tab")) {
    const active = btn.dataset.view === view;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", String(active));
  }
  onViewChange(view);
}

/** Jump to a panel. `view` is "tree" (outline) or "ai". */
export function showMobileView(view, { smooth = true } = {}) {
  if (!isMobileLayout()) return;
  const list = panels();
  const index = view === "ai" ? list.findIndex((p) => p.classList.contains("ai-pane")) : 0;
  const pane = list[index < 0 ? 0 : index];
  if (!pane) return;
  pane.scrollIntoView({
    behavior: smooth ? "smooth" : "auto",
    inline: "center",
    block: "nearest",
  });
  setActiveTab(view);
  if (view === "ai") {
    // Land with the cursor in the prompt — the whole point of jumping here.
    setTimeout(() => {
      const prompt = document.getElementById("ai-prompt");
      if (prompt && document.activeElement === document.body) prompt.focus({ preventScroll: true });
    }, smooth ? 320 : 0);
  }
}

function syncFromScroll() {
  const ws = els.workspace;
  if (!ws || !ws.clientWidth) return;
  const ratio = ws.scrollLeft / ws.clientWidth;
  const view = ratio > 0.5 ? "ai" : "tree";
  if (view !== current) setActiveTab(view);
}

/** Show/hide the floating "AI for this block" shortcut. Only rendered when a
 *  block is selected, and only on the mobile layout. */
export function updateMobileSelection(title) {
  if (!els.aiJump) return;
  const show = isMobileLayout() && !!title && title !== "Whole textbook";
  els.aiJump.hidden = !show;
  if (show) els.aiJump.title = title;
}
