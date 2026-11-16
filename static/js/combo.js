// A small single-select combobox, styled to match the rest of the app.
//
// A native <select> is skinned by the operating system while it's open — its
// font, colours and row height ignore the page's CSS — which is why the book
// switcher is built this way too (see book-picker.js). This is the same
// pattern, generalised so other fields can use it: a button showing the current
// value, and a listbox popover that can be themed.
//
// Values are plain strings. An item whose value is CUSTOM never becomes the
// selection — it just reports itself to `onSelect`, so callers can reveal an
// input for a free-form value.

export const CUSTOM = "__custom__";

export function mountCombo(root, { onSelect = () => {} } = {}) {
  root.innerHTML = `
    <button type="button" class="combo-btn" aria-haspopup="listbox" aria-expanded="false">
      <span class="combo-label">—</span>
      <span class="combo-arrow" aria-hidden="true"></span>
    </button>
    <ul class="combo-list" role="listbox" hidden></ul>`;

  const els = {
    root,
    btn: root.querySelector(".combo-btn"),
    label: root.querySelector(".combo-label"),
    list: root.querySelector(".combo-list"),
  };

  let items = [];
  let value = "";
  let isOpen = false;

  function labelFor(v) {
    const hit = items.find((i) => i.value === v);
    if (hit) return hit.label;
    // Not in the list: a free-form value the caller typed (or saved earlier),
    // shown as-is rather than pretending it's the default.
    return v || (items[0] ? items[0].label : "—");
  }

  function syncLabel() {
    els.label.textContent = labelFor(value);
  }

  function render() {
    els.list.innerHTML = "";
    for (const item of items) {
      const li = document.createElement("li");
      li.className = "combo-opt";
      li.setAttribute("role", "option");
      li.tabIndex = -1;
      li.dataset.value = item.value;
      li.textContent = item.label;
      if (item.value === CUSTOM) li.classList.add("combo-opt-custom");
      const active = item.value === value;
      li.setAttribute("aria-selected", String(active));
      if (active) li.classList.add("active");
      li.addEventListener("click", () => select(item.value));
      els.list.append(li);
    }
  }

  function select(next) {
    close();
    els.btn.focus();
    if (next === CUSTOM) { onSelect(CUSTOM); return; }   // caller decides what to do
    value = next;
    syncLabel();
    render();
    onSelect(next);
  }

  function toggle() { isOpen ? close() : openList(); }

  // The list is moved to <body> while open: containers like .topbar and the
  // modals' .glass use backdrop-filter, which makes them a containing block for
  // position:fixed descendants — a list left inside would be clipped to the
  // parent's box instead of floating over the page.
  function positionList() {
    const r = els.btn.getBoundingClientRect();
    els.list.style.left = r.left + "px";
    els.list.style.minWidth = r.width + "px";
    const below = r.bottom + 6;
    const height = els.list.offsetHeight || 200;
    // Flip above the button when there isn't room below (common in the modal).
    els.list.style.top = (below + height > window.innerHeight - 8
      ? Math.max(8, r.top - height - 6)
      : below) + "px";
  }

  function openList() {
    if (isOpen || !items.length) return;
    isOpen = true;
    document.body.append(els.list);
    els.list.hidden = false;
    // Set the stacking order here rather than relying on the stylesheet alone:
    // this control is used inside the Settings modal (z-index 50), and being a
    // <body> child only helps if it outranks whatever it covers.
    els.list.style.zIndex = "900";
    positionList();
    window.addEventListener("resize", positionList);
    window.addEventListener("scroll", positionList, true);
    els.btn.setAttribute("aria-expanded", "true");
    const idx = Math.max(0, items.findIndex((i) => i.value === value));
    const activeEl = els.list.children[idx];
    activeEl?.scrollIntoView({ block: "nearest" });
    activeEl?.focus();
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    els.list.hidden = true;
    window.removeEventListener("resize", positionList);
    window.removeEventListener("scroll", positionList, true);
    els.root.append(els.list);   // back inside the component until next time
    els.btn.setAttribute("aria-expanded", "false");
  }

  els.btn.addEventListener("click", toggle);
  els.btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openList();
    } else if (e.key === "Escape") {
      close();
    }
  });

  els.list.addEventListener("keydown", (e) => {
    const children = [...els.list.children];
    const i = children.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); (children[i + 1] || children[0])?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (children[i - 1] || children[children.length - 1])?.focus(); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.activeElement?.click(); }
    else if (e.key === "Escape") { close(); els.btn.focus(); }
    else if (e.key === "Tab") { close(); }
  });

  document.addEventListener("click", (e) => {
    if (isOpen && !els.root.contains(e.target) && !els.list.contains(e.target)) close();
  });

  return {
    /** Replace the option list: [{ value, label }]. */
    setItems(list) {
      items = list || [];
      render();
      syncLabel();
      if (isOpen) positionList();
    },
    /** Select a value without firing onSelect (used when painting saved state). */
    setValue(v) {
      value = v ?? "";
      syncLabel();
      render();
    },
    getValue: () => value,
  };
}
