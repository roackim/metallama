// Chat page — talks to the Ollama gateway at /ollama/api/chat.
// Standalone page (served at /chat); no dependencies on main.js features.

import { marked } from "https://esm.sh/marked@12.0.2";
import DOMPurify from "https://esm.sh/dompurify@3.1.6";
// Full highlight.js build — all common languages pre-registered, single import.
import hljs from "https://esm.sh/highlight.js@11.11.1";
import { copyToClipboard } from "/static/js/core/clipboard.js";

const LS_CONVS = "metallama.chat.conversations";
const LS_MODEL = "metallama.chat.model";
const LS_HLTHEME = "metallama.chat.hltheme";
const LS_SIDEBAR = "metallama.chat.sidebar"; // "1" when collapsed

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

/** Inline-rename a conversation: swap `hostEl`'s text for an input. Shared by the
 *  header button and each sidebar item's ✎. Enter/blur saves, Esc cancels. */
function startInlineRename(convId, hostEl) {
  const conv = conversations.find((c) => c.id === convId);
  if (!conv || streaming) return;

  const item = hostEl.closest(".chat-conv-item");
  if (item) {
    item.classList.add("is-renaming");
    // Hide the label; the editor is appended to the row so it can span full width.
    hostEl.style.display = "none";
  }

  const input = document.createElement("input");
  input.type = "text";
  input.className = "chat-rename-input";
  input.value = conv.title || "";
  (item || hostEl).appendChild(input);
  input.focus();
  input.select();

  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    if (item) item.classList.remove("is-renaming");
    if (commit) {
      const v = input.value.trim();
      if (v && v !== conv.title) {
        conv.title = v;
        saveConvs();
      } else if (!v) {
        toast("Name can't be empty.", true);
      }
    }
    renderConvList();
    renderConvTitle();
  };

  // Don't let interaction with the editor bubble up to "select conversation".
  input.addEventListener("mousedown", (e) => e.stopPropagation());
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
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

function exportConversation(conv) {
  conv = conv || currentConv();
  if (!conv || conv.messages.length === 0) {
    toast("Nothing to export — this conversation is empty.", true);
    return;
  }
  const payload = {
    app: "metallama-chat",
    version: EXPORT_VERSION,
    exported_at: new Date().toISOString(),
    model: selectedModel() || null,
    title: conv.title,
    messages: conv.messages.map((m) => ({ role: m.role, content: m.content })),
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

/** Coerce an imported message array into the internal shape. Returns [] if invalid. */
function normalizeMessages(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const m of raw) {
    if (!m || typeof m !== "object") continue;
    const role = m.role === "user" ? "user" : m.role === "assistant" ? "assistant" : null;
    let content = m.content;
    // Accept OpenAI-style multimodal content (array of parts) by joining text.
    if (Array.isArray(content)) {
      content = content.filter((p) => p?.type === "text").map((p) => p.text || "").join("");
    }
    if (!role || typeof content !== "string") continue;
    const msg = { role, content };
    if (typeof m.model === "string" && m.model) msg.model = m.model;
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
  const messages = normalizeMessages(rawMessages);
  if (messages.length === 0) {
    toast("No valid user/assistant messages found in that file.", true);
    return;
  }
  let title = typeof data.title === "string" && data.title ? data.title : null;
  if (!title) {
    const firstUser = messages.find((m) => m.role === "user");
    title = firstUser ? (firstUser.content.length > 42 ? `${firstUser.content.slice(0, 42)}…` : firstUser.content) : file.name;
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
    { label: "Rename", action: () => startInlineRename(conv.id, titleEl) },
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
  el.appendChild(body);

  $messages.appendChild(el);
  return { el, body };
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
    if (!newText) { toast("Message can't be empty.", true); return; }
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
  let used, approx;
  if (real != null) {
    used = real + draft;
    approx = false;
  } else {
    // No server data yet — fall back to a full estimate.
    used = estimateTokens([...(conv?.messages || []).map((m) => m.content), $input.value].join(" "));
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
  if (!text || streaming) return;
  const model = selectedModel();
  if (!model) {
    toast("No running model — start one from the main page.", true);
    return;
  }

  // Reject (don't truncate) when this message would overflow the context window.
  const ctx = modelContextLength(model);
  let conv0 = currentConv();
  if (ctx) {
    const real = lastPromptCount(conv0);
    const need = estimateTokens(text) + 1; // +1 for the role marker
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
  conv.messages.push(userMsg);
  if (isFirstUserMsg) {
    conv.title = text.length > 42 ? `${text.slice(0, 42)}…` : text;
    renderConvList();
  }

  $input.value = "";
  autosizeInput();
  appendMessageEl(userMsg);
  scrollBottom(true);

  await _streamAssistantReply(conv, model);
}

/** Stream the next assistant reply for `conv` and persist it. Reused by both a
 *  fresh send and an edit-and-regenerate. Assumes the user message is already in
 *  conv.messages (and rendered). */
async function _streamAssistantReply(conv, model) {
  const { body: assistantBody } = appendMessageEl(
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
    const r = await fetch("/ollama/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: conv.messages.map((m) => ({ role: m.role, content: m.content })),
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
    if (!content) {
      if (last && last.role === "assistant") conv.messages.pop();
      assistantBody.parentElement.remove();
    } else {
      const saved = { role: "assistant", content, model };
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
  $send.disabled = on || !selectedModel() || !$input.value.trim();
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
    if (conv) startInlineRename(conv.id, $convTitle);
  });

  // Conversation selection + per-item rename/delete are wired in renderConvList().

  $importBtn.addEventListener("click", () => $importFile.click());
  $importFile.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (file) await importConversation(file);
    e.target.value = ""; // allow re-importing the same file
  });

  $modelSelect.addEventListener("change", () => {
    localStorage.setItem(LS_MODEL, selectedModel());
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

  // Populate the header context chip once models (and their ctx lengths) are known.
  loadModels().then(() => {
    setStreamingUI(false);
    updateTokenChip();
  });
}
