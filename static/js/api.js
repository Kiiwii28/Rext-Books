// Thin fetch wrappers around the Flask API, plus an SSE reader for generation.

async function j(res) {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json()).error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export const listBooks = () => fetch("/api/books").then(j);
export const getBook = (id) => fetch(`/api/books/${id}`).then(j);
export const createBook = (topic, title = "") =>
  fetch("/api/books", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, title }),
  }).then(j);
export const saveBook = (id, book) =>
  fetch(`/api/books/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(book),
  }).then(j);
export const deleteBook = (id) =>
  fetch(`/api/books/${id}`, { method: "DELETE" }).then(j);

export const renderMarkdown = (text) =>
  fetch("/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }).then(j).then((d) => d.html);

export const getPalettes = () => fetch("/api/palettes").then(j);
export const getHealth = () => fetch("/health").then(j);

export const getSettings = () => fetch("/api/settings").then(j);
export const saveSettings = (partial) =>
  fetch("/api/settings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(partial),
  }).then(j);
export const testApiKey = (apiKey) =>
  fetch("/api/settings/test", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey }),
  }).then(j);
export const getSparkModes = () => fetch("/api/spark-modes").then(j);
export const getVersions = (id) => fetch(`/api/books/${id}/versions`).then(j);
export const restoreVersion = (id, file) =>
  fetch(`/api/books/${id}/restore`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file }),
  }).then(j);

export function importBook(file) {
  const fd = new FormData();
  fd.append("file", file);
  return fetch("/api/books/import", { method: "POST", body: fd }).then(j);
}

/** Search for images matching a caption/keyword. `source` is "wikimedia",
 *  "pexels", or "auto" (Wikimedia first, Pexels as a fallback if it comes up short). */
export const searchImages = (query, limit = 12, source = "wikimedia") =>
  fetch(`/api/image-search?q=${encodeURIComponent(query)}&limit=${limit}&source=${source}`).then(j);

/** Upload a section image. `payload` is one of {file}, {dataUrl}, {url}. */
export function uploadImage(bookId, payload) {
  const opts = { method: "POST" };
  if (payload.file) {
    const fd = new FormData();
    fd.append("image", payload.file);
    opts.body = fd;
  } else {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(payload);
  }
  return fetch(`/api/books/${bookId}/images`, opts).then(j);
}

function withExclude(url, excludeIds) {
  if (!excludeIds || !excludeIds.length) return url;
  const sep = url.includes("?") ? "&" : "?";
  return url + sep + "exclude=" + encodeURIComponent(excludeIds.join(","));
}

/** `lite` only ever applies to pdf/epub/pages — the print fallback (see
 *  printHref) goes through the browser's own print dialog, so there's no
 *  export bytes on the server side for it to compress. `numbered` only
 *  applies to pages. */
export const exportHref = (bookId, fmt, palette, excludeIds, lite, numbered) => {
  let url = withExclude(
    fmt === "md" ? `/api/books/${bookId}/export.md`
    : fmt === "json" ? `/api/books/${bookId}/export.json`
    : fmt === "epub" ? `/api/books/${bookId}/export.epub`
    : fmt === "pages" ? `/api/books/${bookId}/export.pages`
    : `/api/books/${bookId}/export.pdf?palette=${encodeURIComponent(palette || "")}`,
    excludeIds,
  );
  if (lite && (fmt === "pdf" || fmt === "epub" || fmt === "pages")) {
    url += (url.includes("?") ? "&" : "?") + "lite=1";
  }
  if (numbered && fmt === "pages") url += (url.includes("?") ? "&" : "?") + "number=1";
  return url;
};

export const printHref = (bookId, palette, excludeIds) =>
  withExclude(`/api/books/${bookId}/preview?print=1&palette=${encodeURIComponent(palette || "")}`, excludeIds);

/**
 * Stream a generation. Returns a controller with `.abort()`.
 * Callbacks: onStart(mode), onDelta(text), onDone(fullText), onError(message),
 * onStatus(message) (an in-progress note, e.g. "Finding images…"), and
 * onRevise(fullText) — the server replacing the accumulated text wholesale
 * (image-search placeholders resolved into real Markdown, or dropped) after
 * the raw stream finishes but before "done". Kept separate from onDelta
 * rather than folded into it: onDelta is throttled by callers for the
 * partial-streamed-text case, and this final correction must never be the
 * thing that gets silently dropped by that throttle.
 */
export function streamGenerate(payload, { url = "/api/ai/generate", onStart, onDelta, onDone, onError, onStatus, onRevise } = {}) {
  const ctrl = new AbortController();
  let full = "";

  (async () => {
    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
    } catch (err) {
      if (ctrl.signal.aborted) return;
      onError?.(String(err));
      return;
    }
    if (!res.ok || !res.body) {
      let msg = `HTTP ${res.status}`;
      try { msg = (await res.json()).error || msg; } catch {}
      onError?.(msg);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          handleEvent(rawEvent);
        }
      }
    } catch (err) {
      if (!ctrl.signal.aborted) onError?.(String(err));
      return;
    }

    function handleEvent(raw) {
      let event = "message";
      const dataLines = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      let data = {};
      try { data = JSON.parse(dataLines.join("\n")); } catch { return; }

      if (event === "start") onStart?.(data.mode);
      else if (event === "delta") { full += data.text || ""; onDelta?.(data.text || "", full); }
      else if (event === "status") onStatus?.(data.message || "");
      else if (event === "revise") { full = data.text ?? full; onRevise?.(full); }
      else if (event === "done") onDone?.(full);
      else if (event === "error") onError?.(data.message || "generation failed");
    }
  })();

  return ctrl;
}
