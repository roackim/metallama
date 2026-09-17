// Chat page — talks to the Ollama gateway at /ollama/api/chat.
// Standalone page (served at /chat); no dependencies on main.js features.

import { marked } from "https://esm.sh/marked@12.0.2";
import DOMPurify from "https://esm.sh/dompurify@3.1.6";
// Full highlight.js build — all common languages pre-registered, single import.
import hljs from "https://esm.sh/highlight.js@11.11.1";
import { copyToClipboard } from "/static/js/core/clipboard.js";
import {
  putImage,
  getImage,
  gcImages,
  requestPersistence,
  blobToDataURL,
} from "./imageStore.js";

const LS_CONVS = "metallama.chat.conversations";
const LS_MODEL = "metallama.chat.model";
const LS_HLTHEME = "metallama.chat.hltheme";
const LS_SIDEBAR = "metallama.chat.sidebar"; // "1" when collapsed

// Image attachments (vision models only).
const MAX_IMAGES = 8; // per message
const MAX_EDGE = 1024; // downscale so the long edge fits this many px
const JPEG_QUALITY = 0.85;
// Rough per-image context cost, used only for the pre-send estimate. The
// server's real prompt_eval_count (which includes image tokens) corrects it
// as soon as the first vision turn completes.
const IMAGE_TOKEN_ESTIMATE = 768;

// Syntax-highlight themes (highlight.js 11.11.1 ships all of these).
const HL_THEMES = [
  "agate", "sunburst", "srcery", "rose-pine", "qtcreator-dark", "pojoaque",
  "panda-syntax-dark", "monokai", "hybrid", "github-dark", "felipec",
];
const HL_DEFAULT_THEME = "github-dark";

function hlThemeUrl(name) {
  return `https://cdn.jsdelivr.net/npm/highlight.js@11.11.1/styles/${name}.css`;
}

let $hlLink = null;
/** Swap the highlight.js stylesheet. Existing code recolors instantly because
 *  token spans keep their hljs-* classes — no re-render needed. */
function applyHlTheme(name) {
  if (!HL_THEMES.includes(name)) name = HL_DEFAULT_THEME;
  localStorage.setItem(LS_HLTHEME, name);
  if (!$hlLink) {
    $hlLink = document.createElement("link");
    $hlLink.rel = "stylesheet";
    document.head.appendChild($hlLink);
  }
  $hlLink.href = hlThemeUrl(name);
}

function currentHlTheme() {
  const saved = localStorage.getItem(LS_HLTHEME);
  return HL_THEMES.includes(saved) ? saved : HL_DEFAULT_THEME;
}

/** Collapse/expand the conversation sidebar; the choice persists across loads. */
function setSidebarCollapsed(collapsed) {
  $shell.classList.toggle("is-collapsed", collapsed);
  // Both the expand arrow (main area) and collapse arrow (sidebar) reflect state.
  if ($expandBtn) $expandBtn.setAttribute("aria-expanded", String(!collapsed));
  if ($collapseBtn) $collapseBtn.setAttribute("aria-expanded", String(!collapsed));
  if (collapsed) localStorage.setItem(LS_SIDEBAR, "1");
  else localStorage.removeItem(LS_SIDEBAR);
}

// How often (ms) to re-render live Markdown while streaming. Fence open/close
// events bypass this and render immediately so code blocks appear right away.
const LIVE_RENDER_MS = 120;

let conversations = []; // [{id, title, messages:[{role, content, model?}], created_at}]
let currentId = null;
let models = []; // from /ollama/api/tags (running servers only)
let streaming = false;
let aborter = null;
// Images attached to the message being composed: [{ id, w, h, bytes, url }].
let pendingImages = [];

// ── DOM refs ───────────────────────────────────────────────
const $shell = document.querySelector(".chat-shell");
const $expandBtn = document.getElementById("chat-expand-btn");
const $newTopbarBtn = document.getElementById("chat-new-topbar-btn");
const $collapseBtn = document.getElementById("chat-collapse-btn");
const $messages = document.getElementById("chat-messages");
const $empty = document.getElementById("chat-empty");
const $input = document.getElementById("chat-input");
const $send = document.getElementById("chat-send-btn");
const $stop = document.getElementById("chat-stop-btn");
const $modelSelect = document.getElementById("chat-model-select");
const $attachBtn = document.getElementById("chat-attach-btn");
const $attachFile = document.getElementById("chat-attach-file");
const $attachStrip = document.getElementById("chat-attach-strip");
const $inputWrap = document.querySelector(".chat-input-wrap");
const $themeSelect = document.getElementById("chat-theme-select");
const $convList = document.getElementById("chat-conv-list");
const $convTitle = document.getElementById("chat-conv-title");
const $renameBtn = document.getElementById("chat-rename-btn");
const $importBtn = document.getElementById("chat-import-btn");
const $importFile = document.getElementById("chat-import-file");
const $newBtn = document.getElementById("chat-new-btn");
const $convDate = document.getElementById("chat-conv-date");
const $tokens = document.getElementById("chat-tokens");

// ── Persistence ────────────────────────────────────────────
function loadState() {
  try {
    conversations = JSON.parse(localStorage.getItem(LS_CONVS)) || [];
  } catch {
    conversations = [];
  }
}

function saveConvs() {
  localStorage.setItem(LS_CONVS, JSON.stringify(conversations));
}

function currentConv() {
  return conversations.find((c) => c.id === currentId) || null;
}

const MONTHS_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sept","Oct","Nov","Dec"];

/** Default conversation name: e.g. "New chat, 9 Sept 2026". */
function defaultTitle(ts) {
  const d = new Date(ts);
  return `New chat, ${d.getDate()} ${MONTHS_SHORT[d.getMonth()]} ${d.getFullYear()}`;
}

