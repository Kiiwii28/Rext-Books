// Custom-styled book switcher. A native <select>'s open dropdown always
// renders with the OS's own colours/font regardless of CSS — so this is a
// small combobox instead: a button showing the current book, and a listbox
// popover styled to match the rest of the app.

let els = {};
let books = [];
let value = "";
let onChange = () => {};
let isOpen = false;

export function mountBookPicker(container, opts = {}) {
  onChange = opts.onChange || (() => {});
  container.innerHTML = `
    <button type="button" class="book-picker-btn" aria-haspopup="listbox" aria-expanded="false">
      <span class="book-picker-label">—</span>
      <span class="book-picker-arrow" aria-hidden="true"></span>
    </button>
    <ul class="book-picker-list" role="listbox" hidden></ul>`;
  els = {
    root: container,
    btn: container.querySelector(".book-picker-btn"),
    label: container.querySelector(".book-picker-label"),
    list: container.querySelector(".book-picker-list"),
  };
  container.hidden = true;

  els.btn.addEventListener("click", toggle);
  els.btn.addEventListener("keydown", onBtnKey);
  els.list.addEventListener("keydown", onListKey);
  document.addEventListener("click", (e) => { if (isOpen && !container.contains(e.target)) close(); });
}

export function setBooks(list) {
  books = list || [];
  els.root.hidden = books.length === 0;
  syncLabel();
  renderList();
}

export function setValue(id) {
  value = id;
  syncLabel();
  renderList();
}

export function getValue() { return value; }

function syncLabel() {
  const cur = books.find((b) => b.id === value);
  els.label.textContent = cur ? (cur.title || "Untitled") : "—";
}

function renderList() {
  els.list.innerHTML = "";
  for (const b of books) {
    const li = document.createElement("li");
    li.className = "book-picker-opt";
    li.setAttribute("role", "option");
    li.tabIndex = -1;
    li.dataset.id = b.id;
    li.textContent = b.title || "Untitled";
    const active = b.id === value;
    li.setAttribute("aria-selected", String(active));
    if (active) li.classList.add("active");
    li.addEventListener("click", () => select(b.id));
    els.list.append(li);
  }
}

function select(id) {
  close();
  els.btn.focus();
  if (id !== value) {
    value = id;
    syncLabel();
    renderList();
    onChange(id);
  }
}

function toggle() { isOpen ? close() : openList(); }

// The list is moved to <body> while open: .topbar uses backdrop-filter for
// its glass look, which (like any CSS filter) makes it a containing block
// for position:fixed descendants — so a fixed list left inside it would
// still be clipped to the topbar's own bounds instead of the viewport.
function positionList() {
  const r = els.btn.getBoundingClientRect();
  els.list.style.left = r.left + "px";
  els.list.style.minWidth = r.width + "px";
  els.list.style.top = r.bottom + 6 + "px";
}

function openList() {
  if (!books.length || isOpen) return;
  isOpen = true;
  document.body.append(els.list);
  els.list.hidden = false;
  positionList();
  window.addEventListener("resize", positionList);
  els.btn.setAttribute("aria-expanded", "true");
  const activeIdx = Math.max(0, books.findIndex((b) => b.id === value));
  const activeEl = els.list.children[activeIdx];
  activeEl?.scrollIntoView({ block: "nearest" });
  activeEl?.focus();
}

function close() {
  if (!isOpen) return;
  isOpen = false;
  els.list.hidden = true;
  window.removeEventListener("resize", positionList);
  els.root.append(els.list);   // back inside the component until next time
  els.btn.setAttribute("aria-expanded", "false");
}

function onBtnKey(e) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    openList();
  } else if (e.key === "Escape") {
    close();
  }
}

function onListKey(e) {
  const items = [...els.list.children];
  const i = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); (items[i + 1] || items[0])?.focus(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); (items[i - 1] || items[items.length - 1])?.focus(); }
  else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.activeElement?.click(); }
  else if (e.key === "Escape") { close(); els.btn.focus(); }
  else if (e.key === "Tab") { close(); }
}
