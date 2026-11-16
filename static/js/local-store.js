// A copy of every book this browser has opened or edited, kept in IndexedDB.
//
// The server's /api/books is still the shared, authoritative copy — but on a
// hosted instance its disk is wiped by every redeploy and (on the free tier)
// every spin-down, which silently deletes work. This vault is the safety net
// underneath that: saves are written here *before* the network call, and a
// book that the server has lost is pushed back on the next page load.
//
// Everything degrades to a no-op when IndexedDB is unavailable (private mode,
// storage disabled), so the app behaves exactly as it did before.

const DB_NAME = "rextbooks-vault";
const DB_VERSION = 1;
const STORE = "books";

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    if (typeof indexedDB === "undefined") return resolve(null);
    let req;
    try {
      req = indexedDB.open(DB_NAME, DB_VERSION);
    } catch {
      return resolve(null);
    }
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);
    req.onblocked = () => resolve(null);
  });
  return dbPromise;
}

/** Run one request in its own transaction; resolves to its result (or null). */
async function run(mode, fn) {
  const db = await openDb();
  if (!db) return null;
  return new Promise((resolve) => {
    let tx;
    try {
      tx = db.transaction(STORE, mode);
    } catch {
      return resolve(null);
    }
    let value = null;
    const req = fn(tx.objectStore(STORE));
    if (req) req.onsuccess = () => { value = req.result ?? null; };
    tx.oncomplete = () => resolve(value);
    tx.onerror = () => resolve(null);
    tx.onabort = () => resolve(null);
  });
}

/** Cache a book (the whole object, as the server would store it).
 *
 * ``dirty`` marks a copy the server has not confirmed: an edit was mirrored
 * here but the PUT that should have followed it failed (redeploy, spin-down,
 * dropped connection). On the next load a dirty record is pushed back to the
 * server even when the server still has an older copy of the same book —
 * otherwise a failed save would silently revert to that older copy. */
export async function putBook(book, { dirty = false } = {}) {
  if (!book || !book.id) return false;
  const record = {
    id: book.id,
    title: book.title || "Untitled",
    updatedAt: book.updatedAt || "",
    cachedAt: new Date().toISOString(),
    dirty,
    book,
  };
  return (await run("readwrite", (os) => os.put(record))) !== null;
}

export async function getBook(id) {
  const rec = await run("readonly", (os) => os.get(id));
  return (rec && rec.book) || null;
}

/** Every cached record, newest first — `{ id, title, updatedAt, book }`. */
export async function listBooks() {
  const all = (await run("readonly", (os) => os.getAll())) || [];
  return all.sort((a, b) => String(b.cachedAt).localeCompare(String(a.cachedAt)));
}

export async function removeBook(id) {
  return (await run("readwrite", (os) => os.delete(id))) !== null;
}