function newConversation() {
  const ts = Date.now();
  const conv = { id: crypto.randomUUID(), title: defaultTitle(ts), messages: [], created_at: ts };
  conversations.unshift(conv);
  currentId = conv.id;
  saveConvs();
  renderConvList();
  renderConvTitle();
  renderMessages();
}

/** Show the active conversation's name + start date in the header. */
function renderConvTitle() {
  const conv = currentConv();
  $convTitle.textContent = conv ? (conv.title || "Untitled") : "";
  $renameBtn.disabled = !conv;
  if (conv) {
    const d = new Date(conv.created_at);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    $convDate.textContent = `${dd}/${mm}/${d.getFullYear()}`;
    // Tooltip: full date + hour
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    $convDate.title = `${dd}/${mm}/${d.getFullYear()} ${hh}:${mi}`;
  } else {
    $convDate.textContent = "";
    $convDate.title = "";
  }
}

function deleteConversation(id) {
  conversations = conversations.filter((c) => c.id !== id);
  if (currentId === id) currentId = conversations[0]?.id || null;
  if (!currentId && conversations.length === 0) newConversation();
  saveConvs();
  renderConvList();
  renderConvTitle();
  renderMessages();
}

// ── Rename modal ───────────────────────────────────────────
let $renameModal = null;

function closeRenameModal() {
  if ($renameModal) { $renameModal.remove(); $renameModal = null; }
}

