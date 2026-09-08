// Chat page — talks to the Ollama gateway at /ollama/api/chat.
// Standalone page (served at /chat); no dependencies on main.js features.

const LS_CONVS = "metallama.chat.conversations";
const LS_MODEL = "metallama.chat.model";

let conversations = []; // [{id, title, messages:[{role, content, model?}], created_at}]
let currentId = null;
let models = []; // from /ollama/api/tags (running servers only)
let streaming = false;
let aborter = null;

// ── DOM refs ───────────────────────────────────────────────
const $messages = document.getElementById("chat-messages");
const $empty = document.getElementById("chat-empty");
const $input = document.getElementById("chat-input");
const $send = document.getElementById("chat-send-btn");
const $stop = document.getElementById("chat-stop-btn");
const $modelSelect = document.getElementById("chat-model-select");
const $historySelect = document.getElementById("chat-history-select");
const $deleteBtn = document.getElementById("chat-delete-btn");
const $exportBtn = document.getElementById("chat-export-btn");
const $importBtn = document.getElementById("chat-import-btn");
const $importFile = document.getElementById("chat-import-file");
const $newBtn = document.getElementById("chat-new-btn");
const $status = document.getElementById("chat-status");
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

function newConversation() {
  const conv = { id: crypto.randomUUID(), title: "New chat", messages: [], created_at: Date.now() };
  conversations.unshift(conv);
  currentId = conv.id;
  saveConvs();
  renderHistorySelect();
  renderMessages();
}

function deleteConversation(id) {
  conversations = conversations.filter((c) => c.id !== id);
  if (currentId === id) currentId = conversations[0]?.id || null;
  if (!currentId && conversations.length === 0) newConversation();
  saveConvs();
  renderHistorySelect();
  renderMessages();
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

function exportConversation() {
  const conv = currentConv();
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
  renderHistorySelect();
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
    setStatus("offline", "no model");
    return;
  }
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m.name;
    const ctx = m.details?.context_length ? ` · ${fmtCtx(m.details.context_length)}` : "";
    opt.textContent = `${m.name}${ctx}`;
    $modelSelect.appendChild(opt);
  }
  if (models.some((m) => m.name === prev)) {
    $modelSelect.value = prev;
  } else {
    localStorage.removeItem(LS_MODEL);
  }
  setStatus("online", models.length === 1 ? models[0].name : `${models.length} models`);
}

function fmtCtx(n) {
  return n >= 1024 ? `${Math.round(n / 1024)}k ctx` : `${n} ctx`;
}

function setStatus(state, label) {
  $status.className = `status-badge ${state}`;
  $status.textContent = label;
}

// ── History dropdown ───────────────────────────────────────
function renderHistorySelect() {
  const prev = currentId;
  $historySelect.innerHTML = "";
  for (const c of conversations) {
    const opt = document.createElement("option");
    opt.value = c.id;
    const date = new Date(c.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    opt.textContent = `${c.title} (${date})`;
    $historySelect.appendChild(opt);
  }
  if (conversations.some((c) => c.id === prev)) {
    currentId = prev;
  } else {
    currentId = conversations[0]?.id || null;
  }
  $historySelect.value = currentId || "";
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
  meta.textContent = msg.role === "user" ? "You" : msg.model || "Assistant";
  el.appendChild(meta);

  const body = document.createElement("div");
  body.className = "chat-body";
  body.textContent = msg.content;
  el.appendChild(body);

  $messages.appendChild(el);
  return { el, body };
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

/** Last server-reported prompt token count in this conversation (true used ctx). */
function lastPromptCount(conv) {
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
  let label;
  if (real != null) {
    label = `${(real + draft).toLocaleString()} / ${ctx.toLocaleString()} tok`;
  } else {
    // No server data yet — fall back to a full estimate.
    const est = estimateTokens([...(conv?.messages || []).map((m) => m.content), $input.value].join(" "));
    label = `≈${est.toLocaleString()} / ${ctx.toLocaleString()} tok`;
  }
  $tokens.textContent = label;
  $tokens.classList.remove("is-hidden");
  $tokens.classList.toggle("over", real != null && real + draft > ctx);
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
  conv.messages.push({ role: "user", content: text });
  if (isFirstUserMsg) {
    conv.title = text.length > 42 ? `${text.slice(0, 42)}…` : text;
    renderHistorySelect();
  }

  $input.value = "";
  autosizeInput();
  appendMessageEl({ role: "user", content: text });
  scrollBottom(true);

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
          assistantBody.textContent = content;
          assistantBody.appendChild(cursor);
          scrollBottom();
        }
        // Real token counts arrive on the final done line (when upstream
        // supports stream_options.include_usage).
        if (typeof obj.prompt_eval_count === "number") promptTokens = obj.prompt_eval_count;
        if (typeof obj.eval_count === "number") completionTokens = obj.eval_count;
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      if (!content) content = "(stopped)";
    } else {
      toast(err.message, true);
      if (!content) assistantBody.textContent = "";
      assistantBody.parentElement.classList.add("error");
    }
  } finally {
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
      if (promptTokens != null) saved.prompt_tokens = promptTokens;
      if (completionTokens != null) saved.completion_tokens = completionTokens;
      conv.messages.push(saved);
    }
    saveConvs();
    updateTokenChip();
  }
}

function setStreamingUI(on) {
  $send.disabled = on || !selectedModel() || !$input.value.trim();
  $stop.classList.toggle("is-hidden", !on);
  $input.placeholder = on ? "Generating…" : "Send a message… (Enter to send, Shift+Enter for newline)";
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

// ── Init ───────────────────────────────────────────────────
export function initChat() {
  loadState();
  if (conversations.length === 0) newConversation();
  else renderHistorySelect();
  renderMessages();

  $send.addEventListener("click", sendMessage);
  $stop.addEventListener("click", () => aborter?.abort());
  $newBtn.addEventListener("click", () => {
    if (streaming) return;
    newConversation();
  });

  $historySelect.addEventListener("change", () => {
    currentId = $historySelect.value || null;
    renderMessages();
    updateTokenChip();
  });
  $deleteBtn.addEventListener("click", () => {
    if (streaming) return;
    const conv = currentConv();
    if (conv && confirm(`Delete "${conv.title}"?`)) {
      deleteConversation(conv.id);
    }
  });

  $exportBtn.addEventListener("click", exportConversation);
  $importBtn.addEventListener("click", () => $importFile.click());
  $importFile.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (file) await importConversation(file);
    e.target.value = ""; // allow re-importing the same file
  });

  $modelSelect.addEventListener("change", () => {
    localStorage.setItem(LS_MODEL, selectedModel());
    setStatus("online", selectedModel() || "no model");
    setStreamingUI(false);
    updateTokenChip();
  });

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

  loadModels().then(() => setStreamingUI(false));
}
