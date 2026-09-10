// Export modal: choose format (PDF / Markdown) + colour palette, then download.

import * as store from "./store.js";
import { getPalettes, getHealth, exportHref, printHref } from "./api.js";

let els = {};
let palettes = {};
let fmt = "pdf";
let pdfNative = true;

export async function mountExport(refs) {
  els = refs;

  try { pdfNative = (await getHealth()).pdf !== false; } catch { pdfNative = false; }
  try { palettes = await getPalettes(); } catch { palettes = {}; }
  renderSwatches();

  els.openBtn.addEventListener("click", open);
  els.closeBtn.addEventListener("click", close);
  els.cancelBtn.addEventListener("click", close);
  els.backdrop.addEventListener("click", (e) => { if (e.target === els.backdrop) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.backdrop.hidden) close(); });

  els.formatSeg.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      fmt = b.dataset.fmt;
      els.formatSeg.querySelectorAll(".seg-btn").forEach((x) => x.classList.toggle("active", x === b));
      syncFormat();
    });
  });

  els.goBtn.addEventListener("click", go);
}

function renderSwatches() {
  els.grid.innerHTML = "";
  for (const [key, p] of Object.entries(palettes)) {
    const btn = document.createElement("button");
    btn.className = "swatch";
    btn.dataset.key = key;
    btn.title = p.label;
    btn.innerHTML =
      `<span class="sw-strip">` +
      [p.bg, p.heading, p.accent, p.text].map((c) => `<i style="background:${c}"></i>`).join("") +
      `</span><span class="sw-name">${p.label}</span>`;
    btn.addEventListener("click", () => {
      store.setSetting("palette", key);
      markSelected();
    });
    els.grid.append(btn);
  }
}

function markSelected() {
  const cur = store.getSetting("palette");
  els.grid.querySelectorAll(".swatch").forEach((s) => s.classList.toggle("selected", s.dataset.key === cur));
}

function syncFormat() {
  els.paletteField.hidden = fmt !== "pdf";
  if (fmt === "pdf") {
    els.note.textContent = pdfNative
      ? "A styled PDF will download — cover page, contents, working links."
      : "No PDF renderer on the server, so this opens a print-ready page — choose “Save as PDF” (turn on “Background graphics”).";
  } else if (fmt === "md") {
    els.note.textContent = "A .md file will download. Local images use absolute URLs to this server.";
  } else {
    els.note.textContent = "The raw book file — re-import it with the Import button to restore this book.";
  }
}

function open() {
  if (!store.getBook()) return;
  markSelected();
  syncFormat();
  els.backdrop.hidden = false;
}
function close() { els.backdrop.hidden = true; }

function go() {
  const book = store.getBook();
  if (!book) return;
  const palette = store.getSetting("palette");
  if (fmt === "md" || fmt === "json") {
    window.location.href = exportHref(book.id, fmt);
  } else if (pdfNative) {
    window.location.href = exportHref(book.id, "pdf", palette);
  } else {
    window.open(printHref(book.id, palette), "_blank", "noopener");
  }
  close();
}