function openRenameModal(convId) {
  const conv = conversations.find((c) => c.id === convId);
  if (!conv || streaming) return;
  closeRenameModal(); // only one at a time

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-dialog" style="max-width:420px">
      <div class="modal-header">
        <h2>Rename conversation</h2>
        <button class="modal-close" type="button" title="Close">&times;</button>
      </div>
      <div class="modal-body">
        <input type="text" class="chat-rename-modal-input" placeholder="Conversation name" />
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" type="button" data-act="cancel">Cancel</button>
        <button class="btn-primary" type="button" data-act="save">Save</button>
      </div>
    </div>`;

  const input = overlay.querySelector("input");
  input.value = conv.title || ""; // set via property — no HTML injection

  const close = () => { overlay.remove(); $renameModal = null; };
  const save = () => {
    const v = input.value.trim();
    if (!v) { toast("Name can't be empty.", true); return; }
    if (v !== conv.title) {
      conv.title = v;
      saveConvs();
      renderConvList();
      renderConvTitle();
    }
    close();
  };

  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.querySelector('[data-act="cancel"]').addEventListener("click", close);
  overlay.querySelector('[data-act="save"]').addEventListener("click", save);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); save(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });

  document.body.appendChild(overlay);
  $renameModal = overlay;
  input.focus();
  input.select();
}

// ── Import / Export ────────────────────────────────────────
const EXPORT_VERSION = 1;

function sanitizeFilename(input) {
  return String(input || "")
    .replace(/\.[^/.]+$/, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
}

async function exportConversation(conv) {
  conv = conv || currentConv();
  if (!conv || conv.messages.length === 0) {
    toast("Nothing to export — this conversation is empty.", true);
    return;
  }
  // Images live in the ImageStore, not the conversation JSON — embed them as
  // data URLs so the exported file is self-contained and portable.
  const messages = await Promise.all(
    conv.messages.map(async (m) => {
      const out = { role: m.role, content: m.content };
      if (m.images?.length) {
        const urls = (
          await Promise.all(
            m.images.map(async (im) => {
              const blob = await getImage(im.id);
              return blob ? blobToDataURL(blob) : null;
            }),
          )
        ).filter(Boolean);
        if (urls.length) out.images = urls;
      }
      return out;
    }),
  );
  const payload = {
    app: "metallama-chat",
    version: EXPORT_VERSION,
    exported_at: new Date().toISOString(),
    model: selectedModel() || null,
    title: conv.title,
    messages,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${sanitizeFilename(conv.title) || "chat"}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Coerce an imported message array into the internal shape. Returns [] if invalid.
 *  Async because image parts are decoded and stored in the ImageStore. */
async function normalizeMessages(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const m of raw) {
    if (!m || typeof m !== "object") continue;
    const role = m.role === "user" ? "user" : m.role === "assistant" ? "assistant" : null;
    if (!role) continue;

    let content = typeof m.content === "string" ? m.content : "";
    const imageSources = [];

    // OpenAI-style multimodal content (array of parts): join text, collect images.
    if (Array.isArray(m.content)) {
      const texts = [];
      for (const p of m.content) {
        if (!p || typeof p !== "object") continue;
        if (p.type === "text" && typeof p.text === "string") texts.push(p.text);
        else if (p.type === "image_url") imageSources.push(p.image_url?.url);
        else if (p.type === "input_image") {
          imageSources.push(typeof p.image_url === "string" ? p.image_url : p.image_url?.url);
        }
      }
      content = texts.join("");
    }

    // Native Ollama / our export format: `images` is a list of data URLs or
    // raw base64 strings.
    if (Array.isArray(m.images)) {
      for (const src of m.images) {
        if (typeof src !== "string" || !src) continue;
        const isUrl = src.startsWith("data:") || /^https?:/i.test(src);
        imageSources.push(isUrl ? src : `data:image/jpeg;base64,${src}`);
      }
    }

    const msg = { role, content };
    if (typeof m.model === "string" && m.model) msg.model = m.model;
    if (typeof m.reasoning === "string" && m.reasoning) msg.reasoning = m.reasoning;
    if (typeof m.reasoning_secs === "number" && m.reasoning_secs) msg.reasoning_secs = m.reasoning_secs;

    if (imageSources.length) {
      const refs = (await Promise.all(imageSources.map(importImageSource))).filter(Boolean);
      if (refs.length) msg.images = refs;
    }
    out.push(msg);
  }
  return out;
}

async function importConversation(file) {
  let text;
  try {
    text = await file.text();
  } catch {
    toast("Could not read that file.", true);
    return;
  }
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    toast("Not valid JSON — expected a Metallama chat export.", true);
    return;
  }
  // Accept our own format, or a bare array of messages.
  const rawMessages = Array.isArray(data) ? data : data.messages;
  const messages = await normalizeMessages(rawMessages);
  if (messages.length === 0) {
    toast("No valid user/assistant messages found in that file.", true);
    return;
  }
  let title = typeof data.title === "string" && data.title ? data.title : null;
  if (!title) {
    const firstUser = messages.find((m) => m.role === "user");
    const firstText = firstUser?.content?.trim() || "";
    title = firstText
      ? (firstText.length > 42 ? `${firstText.slice(0, 42)}…` : firstText)
      : file.name;
  }
  const conv = { id: crypto.randomUUID(), title, messages, created_at: Date.now() };
  conversations.unshift(conv);
  currentId = conv.id;
  saveConvs();
  renderConvList();
  renderMessages();
  updateTokenChip();
  toast(`Imported "${title}" (${messages.length} messages).`);
}

// ── Models ─────────────────────────────────────────────────
async function loadModels() {
  try {
    const r = await fetch("/ollama/api/tags");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    models = data.models || [];
  } catch {
    models = [];
  }
  renderModelSelect();
}

function selectedModel() {
  return $modelSelect.value;
}

function modelContextLength(name) {
  const m = models.find((x) => x.name === name);
  return m?.details?.context_length || 0;
}

function renderModelSelect() {
  const prev = localStorage.getItem(LS_MODEL) || $modelSelect.dataset.value || "";
  $modelSelect.innerHTML = "";
  if (models.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No running models";
    $modelSelect.appendChild(opt);
    updateAttachAvailability();
    return;
  }
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m.name;
    // Context window lives in the ctx chip, not glued onto the model name.
    opt.textContent = m.name;
    $modelSelect.appendChild(opt);
  }
  if (models.some((m) => m.name === prev)) {
    $modelSelect.value = prev;
  } else {
    localStorage.removeItem(LS_MODEL);
  }
  sizeModelSelect();
  updateAttachAvailability();
}

/** Size the model selector to fit its longest option name. */
function sizeModelSelect() {
  const cs = getComputedStyle($modelSelect);
  // Hidden measurer matching the select's text styles (uppercase, weight, spacing).
  const m = document.createElement("span");
  m.style.cssText = `position:absolute;visibility:hidden;white-space:nowrap;font-family:${cs.fontFamily};font-size:${cs.fontSize};font-weight:${cs.fontWeight};text-transform:${cs.textTransform};letter-spacing:${cs.letterSpacing}`;
  document.body.appendChild(m);
  let widest = 0;
  for (const opt of $modelSelect.options) {
    m.textContent = opt.value || "No running models";
    widest = Math.max(widest, m.getBoundingClientRect().width);
  }
  m.remove();
  // Text + left padding + right room for the chevron.
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padR = parseFloat(cs.paddingRight) || 0;
  $modelSelect.style.minWidth = `${Math.ceil(widest + padL + padR)}px`;
  $modelSelect.style.maxWidth = "none";
}

function fmtCtx(n) {
  return n >= 1024 ? `${Math.round(n / 1024)}k ctx` : `${n} ctx`;
}

// ── Image attachments (vision models) ──────────────────────
/** Whether the selected/running model advertises vision capability. Virtual
 *  reasoning-effort models (`name:effort`) carry the base server's capability. */
function modelSupportsVision(name) {
  const m = models.find((x) => x.name === name);
  return !!m?.capabilities?.includes("vision");
}

// Object URLs are cached per image id so repeated renders reuse the same URL
// (and the browser keeps the decoded image warm). They live for the session.
const objectUrls = new Map();
function objectUrlFor(id, blob) {
  let url = objectUrls.get(id);
  if (!url) {
    url = URL.createObjectURL(blob);
    objectUrls.set(id, url);
  }
  return url;
}

/** Downscale + re-encode an image file for the gateway.
 *
 *  PNG sources stay PNG (screenshots/text keep their sharpness); everything
 *  else becomes JPEG. WebP is never produced: llama.cpp's stb_image decoder
 *  handles PNG/JPEG/BMP but not WebP. */
async function processImageFile(file) {
  const bitmap = await createImageBitmap(file);
  try {
    const { width, height } = bitmap;
    const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
    const w = Math.max(1, Math.round(width * scale));
    const h = Math.max(1, Math.round(height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    const isPng = file.type === "image/png";
    if (!isPng) {
      // JPEG has no alpha channel — flatten transparency to white.
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, w, h);
    }
    ctx.drawImage(bitmap, 0, 0, w, h);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, isPng ? "image/png" : "image/jpeg", isPng ? undefined : JPEG_QUALITY),
    );
    if (!blob) throw new Error("could not encode image");
    return { blob, w, h };
  } finally {
    bitmap.close?.();
  }
}

/** Store processed images and add them to the compose strip. */
async function addPendingImages(files) {
  const list = [...files].filter((f) => f && f.type.startsWith("image/"));
  if (list.length === 0) return;
  let rejected = 0;
  for (const file of list) {
    if (pendingImages.length >= MAX_IMAGES) {
      rejected++;
      continue;
    }
    try {
      const { blob, w, h } = await processImageFile(file);
      const { id, bytes } = await putImage(blob);
      if (pendingImages.some((im) => im.id === id)) continue; // same image twice
      pendingImages.push({ id, w, h, bytes, url: objectUrlFor(id, blob) });
    } catch {
      rejected++;
    }
  }
  if (rejected > 0) {
    toast(
      rejected === 1 ? "Couldn't attach that image." : `Couldn't attach ${rejected} images.`,
      true,
    );
  }
  if (pendingImages.length >= MAX_IMAGES) {
    toast(`Up to ${MAX_IMAGES} images per message.`);
  }
  renderAttachStrip();
  setStreamingUI(streaming);
  updateTokenChip();
}

