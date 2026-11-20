// The mobile topbar's overflow menu.
//
// On a phone the topbar's labelled buttons (New book / Import / Export /
// Delete / Settings / theme) wrap into a crowded stack and squeeze the book
// title, so below 900px CSS hides them and reveals a ⋮ button instead. Each
// item here just clicks the matching hidden button, so every action keeps a
// single implementation — no duplicated delete-confirm, file picker or modal
// wiring to drift out of sync.
//
// Desktop never shows the button, so nothing in here runs there.

const ITEMS = {
  import: "btn-import-book",
  export: "btn-export",
  delete: "btn-delete-book",
  settings: "btn-settings",
  theme: "btn-theme",
};

export function mountMobileMenu({ button, menu, themeState, themeLabel }) {
  if (!button || !menu) return { close() {} };

  function place() {
    const r = button.getBoundingClientRect();
    menu.style.top = `${Math.round(r.bottom + 6)}px`;
    // Right-align with the ⋮ button, then keep it inside the viewport.
    const width = menu.offsetWidth || 200;
    const left = Math.min(r.right - width, window.innerWidth - width - 10);
    menu.style.left = `${Math.max(10, Math.round(left))}px`;
  }

  function open() {
    if (themeState) themeState.textContent = themeLabel ? themeLabel() : "";
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    place();
    window.addEventListener("resize", onResize);
    document.addEventListener("click", onOutsideClick, true);
  }

  function close() {
    if (menu.hidden) return;
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    window.removeEventListener("resize", onResize);
    document.removeEventListener("click", onOutsideClick, true);
  }

  function onResize() {
    // Crossing back above the breakpoint makes the button disappear; an open
    // menu anchored to nothing would be stranded over the desktop layout.
    if (window.innerWidth > 900) close();
    else place();
  }

  function onOutsideClick(e) {
    if (menu.contains(e.target) || button.contains(e.target)) return;
    close();
  }

  button.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden ? open() : close();
  });

  menu.addEventListener("click", (e) => {
    const item = e.target.closest("[data-action]");
    if (!item) return;
    close();
    const target = ITEMS[item.dataset.action];
    if (target) document.getElementById(target)?.click();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) close();
  });

  return { close };
}
