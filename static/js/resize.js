// Draggable divider between the Outline and AI Assistant panels.
// Width is kept in the `--ai-pane-w` CSS var (grid track for the AI pane) and
// remembered in localStorage; a tiny inline script in index.html applies the
// saved value before first paint so there's no layout flash on reload.

const AI_W_KEY = "rextbooks:aiPaneWidth";
const MIN_W = 300;
const MAX_W = 760;

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

export function mountPaneResizer() {
  const resizer = document.getElementById("pane-resizer");
  const workspace = document.querySelector(".workspace");
  if (!resizer || !workspace) return;

  const currentWidth = () =>
    parseInt(getComputedStyle(document.documentElement).getPropertyValue("--ai-pane-w"), 10) || 384;

  // Never let the resizer squeeze the outline pane away entirely.
  const maxForViewport = () => clamp(workspace.getBoundingClientRect().width - 360, MIN_W, MAX_W);

  function apply(px) {
    const w = clamp(Math.round(px), MIN_W, maxForViewport());
    document.documentElement.style.setProperty("--ai-pane-w", w + "px");
    return w;
  }
  function persist(w) {
    try { localStorage.setItem(AI_W_KEY, String(w)); } catch {}
  }

  resizer.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 && e.button !== undefined) return;
    e.preventDefault();
    const startX = e.clientX;
    const startW = currentWidth();
    resizer.setPointerCapture(e.pointerId);
    resizer.classList.add("is-dragging");
    document.body.classList.add("is-resizing-x");

    const onMove = (ev) => persist(apply(startW - (ev.clientX - startX)));
    const onUp = () => {
      resizer.releasePointerCapture(e.pointerId);
      resizer.classList.remove("is-dragging");
      document.body.classList.remove("is-resizing-x");
      resizer.removeEventListener("pointermove", onMove);
      resizer.removeEventListener("pointerup", onUp);
      resizer.removeEventListener("pointercancel", onUp);
    };
    resizer.addEventListener("pointermove", onMove);
    resizer.addEventListener("pointerup", onUp);
    resizer.addEventListener("pointercancel", onUp);
  });

  resizer.addEventListener("dblclick", () => {
    document.documentElement.style.setProperty("--ai-pane-w", "384px");
    try { localStorage.removeItem(AI_W_KEY); } catch {}
  });

  resizer.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const step = e.key === "ArrowLeft" ? 24 : -24;   // left = divider moves left = AI pane grows
    persist(apply(currentWidth() + step));
  });

  // Keep the stored width sane if the window is resized narrower.
  window.addEventListener("resize", () => apply(currentWidth()));
}