function removePendingImage(id) {
  pendingImages = pendingImages.filter((im) => im.id !== id);
  renderAttachStrip();
  setStreamingUI(streaming);
  updateTokenChip();
}

function clearPendingImages() {
  pendingImages = [];
  renderAttachStrip();
}

function renderAttachStrip() {
  $attachStrip.innerHTML = "";
  if (pendingImages.length === 0) {
    $attachStrip.classList.add("is-hidden");
    return;
  }
  $attachStrip.classList.remove("is-hidden");
  for (const im of pendingImages) {
    const thumb = document.createElement("div");
    thumb.className = "chat-attach-thumb";
    const img = document.createElement("img");
    img.src = im.url;
    img.alt = "attached image";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chat-attach-remove";
    remove.textContent = "×";
    remove.title = "Remove image";
    remove.addEventListener("click", () => removePendingImage(im.id));
    thumb.append(img, remove);
    $attachStrip.appendChild(thumb);
  }
}

/** Enable the attach button only when the selected model supports vision. */
function updateAttachAvailability() {
  const ok = modelSupportsVision(selectedModel());
  $attachBtn.disabled = !ok;
  $attachBtn.title = ok ? "Attach images" : "Selected model doesn't support images";
}

function pendingImageTokens() {
  return pendingImages.length * IMAGE_TOKEN_ESTIMATE;
}

/** All image ids referenced by saved conversations (for orphan GC). */
function referencedImageIds() {
  const ids = new Set();
  for (const conv of conversations) {
    for (const m of conv.messages) {
      for (const im of m.images || []) if (im?.id) ids.add(im.id);
    }
  }
  return ids;
}

/** Convert an imported image source (data: or http(s) URL) into a stored ref. */
async function importImageSource(src) {
  if (typeof src !== "string" || !src) return null;
  try {
    const blob = await fetch(src).then((r) => {
      if (!r.ok) throw new Error(String(r.status));
      return r.blob();
    });
    if (!blob.type.startsWith("image/")) return null;
    const { id, bytes } = await putImage(blob);
    return { id, bytes };
  } catch {
    return null;
  }
}

// ── Conversation sidebar list ──────────────────────────────
function renderConvList() {
  const prev = currentId;
  if (!conversations.some((c) => c.id === prev)) {
    currentId = conversations[0]?.id || null;
  }
  $convList.innerHTML = "";
  for (const c of conversations) {
    const li = document.createElement("li");
    li.className = "chat-conv-item" + (c.id === currentId ? " is-active" : "");
    li.dataset.id = c.id;

    const title = document.createElement("span");
    title.className = "chat-conv-title";
    title.textContent = c.title || "New chat";
    title.title = `${c.title} · ${new Date(c.created_at).toLocaleString()}`;

    const more = document.createElement("button");
    more.type = "button";
    more.className = "chat-conv-more";
    more.textContent = "⋯";
    more.title = `Actions for "${c.title}"`;
    more.addEventListener("click", (e) => {
      e.stopPropagation();
      openConvMenu(more, c, title);
    });

    const del = document.createElement("button");
    del.type = "button";
    del.className = "chat-conv-del";
    del.textContent = "✕";
    del.title = `Delete "${c.title}"`;
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      if (streaming) return;
      if (confirm(`Delete "${c.title}"?`)) deleteConversation(c.id);
    });

    const actions = document.createElement("span");
    actions.className = "chat-conv-actions";
    actions.append(more, del);
    li.append(title, actions);
    li.addEventListener("click", () => selectConversation(c.id));
    $convList.appendChild(li);
  }
}

// ── Per-conversation kebab menu (⋯ → Rename / Export) ────────
let $convMenu = null;

function closeConvMenu() {
  if ($convMenu) { $convMenu.remove(); $convMenu = null; }
}

function openConvMenu(anchorBtn, conv, titleEl) {
  closeConvMenu();
  const menu = document.createElement("div");
  menu.className = "chat-conv-menu";
  menu.setAttribute("role", "menu");

  const items = [
    { label: "Rename", action: () => openRenameModal(conv.id) },
    { label: "Export", action: () => exportConversation(conv) },
  ];

  for (const item of items) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-conv-menu-item";
    btn.textContent = item.label;
    btn.setAttribute("role", "menuitem");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeConvMenu();
      item.action();
    });
    menu.appendChild(btn);
  }

  // Position: anchored to the right of the ⋯ button, opening downward.
  const rect = anchorBtn.getBoundingClientRect();
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.left = `${rect.right - 120}px`; // align right edge near button
  document.body.appendChild(menu);
  $convMenu = menu;

  // Close on outside click or Escape.
  const onDocClick = (e) => {
    if (!menu.contains(e.target)) { closeConvMenu(); cleanup(); }
  };
  const onKey = (e) => {
    if (e.key === "Escape") { closeConvMenu(); cleanup(); }
  };
  function cleanup() {
    document.removeEventListener("mousedown", onDocClick);
    document.removeEventListener("keydown", onKey);
  }
  setTimeout(() => {
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
  }, 0);
}

/** Switch the active conversation and re-render. */
function selectConversation(id) {
  if (id === currentId || streaming) return;
  currentId = id;
  renderConvList();
  renderConvTitle();
  renderMessages();
  updateTokenChip();
}

// ── Markdown rendering (assistant messages) ────────────────
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

marked.setOptions({ gfm: true, breaks: false });

