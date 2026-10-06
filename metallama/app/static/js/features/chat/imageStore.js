// Content-addressed image store for the chat page.
//
// Pixels are kept out of the conversation JSON (which lives in localStorage and
// is limited to a few MB). Images are stored as Blobs in IndexedDB, keyed by the
// SHA-256 of their bytes, so attaching the same picture twice never doubles
// storage. Conversations only keep a tiny reference:
//
//     { id, w, h, bytes }
//
// IndexedDB is used rather than the Cache Storage API because `caches` is only
// available in secure contexts — this app is commonly reached over plain HTTP on
// a LAN. When IndexedDB is unavailable or fails to open (e.g. some
// private-browsing modes), the store transparently falls back to an in-memory
// Map: images still work for the current session but are not persisted.

const DB_NAME = "metallama-chat";
const DB_VERSION = 1;
const STORE = "images";
// Never GC a blob younger than this. Orphan collection runs at startup, and an
// attachment added a moment later must not be swept away by that pass.
const GC_GRACE_MS = 5 * 60 * 1000;

let _dbPromise = null;
let _idbBroken = false; // set once IndexedDB proves unusable → memory fallback
let _memory = null; // Map<id, {blob, bytes, mime, created}> — fallback only

function hasIDB() {
  try {
    return typeof indexedDB !== "undefined" && indexedDB !== null;
  } catch {
    return false;
  }
}

function idbAvailable() {
  return !_idbBroken && hasIDB();
}

function openDB() {
  if (_dbPromise) return _dbPromise;
  _dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => {
      _idbBroken = true;
      reject(req.error);
    };
    req.onblocked = () => {
      _idbBroken = true;
      reject(new Error("IndexedDB blocked"));
    };
  });
  return _dbPromise;
}

function store(db, mode) {
  return db.transaction(STORE, mode).objectStore(STORE);
}

function reqToPromise(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function memoryMap() {
  if (!_memory) _memory = new Map();
  return _memory;
}

/** Random id fallback for environments without crypto.subtle (non-secure contexts). */
function randomId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Content hash when the WebCrypto API is available, else a random id. */
async function idFor(blob) {
  if (!globalThis.crypto?.subtle) return randomId();
  try {
    const buf = await blob.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buf);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return randomId();
  }
}

/**
 * Store an image Blob (deduped by content hash when hashing is available).
 * Returns `{ id, bytes }`.
 */
export async function putImage(blob) {
  const id = await idFor(blob);
  const record = { blob, bytes: blob.size, mime: blob.type, created: Date.now() };
  if (idbAvailable()) {
    try {
      const db = await openDB();
      const existing = await reqToPromise(store(db, "readonly").get(id));
      if (!existing) await reqToPromise(store(db, "readwrite").put(record, id));
      return { id, bytes: blob.size };
    } catch {
      _idbBroken = true; // fall through to memory
    }
  }
  const mem = memoryMap();
  if (!mem.has(id)) mem.set(id, record);
  return { id, bytes: blob.size };
}

/** Fetch an image Blob by id, or null if missing. */
export async function getImage(id) {
  if (!id) return null;
  if (idbAvailable()) {
    try {
      const db = await openDB();
      const rec = await reqToPromise(store(db, "readonly").get(id));
      return rec?.blob || null;
    } catch {
      _idbBroken = true;
    }
  }
  return _memory?.get(id)?.blob || null;
}

/** Delete a single image by id. */
export async function deleteImage(id) {
  if (!id) return;
  if (idbAvailable()) {
    try {
      const db = await openDB();
      await reqToPromise(store(db, "readwrite").delete(id));
      return;
    } catch {
      _idbBroken = true;
    }
  }
  _memory?.delete(id);
}

/** Remove stored images whose ids are not in `validIds`. Returns the count removed. */
export async function gcImages(validIds) {
  const keep = validIds instanceof Set ? validIds : new Set(validIds || []);
  const isFresh = (rec) => rec?.created && Date.now() - rec.created < GC_GRACE_MS;

  let removed = 0;
  if (idbAvailable()) {
    try {
      const db = await openDB();
      const keys = await reqToPromise(store(db, "readonly").getAllKeys());
      for (const key of keys) {
        if (keep.has(key)) continue;
        const rec = await reqToPromise(store(db, "readonly").get(key));
        if (isFresh(rec)) continue; // don't race an in-flight attachment
        await reqToPromise(store(db, "readwrite").delete(key));
        removed++;
      }
      return removed;
    } catch {
      _idbBroken = true;
    }
  }
  if (!_memory) return removed;
  for (const [id, rec] of [..._memory.entries()]) {
    if (!keep.has(id) && !isFresh(rec)) {
      _memory.delete(id);
      removed++;
    }
  }
  return removed;
}

/** Ask the browser for durable storage so images are less likely to be evicted. */
export async function requestPersistence() {
  try {
    if (navigator.storage?.persist && !(await navigator.storage.persisted())) {
      await navigator.storage.persist();
    }
  } catch {
    /* non-fatal */
  }
}

/** Convert a Blob to a data: URL (used when sending to the gateway and exporting). */
export function blobToDataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("could not read image"));
    reader.readAsDataURL(blob);
  });
}