/** Wrap each <pre><code> in a header bar with language label + copy button. */
function postProcessCodeBlocks(root) {
  for (const pre of root.querySelectorAll("pre")) {
    if (pre.parentElement?.classList.contains("chat-codeblock")) continue; // already wrapped
    const code = pre.querySelector("code");
    const langClass = code ? [...code.classList].find((c) => c.startsWith("language-")) : null;
    const lang = langClass ? langClass.slice("language-".length) : "";

    let highlightedHtml;
    if (lang && hljs.getLanguage(lang)) {
      try {
        // hljs.highlight already returns escaped HTML — do NOT re-escape.
        highlightedHtml = hljs.highlight(code.textContent, { language: lang }).value;
      } catch {
        highlightedHtml = code.innerHTML;
      }
    } else {
      highlightedHtml = code ? code.innerHTML : pre.innerHTML;
    }

    const label = lang ? `<span class="chat-code-lang">${escapeHtml(lang)}</span>` : "";
    const wrap = document.createElement("div");
    wrap.className = "chat-codeblock";
    wrap.innerHTML =
      `<div class="chat-code-head">${label}` +
      `<button type="button" class="chat-copy-btn" title="Copy code">copy</button></div>`;
    pre.replaceWith(wrap);
    const newPre = document.createElement("pre");
    newPre.innerHTML = `<code class="hljs${lang ? " language-" + escapeHtml(lang) : ""}">${highlightedHtml}</code>`;
    wrap.appendChild(newPre);
  }
}

/** Render assistant Markdown to sanitized HTML and attach copy buttons. */
function renderMarkdown(body, text) {
  const html = DOMPurify.sanitize(marked.parse(text || ""));
  body.innerHTML = html;
  // Switch from plain-text (pre-wrap) flow to normal block layout for HTML.
  body.classList.add("is-md");
  postProcessCodeBlocks(body);
  for (const btn of body.querySelectorAll(".chat-copy-btn")) {
    btn.addEventListener("click", async () => {
      const codeEl = btn.closest(".chat-codeblock")?.querySelector("pre code");
      if (!codeEl) return;
      await copyToClipboard(codeEl.innerText);
      flashCopy(btn);
    });
  }
}

function flashCopy(btn) {
  const prev = btn.textContent;
  btn.textContent = "copied";
  btn.classList.add("is-copied");
  setTimeout(() => {
    btn.textContent = prev;
    btn.classList.remove("is-copied");
  }, 1200);
}

/** True if the markdown has an unclosed fenced code block (odd number of ```). */
function fenceOpen(text) {
  const n = (text.match(/```/g) || []).length;
  return n % 2 === 1;
}

/** Place the blinking cursor at the end of the live content. If a code fence is
 *  currently open, put it inside that block so it reads as "typing in the code". */
function placeCursor(body, cursor) {
  if (body.contains(cursor)) return; // already attached
  const lastPre = body.querySelector(".chat-codeblock:last-of-type pre");
  if (fenceOpen(body.textContent || "") && lastPre) {
    const codeEl = lastPre.querySelector("code") || lastPre;
    codeEl.appendChild(cursor);
  } else {
    body.appendChild(cursor);
  }
}

// ── Rendering ──────────────────────────────────────────────
/** An <img> for a stored image reference; the Blob is fetched from the
 *  ImageStore and wired up lazily so message rendering stays synchronous. */
function buildMessageImage(ref) {
  const img = document.createElement("img");
  img.className = "chat-image";
  img.alt = "attached image";
  img.loading = "lazy";
  img.dataset.id = ref.id;
  getImage(ref.id)
    .then((blob) => {
      if (!blob) throw new Error("missing");
      img.src = objectUrlFor(ref.id, blob);
    })
    .catch(() => {
      img.classList.add("is-missing");
      img.alt = "image unavailable";
    });
  img.addEventListener("click", () => {
    if (img.src) openLightbox(img.src);
  });
  return img;
}

/** Full-screen image viewer; click anywhere or press Escape to dismiss. */
function openLightbox(src) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay chat-lightbox";
  const img = document.createElement("img");
  img.src = src;
  img.alt = "attached image";
  overlay.appendChild(img);

  const close = () => {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  overlay.addEventListener("click", close);
  document.addEventListener("keydown", onKey);
  document.body.appendChild(overlay);
}

function renderMessages() {
  const conv = currentConv();
  $messages.innerHTML = "";
  if (!conv || conv.messages.length === 0) {
    $empty.classList.remove("is-hidden");
    return;
  }
  $empty.classList.add("is-hidden");
  for (const msg of conv.messages) appendMessageEl(msg, false);
  scrollBottom(true);
}

function appendMessageEl(msg, animate = true) {
  const el = document.createElement("div");
  el.className = `chat-msg ${msg.role}`;
  if (animate) el.classList.add("is-new");

  const meta = document.createElement("div");
  meta.className = "chat-meta";
  const label = document.createElement("span");
  label.textContent = msg.role === "user" ? "You" : msg.model || "Assistant";
  meta.appendChild(label);

  // User messages get an edit action, tucked into the meta row (no extra line):
  // rewrite this message, cut the conversation to it, regenerate the reply.
  if (msg.role === "user" && !streaming) {
    const actions = document.createElement("div");
    actions.className = "chat-msg-actions";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn-secondary btn-small chat-edit-btn";
    editBtn.textContent = "✎ Edit";
    editBtn.title = "Edit this message and regenerate the reply";
    editBtn.addEventListener("click", () => startEditMessage(el, msg));
    actions.appendChild(editBtn);
    meta.appendChild(actions);
  }
  el.appendChild(meta);

  const body = document.createElement("div");
  body.className = "chat-body";
  if (msg.role === "assistant") renderMarkdown(body, msg.content);
  else body.textContent = msg.content;

  // Attached images sit above the caption text.
  if (msg.role === "user" && msg.images?.length) {
    const imgs = document.createElement("div");
    imgs.className = "chat-body-images";
    for (const ref of msg.images) imgs.appendChild(buildMessageImage(ref));
    el.appendChild(imgs);
  }
  el.appendChild(body);

  // Reasoning ("thoughts") render as a compact collapsible block above the answer.
  if (msg.role === "assistant" && msg.reasoning) {
    $messages.appendChild(buildThoughtsMessage(msg.reasoning, animate, msg.reasoning_secs));
  }

  $messages.appendChild(el);
  return { el, body };
}

/** Compact collapsible "Thoughts" block showing a model's reasoning_content.
 *  A single <details>; the summary reads "Thought for Xs" (or "Thoughts"). */
function buildThoughtsMessage(reasoning, animate = true, secs = null) {
  const details = document.createElement("details");
  details.className = "chat-msg thoughts";
  if (animate) details.classList.add("is-new");

  const summary = document.createElement("summary");
  const label = document.createElement("span");
  label.textContent = secs ? `Thought for ${secs}s` : "Thoughts";
  summary.appendChild(label);
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "chat-thoughts-body";
  details.appendChild(body);
  renderMarkdown(body, reasoning);
  return details;
}

/** Re-render a thoughts block's body as Markdown (used while streaming). */
function updateThoughtsBody(el, reasoning) {
  renderMarkdown(el.querySelector(".chat-thoughts-body"), reasoning);
}

/** Inline-edit a user message: swap its body for an editor. On save, truncate the
 *  conversation to this message and regenerate the next assistant reply. */
function startEditMessage(el, msg) {
  if (streaming) return;
  const model = selectedModel();
  if (!model) {
    toast("No running model — start one from the main page.", true);
    return;
  }
  const conv = currentConv();
  const body = el.querySelector(".chat-body");
  // Remove the edit button from the meta row while editing; renderMessages()
  // restores it on cancel/save. (Hiding would leave a gap in the flex row.)
  const actions = el.querySelector(".chat-msg-actions");
  if (actions) actions.remove();

  const editor = document.createElement("div");
  editor.className = "chat-edit";
  const ta = document.createElement("textarea");
  ta.className = "chat-textarea chat-edit-input";
  ta.value = msg.content;
  const row = document.createElement("div");
  row.className = "chat-edit-actions";
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn-primary btn-small";
  saveBtn.textContent = "Save & regenerate";
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "btn-secondary btn-small";
  cancelBtn.textContent = "Cancel";
  row.append(saveBtn, cancelBtn);
  editor.append(ta, row);
  body.replaceWith(editor);

  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight + 20, 300)}px`;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);

  const cancel = () => renderMessages();
  cancelBtn.addEventListener("click", cancel);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveBtn.click(); }
    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
  });

  saveBtn.addEventListener("click", async () => {
    const newText = ta.value.trim();
    if (!newText && !msg.images?.length) { toast("Message can't be empty.", true); return; }
    // Cut the conversation to this message and apply the new text.
    const idx = conv.messages.indexOf(msg);
    msg.content = newText;
    conv.messages.length = idx + 1;
    saveConvs();
    renderMessages();
    scrollBottom(true);
    await _streamAssistantReply(conv, model);
  });
}

function scrollBottom(force = false) {
  const pinned = force || isPinned();
  if (pinned) $messages.scrollTop = $messages.scrollHeight;
}

function isPinned() {
  return $messages.scrollTop + $messages.clientHeight >= $messages.scrollHeight - 40;
}

// ── Token budget ───────────────────────────────────────────
function estimateTokens(text) {
  return Math.ceil((text?.length || 0) / 4);
}

/** Last server-reported prompt token count for this conversation. */
function lastPromptCount(conv) {
  // Prefer the value stored directly on the conversation (updated after each turn).
  if (typeof conv?.prompt_tokens === "number") return conv.prompt_tokens;
  // Fallback: scan messages (for conversations saved before this field existed).
  for (let i = (conv?.messages || []).length - 1; i >= 0; i--) {
    const m = conv.messages[i];
    if (m.role === "assistant" && typeof m.prompt_tokens === "number") return m.prompt_tokens;
  }
  return null;
}

function updateTokenChip() {
  const model = selectedModel();
  const ctx = modelContextLength(model);
  if (!ctx) {
    $tokens.classList.add("is-hidden");
    return;
  }
  const conv = currentConv();
  const real = lastPromptCount(conv);
  // True used context from the server's last turn, plus a rough estimate of
  // whatever is currently typed (not yet sent).
  const draft = $input.value.trim() ? estimateTokens($input.value) + 1 : 0;
  const storedImageTokens =
    (conv?.messages || []).reduce((n, m) => n + (m.images?.length || 0), 0) * IMAGE_TOKEN_ESTIMATE;
  let used, approx;
  if (real != null) {
    // `real` already includes image tokens the server counted on prior turns;
    // only pending (unsent) attachments need adding here.
    used = real + draft + pendingImageTokens();
    approx = false;
  } else {
    // No server data yet — fall back to a full estimate.
    used =
      estimateTokens([...(conv?.messages || []).map((m) => m.content), $input.value].join(" ")) +
      storedImageTokens +
      pendingImageTokens();
    approx = true;
  }
  const pct = Math.min(100, Math.round((used / ctx) * 100));
  $tokens.textContent = `${approx ? "≈" : ""}${pct}% ctx`;
  $tokens.title = `${used.toLocaleString()} / ${ctx.toLocaleString()} tokens`;
  $tokens.classList.remove("is-hidden");
  $tokens.classList.toggle("over", used > ctx);
}

// ── Streaming send ─────────────────────────────────────────
async function sendMessage() {
  const text = $input.value.trim();
  const attachments = pendingImages.slice();
  if ((!text && attachments.length === 0) || streaming) return;
  const model = selectedModel();
  if (!model) {
    toast("No running model — start one from the main page.", true);
    return;
  }
  if (attachments.length && !modelSupportsVision(model)) {
    toast("The selected model doesn't support images.", true);
    return;
  }

  // Snapshot the refs (pixels stay in the ImageStore); the object shape is the
  // one persisted on the message.
  const imageRefs = attachments.map(({ id, w, h, bytes }) => ({ id, w, h, bytes }));

  // Reject (don't truncate) when this message would overflow the context window.
  const ctx = modelContextLength(model);
  const conv0 = currentConv();
  if (ctx) {
    const real = lastPromptCount(conv0);
    const need = estimateTokens(text) + 1 + imageRefs.length * IMAGE_TOKEN_ESTIMATE; // +1 for the role marker
    if (real != null && real + need > ctx) {
      toast(`Message won't fit: ≈${(real + need).toLocaleString()} tokens needed, ${ctx.toLocaleString()} available. Start a new chat or shorten it.`, true);
      return;
    }
  }

  let conv = currentConv();
  if (!conv) newConversation();
  conv = currentConv();

  // Title the conversation from its first user message.
  const isFirstUserMsg = !conv.messages.some((m) => m.role === "user");
  // Use one shared object so the rendered node and stored message are identical —
  // edit-and-regenerate relies on finding this exact reference in conv.messages.
  const userMsg = { role: "user", content: text };
  if (imageRefs.length) userMsg.images = imageRefs;
  conv.messages.push(userMsg);
  if (isFirstUserMsg) {
    const titleText = text || (imageRefs.length > 1 ? `${imageRefs.length} images` : "Image");
    conv.title = titleText.length > 42 ? `${titleText.slice(0, 42)}…` : titleText;
    renderConvList();
  }

  $input.value = "";
  clearPendingImages();
  autosizeInput();
  appendMessageEl(userMsg);
  scrollBottom(true);

  await _streamAssistantReply(conv, model);
}

/** Stream the next assistant reply for `conv` and persist it. Reused by both a
 *  fresh send and an edit-and-regenerate. Assumes the user message is already in
 *  conv.messages (and rendered). */
async function _streamAssistantReply(conv, model) {
  const { el: assistantEl, body: assistantBody } = appendMessageEl(
    { role: "assistant", content: "", model },
    true,
  );
  assistantBody.textContent = "";
  const cursor = document.createElement("span");
  cursor.className = "chat-cursor";
  cursor.textContent = "▍";
  assistantBody.appendChild(cursor);

  streaming = true;
  setStreamingUI(true);
  aborter = new AbortController();

  let content = "";
  let reasoning = ""; // model "thoughts" (reasoning_content), streamed separately
  let thoughtsEl = null;
  let reasoningStart = null; // when the first reasoning token arrived (for the duration label)
  let promptTokens = null; // server-reported used context (true value)
  let completionTokens = null;

  // Live Markdown rendering during the stream. Fence open/close render instantly;
  // everything else is debounced so we don't re-parse on every token.
  let liveTimer = null;
  let lastFenceOpen = false;
  const doLiveRender = () => {
    if (liveTimer) { clearTimeout(liveTimer); liveTimer = null; }
    renderMarkdown(assistantBody, content);
    placeCursor(assistantBody, cursor);
    scrollBottom();
  };
  const scheduleLiveRender = () => {
    if (!liveTimer) liveTimer = setTimeout(doLiveRender, LIVE_RENDER_MS);
  };

  try {
    // Hydrate image refs into data URLs for the gateway. Text-only messages pass
    // through untouched so the common path stays cheap.
    const payloadMessages = await Promise.all(
      conv.messages.map(async (m) => {
        const out = { role: m.role, content: m.content };
        if (m.images?.length) {
          const urls = (
            await Promise.all(
              m.images.map(async (im) => {
                const blob = await getImage(im.id);
                return blob ? blobToDataURL(blob) : null;
              }),
            )
          ).filter(Boolean);
          if (urls.length) out.images = urls;
        }
        return out;
      }),
    );

    const r = await fetch("/ollama/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: payloadMessages,
        stream: true,
      }),
      signal: aborter.signal,
    });
    if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line) continue;
        let obj;
        try {
          obj = JSON.parse(line);
        } catch {
          continue;
        }
        if (obj.error) throw new Error(obj.error);
        const piece = obj.message?.content || "";
        if (piece) {
          content += piece;
          // Render instantly when a code fence opens/closes so the highlighted
          // block appears as soon as ```lang streams in; otherwise debounce.
          const nowFenceOpen = fenceOpen(content);
          if (nowFenceOpen !== lastFenceOpen || nowFenceOpen) {
            doLiveRender();
          } else {
            scheduleLiveRender();
          }
          lastFenceOpen = nowFenceOpen;
        }
        // Reasoning deltas ("thoughts") stream in a compact collapsible block
        // above the answer. Create it on first token, then update it live.
        const reasoningPiece = obj.message?.reasoning || "";
        if (reasoningPiece) {
          reasoning += reasoningPiece;
          if (!thoughtsEl) {
            reasoningStart = Date.now();
            thoughtsEl = buildThoughtsMessage(reasoning, true);
            $messages.insertBefore(thoughtsEl, assistantEl);
          } else {
            updateThoughtsBody(thoughtsEl, reasoning);
          }
        }
        // Real token counts arrive on the final done line (when upstream
        // supports stream_options.include_usage).
        if (typeof obj.prompt_eval_count === "number") promptTokens = obj.prompt_eval_count;
        if (typeof obj.eval_count === "number") completionTokens = obj.eval_count;
      }
    }
  } catch (err) {
    if (liveTimer) { clearTimeout(liveTimer); liveTimer = null; }
    if (err.name === "AbortError") {
      if (!content) content = "(stopped)";
    } else {
      toast(err.message, true);
      assistantBody.parentElement.classList.add("error");
    }
  } finally {
    if (liveTimer) { clearTimeout(liveTimer); liveTimer = null; } // prevent re-adding cursor after removal
    cursor.remove();
    streaming = false;
    setStreamingUI(false);

    // Persist (drop the placeholder if nothing was produced).
    const last = conv.messages[conv.messages.length - 1];
    if (!content && !reasoning) {
      if (last && last.role === "assistant") conv.messages.pop();
      assistantBody.parentElement.remove();
    } else {
      // Finalize the "Thought for Xs" label once streaming ends.
      let reasoningSecs = null;
      if (reasoning && reasoningStart) {
        reasoningSecs = Math.max(1, Math.round((Date.now() - reasoningStart) / 1000));
        const label = thoughtsEl?.querySelector("summary span");
        if (label) label.textContent = `Thought for ${reasoningSecs}s`;
      }
      const saved = { role: "assistant", content, model };
      if (reasoning) {
        saved.reasoning = reasoning;
        if (reasoningSecs) saved.reasoning_secs = reasoningSecs;
      }
      if (promptTokens != null) {
        saved.prompt_tokens = promptTokens;
        conv.prompt_tokens = promptTokens; // persist on the conversation itself
      }
      if (completionTokens != null) saved.completion_tokens = completionTokens;
      conv.messages.push(saved);
      // Now that the stream is complete, render the full message as Markdown.
      renderMarkdown(assistantBody, content);
    }
    saveConvs();
    updateTokenChip();
  }
}

function setStreamingUI(on) {
  $send.disabled = on || !selectedModel() || (!$input.value.trim() && pendingImages.length === 0);
  $stop.disabled = !on; // muted/gray when not streaming, active (red) while generating
  $input.placeholder = on ? "Generating…" : "Send a message… ";
}

// ── Toast (page-local; mirrors core/uiMessage.js behaviour) ─
function toast(msg, isError = false) {
  const el = document.getElementById("ui-message");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("error", !!isError);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.textContent = "";
    el.classList.remove("error");
  }, isError ? 8000 : 4000);
}

// ── Input handling ─────────────────────────────────────────
function autosizeInput() {
  $input.style.height = "auto";
  $input.style.height = `${Math.min($input.scrollHeight, 200)}px`;
}

/** Populate the code-theme dropdown and apply the saved theme. */
function renderThemeSelect() {
  $themeSelect.innerHTML = "";
  for (const name of HL_THEMES) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name.replace(/-/g, " ");
    $themeSelect.appendChild(opt);
  }
  $themeSelect.value = currentHlTheme();
  applyHlTheme($themeSelect.value);
}

// ── Init ───────────────────────────────────────────────────
export function initChat() {
  loadState();
  setSidebarCollapsed(localStorage.getItem(LS_SIDEBAR) === "1");
  renderThemeSelect();
  if (conversations.length === 0) newConversation();
  else { renderConvList(); renderConvTitle(); }
  renderMessages();

  // Expand arrow lives in the main area (visible when collapsed);
  // collapse arrow lives inside the sidebar next to "Conversations".
  $expandBtn.addEventListener("click", () => setSidebarCollapsed(false));
  if ($newTopbarBtn) $newTopbarBtn.addEventListener("click", () => {
    if (streaming) return;
    newConversation();
  });
  $collapseBtn.addEventListener("click", () => setSidebarCollapsed(true));

  $send.addEventListener("click", sendMessage);
  $stop.addEventListener("click", () => aborter?.abort());
  $newBtn.addEventListener("click", () => {
    if (streaming) return;
    newConversation();
  });

  $renameBtn.addEventListener("click", () => {
    const conv = currentConv();
    if (conv) openRenameModal(conv.id);
  });

  // Conversation selection + per-item rename/delete are wired in renderConvList().

  $importBtn.addEventListener("click", () => $importFile.click());
  $importFile.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (file) await importConversation(file);
    e.target.value = ""; // allow re-importing the same file
  });

  // ── Image attachments (file picker, paste, drag & drop) ──
  $attachBtn.addEventListener("click", () => $attachFile.click());
  $attachFile.addEventListener("change", async (e) => {
    const files = e.target.files;
    if (files?.length) await addPendingImages(files);
    e.target.value = ""; // allow re-attaching the same file
  });

  $input.addEventListener("paste", (e) => {
    const files = e.clipboardData?.files;
    if (!files?.length) return;
    if (![...files].some((f) => f.type.startsWith("image/"))) return;
    e.preventDefault();
    if (!modelSupportsVision(selectedModel())) {
      toast("The selected model doesn't support images.", true);
      return;
    }
    addPendingImages(files);
  });

  const hasFileDrag = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  for (const ev of ["dragenter", "dragover"]) {
    $inputWrap.addEventListener(ev, (e) => {
      if (!hasFileDrag(e)) return;
      e.preventDefault();
      $inputWrap.classList.add("is-dragover");
    });
  }
  for (const ev of ["dragleave", "dragend"]) {
    $inputWrap.addEventListener(ev, () => $inputWrap.classList.remove("is-dragover"));
  }
  $inputWrap.addEventListener("drop", (e) => {
    const files = e.dataTransfer?.files;
    $inputWrap.classList.remove("is-dragover");
    if (!files?.length) return;
    e.preventDefault();
    if (!modelSupportsVision(selectedModel())) {
      toast("The selected model doesn't support images.", true);
      return;
    }
    addPendingImages(files);
  });

  $modelSelect.addEventListener("change", () => {
    localStorage.setItem(LS_MODEL, selectedModel());
    updateAttachAvailability();
    setStreamingUI(false);
    updateTokenChip();
  });

  $themeSelect.addEventListener("change", () => applyHlTheme($themeSelect.value));

  $input.addEventListener("input", () => {
    autosizeInput();
    setStreamingUI(streaming);
    updateTokenChip();
  });
  $input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Purge image blobs no longer referenced by any conversation (e.g. removed
  // before sending, or from deleted conversations), and ask for durable storage.
  requestPersistence();
  gcImages(referencedImageIds());

  // Populate the header context chip once models (and their ctx lengths) are known.
  loadModels().then(() => {
    setStreamingUI(false);
    updateTokenChip();
  });
}
