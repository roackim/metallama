import { api } from "../../core/api.js";
import { copyToClipboard } from "../../core/clipboard.js";
import { setConfigMessage } from "../../core/uiMessage.js";

const modelsEl = document.getElementById("models");
const summaryEl = document.getElementById("summary");

const inFlight = new Map(); // modelId -> "start" | "stop"
const cardErrors = new Map();
const openLogs = new Set(); // modelIds with an open log panel
const logState = new Map(); // modelId -> { since, text, pinned }
const dismissedExits = new Map(); // modelId -> last_exit.at that the user dismissed
let logTimer = null;
const LOG_POLL_INTERVAL = 1000; // ms
const LOG_TEXT_CAP = 500000; // chars kept per panel
const slotCache = new Map(); // modelId -> { slots: [...], ts: number }
let filterText = ""; // server name filter
let filterStatus = "all"; // all | running | offline
let lastSlotRefresh = 0;
const SLOT_REFRESH_INTERVAL = 5000; // ms — avoid hammering /slots during inference

// ── Edit Modal State ──────────────────────────────────────
let editingModelId = null;
let editingIsManaged = true;
let modalMode = "edit"; // "edit" or "create"
let modelFilesCache = null;
let modelsDirCache = "";

// Expose cache invalidation for HF download module
window.__metallamaInvalidateModelCache = () => { modelFilesCache = null; };

async function loadModelFiles() {
  if (modelFilesCache) return modelFilesCache;
  try {
    const data = await api("/api/model-files");
    modelFilesCache = data;
    modelsDirCache = data.models_dir || "";
    return data;
  } catch {
    return { files: [], models_dir: "" };
  }
}

function populateModelSelector(files, currentPath) {
  const select = document.getElementById("edit-model-path");
  select.innerHTML = "";

  const warning = document.getElementById("edit-model-warning");
  const normalizedCurrent = currentPath ? currentPath.replace(/^.*[\\/]/, "") : "";
  // Build full paths for option values
  const dir = modelsDirCache ? modelsDirCache.replace(/\/$/, "") + "/" : "";

  if (!files.length) {
    const opt = document.createElement("option");
    opt.value = currentPath || "";
    opt.textContent = currentPath || "(no .gguf files found)";
    opt.selected = true;
    select.appendChild(opt);
    warning.textContent = "⚠ No .gguf files found in METALLAMA_MODELS_DIR";
    warning.classList.remove("is-hidden");
    return;
  }

  // Check if current model is in the list
  const found = files.some((f) => {
    const fname = f.replace(/^.*[\\/]/, "");
    return fname === normalizedCurrent || currentPath?.includes(fname);
  });

  if (!found && currentPath) {
    // Prepend current (missing) model so user sees what's selected
    const opt = document.createElement("option");
    opt.value = currentPath;
    opt.textContent = `${normalizedCurrent} (not found)`;
    opt.selected = true;
    opt.style.color = "#ef4444";
    select.appendChild(opt);
    warning.textContent = `⚠ Model file not found locally: ${normalizedCurrent}`;
    warning.classList.remove("is-hidden");
  } else {
    warning.classList.add("is-hidden");
  }

  files.forEach((f) => {
    const opt = document.createElement("option");
    opt.value = dir + f;
    opt.textContent = f;
    if (found && currentPath?.includes(f.replace(/^.*[\\/]/, ""))) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });

  // Update warning when user changes selection
  select.onchange = () => {
    const val = select.value;
    const isMissing = select.selectedOptions[0]?.textContent.endsWith("(not found)");
    if (isMissing) {
      const fname = val.replace(/^.*[\\/]/, "");
      warning.textContent = `⚠ Model file not found locally: ${fname}`;
      warning.classList.remove("is-hidden");
    } else {
      warning.classList.add("is-hidden");
    }
  };
}

function populateModelDraftSelector(files, currentPath) {
  const select = document.getElementById("edit-model-draft");
  select.innerHTML = "";

  const warning = document.getElementById("edit-model-draft-warning");
  const normalizedCurrent = currentPath ? currentPath.replace(/^.*[\\/]/, "") : "";
  const dir = modelsDirCache ? modelsDirCache.replace(/\/$/, "") + "/" : "";

  // Always include a "None" option at the top
  const noneOpt = document.createElement("option");
  noneOpt.value = "";
  noneOpt.textContent = "(none)";
  noneOpt.selected = !currentPath;
  select.appendChild(noneOpt);

  if (!files.length) {
    if (currentPath) {
      const opt = document.createElement("option");
      opt.value = currentPath;
      opt.textContent = currentPath;
      opt.selected = true;
      select.appendChild(opt);
    }
    if (warning) warning.classList.add("is-hidden");
    return;
  }

  // Check if current draft model is in the list
  const found = files.some((f) => {
    const fname = f.replace(/^.*[\\/]/, "");
    return fname === normalizedCurrent || currentPath?.includes(fname);
  });

  if (!found && currentPath) {
    const opt = document.createElement("option");
    opt.value = currentPath;
    opt.textContent = `${normalizedCurrent} (not found)`;
    opt.selected = true;
    opt.style.color = "#ef4444";
    select.appendChild(opt);
    if (warning) {
      warning.textContent = `⚠ Draft model file not found locally: ${normalizedCurrent}`;
      warning.classList.remove("is-hidden");
    }
  } else {
    if (warning) warning.classList.add("is-hidden");
  }

  files.forEach((f) => {
    const opt = document.createElement("option");
    opt.value = dir + f;
    opt.textContent = f;
    if (found && currentPath?.includes(f.replace(/^.*[\\/]/, ""))) {
      opt.selected = true;
    }
    select.appendChild(opt);
  });
}

function setManagedOnlyVisible(visible) {
  document.querySelectorAll(".managed-only").forEach((el) => {
    el.classList.toggle("is-hidden", !visible);
  });
  document.querySelectorAll(".remote-only").forEach((el) => {
    el.classList.toggle("is-hidden", visible);
  });
}

function setCreateOnlyVisible(visible) {
  document.querySelectorAll(".create-only").forEach((el) => {
    el.classList.toggle("is-hidden", !visible);
  });
}

function clearModalFields() {
  document.getElementById("edit-name").value = "";
  document.getElementById("edit-url").value = "";
  document.getElementById("edit-model-path").innerHTML = "";
  document.getElementById("edit-model-draft").innerHTML = "";
  document.getElementById("edit-port").value = "";
  document.getElementById("edit-context-window").value = "";
  document.getElementById("edit-parallel").value = "";
  document.getElementById("edit-extra-args").value = "";
  const warning = document.getElementById("edit-model-warning");
  if (warning) warning.classList.add("is-hidden");
  const mtpWarning = document.getElementById("edit-model-draft-warning");
  if (mtpWarning) mtpWarning.classList.add("is-hidden");
}

function openEditModal(modelId, isManaged) {
  modalMode = "edit";
  const model = (async () => {
    if (isManaged) {
      return await api(`/api/models/${modelId}/status`);
    }
    // For remote servers, build data from the card directly
    const data = await api("/api/models");
    return (data.models || []).find((m) => m.id === modelId) || {};
  })();

  model.then((data) => {
    editingModelId = modelId;
    editingIsManaged = isManaged;
    setCreateOnlyVisible(false);
    setManagedOnlyVisible(isManaged);
    document.getElementById("modal-title").textContent = `Edit: ${data.display_name || data.id}`;
    document.getElementById("edit-name").value = data.display_name || data.id || "";
    document.getElementById("edit-url").value = data.url || "";
    if (isManaged) {
      document.getElementById("edit-model-path").value = data.model_path || "";
      document.getElementById("edit-port").value = data.port || "";
      document.getElementById("edit-context-window").value = data.context_window || "";
      document.getElementById("edit-parallel").value = data.parallel || "";
      document.getElementById("edit-extra-args").value = (data.extra_args || []).join("\n");
      // Populate model selector from available .gguf files
      loadModelFiles().then((mdata) => {
        populateModelSelector(mdata.files || [], data.model_path || "");
        populateModelDraftSelector(mdata.files || [], data.model_draft || "");
      });
    }
    document.getElementById("edit-modal").classList.remove("is-hidden");
    document.getElementById("modal-delete-btn").classList.remove("is-hidden");
  });
}

function openCreateModal(type, prefill = null) {
  modalMode = "create";
  editingModelId = null;
  const isManaged = type === "managed";
  editingIsManaged = isManaged;
  clearModalFields();
  setCreateOnlyVisible(true);
  setManagedOnlyVisible(isManaged);

  // Type selector default
  const typeSelect = document.getElementById("edit-server-type");
  if (typeSelect) typeSelect.value = type;

  document.getElementById("modal-title").textContent = isManaged ? "Add Local Server" : "Add Remote Server";
  if (isManaged) {
    loadModelFiles().then((mdata) => {
      populateModelSelector(mdata.files || [], prefill?.model_path || "");
      populateModelDraftSelector(mdata.files || [], "");
      if (prefill?.model_path) {
        const stem = prefill.model_path.replace(/^.*[\\/]/, "").replace(/\.gguf$/i, "");
        document.getElementById("edit-name").value = stem;
      }
    });
    // Pre-fill defaults: backend-suggested free port, CTX = 32K, PAR = 1
    api("/api/ports/suggest")
      .then((data) => {
        document.getElementById("edit-port").value = data.port;
      })
      .catch(() => {
        document.getElementById("edit-port").value = 8080;
      });
    document.getElementById("edit-context-window").value = 32000;
    document.getElementById("edit-parallel").value = 1;
  }
  document.getElementById("edit-modal").classList.remove("is-hidden");
  document.getElementById("modal-delete-btn").classList.add("is-hidden");
}

// Open the create modal pre-filled for a freshly downloaded model file.
export function openCreateForModel(modelPath) {
  openCreateModal("managed", { model_path: modelPath });
}

function closeEditModal() {
  document.getElementById("edit-modal").classList.add("is-hidden");
  editingModelId = null;
  modalMode = "edit";
}

async function deleteModal() {
  if (!editingModelId) return;
  const name = editingModelId;
  try {
    await api(`/api/models/${encodeURIComponent(name)}`, { method: "DELETE" });
    setConfigMessage(`Server "${name}" deleted`);
      window.__metallamaRefreshLibrary?.();
    closeEditModal();
    await refreshModels();
  } catch (err) {
    setConfigMessage(err.message, true);
  }
}

async function saveEditModal() {
  if (modalMode === "create") {
    return saveCreateModal();
  }
  if (!editingModelId) return;

  const newName = document.getElementById("edit-name").value.trim();
  const newUrl = document.getElementById("edit-url").value.trim();

  if (editingIsManaged) {
    const payload = {
      name: newName,
      model_path: document.getElementById("edit-model-path").value.trim(),
      model_draft: document.getElementById("edit-model-draft").value.trim(),
      port: parseInt(document.getElementById("edit-port").value, 10),
      context_window: parseInt(document.getElementById("edit-context-window").value, 10),
      parallel: parseInt(document.getElementById("edit-parallel").value, 10),
      extra_args: document.getElementById("edit-extra-args").value
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    Object.keys(payload).forEach((key) => {
      if (key === "extra_args" || key === "name" || key === "model_path" || key === "model_draft") return;
      if (isNaN(payload[key])) delete payload[key];
    });
    if (payload.name === "") delete payload.name;

    try {
      setCardError(editingModelId, "");
      await api(`/api/models/${editingModelId}/config`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setConfigMessage("Config updated");
      closeEditModal();
      await refreshModels();
    } catch (err) {
      setCardError(editingModelId, err.message);
      setConfigMessage(err.message, true);
    }
  } else {
    const payload = {};
    if (newName) payload.name = newName;
    if (newUrl) payload.url = newUrl;

    try {
      setCardError(editingModelId, "");
      await api(`/api/remote-servers/${encodeURIComponent(editingModelId)}/config`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setConfigMessage("Config updated");
      closeEditModal();
      await refreshModels();
    } catch (err) {
      setCardError(editingModelId, err.message);
      setConfigMessage(err.message, true);
    }
  }
}

async function saveCreateModal() {
  const type = document.getElementById("edit-server-type")?.value || "managed";
  const newName = document.getElementById("edit-name").value.trim();

  if (!newName) {
    setConfigMessage("Name is required", true);
    return;
  }

  if (type === "managed") {
    const payload = {
      type: "managed",
      name: newName,
      model_path: document.getElementById("edit-model-path").value.trim(),
      model_draft: document.getElementById("edit-model-draft").value.trim(),
      port: parseInt(document.getElementById("edit-port").value, 10),
      context_window: parseInt(document.getElementById("edit-context-window").value, 10) || 4096,
      parallel: parseInt(document.getElementById("edit-parallel").value, 10) || 1,
      extra_args: document.getElementById("edit-extra-args").value
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    if (!payload.model_path) {
      setConfigMessage("Model path is required", true);
      return;
    }
    if (isNaN(payload.port)) {
      setConfigMessage("Port is required", true);
      return;
    }
    if (!isNaN(payload.context_window) === false) delete payload.context_window;
    if (!isNaN(payload.parallel) === false) delete payload.parallel;

    try {
      await api("/api/models/create", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setConfigMessage(`Server "${newName}" created`);
      window.__metallamaRefreshLibrary?.();
      closeEditModal();
      await refreshModels();
    } catch (err) {
      setConfigMessage(err.message, true);
    }
  } else {
    const newUrl = document.getElementById("edit-url").value.trim();
    if (!newUrl) {
      setConfigMessage("URL is required for remote servers", true);
      return;
    }
    try {
      await api("/api/models/create", {
        method: "POST",
        body: JSON.stringify({ type: "remote", name: newName, url: newUrl }),
      });
      setConfigMessage(`Remote server "${newName}" created`);
      window.__metallamaRefreshLibrary?.();
      closeEditModal();
      await refreshModels();
    } catch (err) {
      setConfigMessage(err.message, true);
    }
  }
}

function setCardError(modelId, message = "") {
  if (!modelId) {
    return;
  }
  const normalized = String(message || "").trim();
  if (!normalized) {
    cardErrors.delete(modelId);
    return;
  }
  cardErrors.set(modelId, normalized);
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function canStart(model) {
  return model.status === "offline" && !inFlight.has(model.id);
}

function canStop(model) {
  return (model.status === "online" || model.status === "starting") && !inFlight.has(model.id);
}

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

function loadingStripHtml(model) {
  if (model.status !== "starting") return "";
  const elapsed = model.started_at
    ? Math.max(0, Math.round(Date.now() / 1000 - model.started_at))
    : 0;
  const progress = typeof model.load_progress === "number" ? model.load_progress : null;
  const pct = progress !== null ? Math.round(progress * 100) : null;
  const bar =
    pct !== null
      ? `<div class="loading-bar"><div class="loading-bar-fill determinate" style="width: ${pct}%"></div></div>`
      : `<div class="loading-bar"><div class="loading-bar-fill"></div></div>`;
  const label = pct !== null ? `Loading model… ${pct}% (${formatElapsed(elapsed)})` : `Loading model… ${formatElapsed(elapsed)}`;
  return `
    <div class="loading-strip">
      ${bar}
      <div class="loading-info">
        <span class="loading-elapsed">${label}</span>
        ${model.last_log ? `<span class="loading-lastlog" title="${escapeHtml(model.last_log)}">${escapeHtml(model.last_log)}</span>` : ""}
      </div>
    </div>`;
}

function modelTypeLabel(model) {
  const normalized = String(model.service || "").trim().toUpperCase();
  if (normalized === "LLM") return "LLM";
  return "LLM";
}

function cardAccentColor(managed) {
  return managed ? "#3B95DD" : "#8B5CF6";
}

function modelStem(model) {
  if (!model.model_path) return "";
  const fname = model.model_path.replace(/^.*[\\/]/, "");
  return fname.replace(/\.gguf$/i, "");
}

function slotIndicators(model) {
  if (model.status !== "online") return "";
  const cached = slotCache.get(model.id);
  const par = model.parallel || 0;
  // Determine how many dots to render: use live slot count if available,
  // otherwise fall back to PAR (managed servers only)
  let slotCount = cached?.slots?.length || 0;
  let dotCount = Math.max(slotCount, par);
  if (!dotCount) return ""; // no PAR info and no live data yet

  let html = `<div class="slot-indicators" data-slot-model="${model.id}" title="Loading slot status…">`;
  const slots = cached?.slots || [];
  for (let i = 0; i < dotCount; i++) {
    const s = slots[i];
    const cls = !s ? "unknown" : (s.is_processing ? "busy" : "free");
    html += `<span class="slot-dot ${cls}"></span>`;
  }
  html += `</div>`;
  return html;
}

async function refreshSlots(models) {
  const targets = (models || []).filter(
    (m) => m.status === "online" && !inFlight.has(m.id)
  );
  if (!targets.length) {
    for (const key of slotCache.keys()) {
      if (!targets.some((m) => m.id === key)) slotCache.delete(key);
    }
    return;
  }
  for (const key of slotCache.keys()) {
    if (!targets.some((m) => m.id === key)) slotCache.delete(key);
  }
  const results = await Promise.allSettled(
    targets.map(async (m) => {
      const data = await api(`/api/models/${encodeURIComponent(m.id)}/slots`);
      return { id: m.id, slots: data.slots || [] };
    })
  );
  for (const r of results) {
    if (r.status === "fulfilled") {
      slotCache.set(r.value.id, { slots: r.value.slots, ts: Date.now() });
    }
  }
}

function updateSlotIndicators() {
  // Update slot indicator DOM nodes. If a container is missing (because slot
  // data arrived after the initial render), inject it into the card's center col.
  document.querySelectorAll(".card[data-model-id]").forEach((card) => {
    const modelId = card.dataset.modelId;
    const cached = slotCache.get(modelId);
    if (!cached) return;
    const slots = cached.slots;
    if (!slots.length) return;
    const busy = slots.filter((s) => s.is_processing).length;
    let container = card.querySelector(".slot-indicators[data-slot-model]");
    if (!container) {
      const centerCol = card.querySelector(".card-center-col");
      if (!centerCol) return;
      container = document.createElement("div");
      container.className = "slot-indicators";
      container.dataset.slotModel = modelId;
      centerCol.appendChild(container);
    }
    container.title = `${busy}/${slots.length} slots busy`;
    // Rebuild dots to match the slot count
    container.innerHTML = slots
      .map((s) => `<span class="slot-dot ${s.is_processing ? "busy" : "free"}"></span>`)
      .join("");
  });
}

// ── Server logs panel ─────────────────────────────────────
function updateLogPanel(modelId) {
  const panel = document.querySelector(`.log-panel[data-log-model="${CSS.escape(modelId)}"]`);
  if (!panel) return;
  const pre = panel.querySelector(".log-output");
  const st = logState.get(modelId);
  if (!pre || !st) return;
  pre.textContent = st.text || "(no output yet)";
  pre.onscroll = () => {
    st.pinned = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
  };
  if (st.pinned !== false) pre.scrollTop = pre.scrollHeight;
}

function hydrateLogPanels() {
  for (const id of openLogs) updateLogPanel(id);
}

async function pollLogs() {
  for (const id of openLogs) {
    const st = logState.get(id);
    if (!st) continue;
    try {
      const data = await api(`/api/models/${encodeURIComponent(id)}/logs?since=${st.since}`);
      const lines = data.lines || [];
      if (lines.length) {
        st.text += (st.text ? "\n" : "") + lines.map((l) => l.text).join("\n");
        if (st.text.length > LOG_TEXT_CAP) {
          st.text = st.text.slice(st.text.indexOf("\n", st.text.length - LOG_TEXT_CAP) + 1);
        }
        st.since = data.next;
        updateLogPanel(id);
      }
    } catch {
      // server unreachable or model deleted — keep panel, retry next tick
    }
  }
}

function ensureLogTimer() {
  if (openLogs.size && !logTimer) {
    logTimer = setInterval(() => pollLogs().catch(() => {}), LOG_POLL_INTERVAL);
  } else if (!openLogs.size && logTimer) {
    clearInterval(logTimer);
    logTimer = null;
  }
}

async function toggleLogs(modelId) {
  if (openLogs.has(modelId)) {
    openLogs.delete(modelId);
    document
      .querySelector(`.log-panel[data-log-model="${CSS.escape(modelId)}"]`)
      ?.classList.add("is-hidden");
  } else {
    openLogs.add(modelId);
    logState.set(modelId, { since: 0, text: "", pinned: true });
    document
      .querySelector(`.log-panel[data-log-model="${CSS.escape(modelId)}"]`)
      ?.classList.remove("is-hidden");
    await pollLogs().catch(() => {});
    updateLogPanel(modelId);
  }
  ensureLogTimer();
}

function exitBannerHtml(model) {
  const exit = model.last_exit;
  if (!exit) return "";
  if (dismissedExits.get(model.id) === String(exit.at)) return "";
  const tail = (exit.tail || []).slice(-5).join("\n");
  return `
    <div class="card-exit-banner">
      <div class="exit-banner-head">
        <span class="exit-banner-title">⚠ Server exited unexpectedly (exit code ${exit.code})</span>
        <span class="exit-banner-actions">
          <button class="btn-secondary btn-small" data-id="${model.id}" data-action="logs">Logs</button>
          <button class="btn-secondary btn-small" data-id="${model.id}" data-action="dismiss-exit" data-at="${exit.at}">Dismiss</button>
        </span>
      </div>
      ${tail ? `<pre class="exit-banner-tail">${escapeHtml(tail)}</pre>` : ""}
    </div>`;
}

function cardTemplate(model) {
  const isManaged = model.managed !== false;
  const action = model.status === "online" || model.status === "starting" ? "stop" : "start";
  const label = action === "stop" ? "Stop" : "Start";
  const canRunAction = action === "stop" ? canStop(model) : canStart(model);
  const type = modelTypeLabel(model);
  const cardError = cardErrors.get(model.id) || "";
  const cardErrorClass = cardError ? "card-error visible" : "card-error";
  const accent = cardAccentColor(isManaged);
  const isLoading = inFlight.has(model.id);
  const overlayClass = isLoading ? "panel-overlay card-overlay" : "panel-overlay card-overlay is-hidden";
  const flightAction = inFlight.get(model.id) || action;
  const statusText = flightAction === "start" ? "Starting..." : "Stopping...";
  const stem = modelStem(model);

  const isLLM = type === "LLM";
  const ctxValue = model.context_window || "";
  const ctxKTokens = ctxValue ? Math.round(ctxValue / 1000) : "";
  const parValue = model.parallel || "";
  const slotsHtml = slotIndicators(model);
  const est = model.vram_estimate;
  const estWarn = est && est.likely_fits === false && model.status === "offline";
  const estTitle = est
    ? `Estimated VRAM (upper bound): weights ≈ ${est.weights_gb} GB + KV cache ≈ ${est.kv_cache_gb} GB + ~1 GB overhead.` +
      (est.free_vram_gb != null ? ` Free VRAM now: ${est.free_vram_gb} GB.` : "") +
      (estWarn ? " Likely will NOT fit — reduce context, parallel slots, or use a smaller quant." : "")
    : "";
  const estChip = est
    ? `<span class="info-item vram-est${estWarn ? " warn" : ""}" title="${escapeHtml(estTitle)}">≈${est.total_gb} GB${estWarn ? " ⚠" : ""}</span>`
    : "";
  const ctxDisplay =
    isLLM
      ? `
    <span class="info-item">CTX: ${ctxKTokens}k</span>
    ${parValue ? `<span class="info-item">PAR: ${parValue}</span>` : ""}
    ${estChip}
  `
      : "";

  const modelWarning = model.model_found === false
    ? `<p class="model-not-found-warning">Model weights not found locally</p>`
    : "";

  return `
    <article class="card ${model.status}" data-model-id="${model.id}" style="--card-accent: ${accent}">
      <div class="card-header-row">
        <div class="title-wrap">
          <h3>${model.display_name}</h3>
          ${stem ? `<span class="card-model-stem">${escapeHtml(stem)}</span>` : ""}
        </div>
        <div class="header-badges">
          <span class="locality-badge ${isManaged ? "local" : "remote"}">${isManaged ? "Local" : "Remote"}</span>
          <div class="status-badge ${model.status}">${model.status}</div>
        </div>
      </div>

      <div class="card-main-row">
        <div class="card-meta-col">
          <div class="endpoint-row">
            <span class="endpoint-label">URL:</span>
            <a class="endpoint-link" href="${model.url}" target="_blank">${model.url}</a>
            ${model.status === "online" ? `<button class="btn-secondary btn-small btn-chat" data-id="${model.id}" data-action="open" data-url="${model.url}" title="Open llama.cpp's chat UI">Chat ↗</button>` : ""}
          </div>

          <div class="info-row">
            ${isManaged && model.pid !== undefined ? `<span class="info-item">PID: ${model.pid ?? "-"}</span>` : ""}
            ${ctxDisplay}
            ${isManaged ? `<button class="btn-secondary btn-small admin-only" data-id="${model.id}" data-action="cmd" title="Copy launch command">CMD</button>` : ""}
            ${isManaged ? `<button class="btn-secondary btn-small ${openLogs.has(model.id) ? "active" : ""}" data-id="${model.id}" data-action="logs" title="Show server logs">Logs</button>` : ""}
            <button class="btn-secondary btn-small admin-only" data-id="${model.id}" data-managed="${isManaged}" data-action="edit" title="Edit server config">Edit</button>
          </div>
        </div>

        <div class="card-center-col">
          ${slotsHtml}
        </div>

        <div class="card-actions-col">
          ${isManaged
            ? `<button class="btn-action-${action} admin-only" data-id="${model.id}" data-action="${action}" ${canRunAction ? "" : "disabled"}>${label}</button>
               <button class="btn-action-${action} disabled-readonly" disabled title="Admin access required">${label}</button>`
            : `<button class="btn-action-start disabled-remote" disabled title="Remote servers cannot be managed from here">${model.status === "online" ? "Stop" : "Start"}</button>`
          }
        </div>
      </div>

      ${loadingStripHtml(model)}
      <p class="${cardErrorClass}" aria-live="polite">${escapeHtml(cardError)}</p>
      ${modelWarning}
      ${exitBannerHtml(model)}
      ${isManaged ? `<div class="log-panel ${openLogs.has(model.id) ? "" : "is-hidden"}" data-log-model="${model.id}">
        <div class="log-panel-head">
          <span class="log-panel-title">Server logs</span>
          <a class="log-open-page" href="/static/logs.html?model=${encodeURIComponent(model.id)}" target="_blank" rel="noopener" title="Open full log view in a new tab">Full view ↗</a>
        </div>
        <pre class="log-output"></pre>
      </div>` : ""}

      <div class="${overlayClass}">
        <div class="overlay-content">
          <div class="spinner"></div>
          <p class="overlay-status">${statusText}</p>
        </div>
      </div>
    </article>
  `;
}

function renderModels(models) {
  if (!modelsEl || !summaryEl) {
    return;
  }

  // Drop log-panel state for models that no longer exist
  for (const id of openLogs) {
    if (!models.some((m) => m.id === id)) {
      openLogs.delete(id);
      logState.delete(id);
    }
  }
  ensureLogTimer();

  const needle = filterText.trim().toLowerCase();
  const visible = models.filter((m) => {
    if (needle && !`${m.display_name} ${modelStem(m)}`.toLowerCase().includes(needle)) return false;
    if (filterStatus === "running") return m.status === "online" || m.status === "starting";
    if (filterStatus === "offline") return m.status === "offline";
    return true;
  });

  modelsEl.innerHTML = visible.map(cardTemplate).join("");
  hydrateLogPanels();
  document.getElementById("models-filter-empty")?.classList.toggle("is-hidden", visible.length > 0 || models.length === 0);
  const running = models.filter((m) => m.status === "online").length;
  summaryEl.textContent = `${running} / ${models.length} running`;
}

export async function refreshModels() {
  const activeElement = document.activeElement;
  if (activeElement && (activeElement.classList?.contains("ctx-inline-input") || activeElement.classList?.contains("par-inline-input"))) {
    return;
  }

  const data = await api("/api/models");
  const models = data.models || [];
  renderModels(models);
  // Fetch slot status on a throttled cadence (every 5s) to avoid contending
  // with active inference. Non-blocking so it never delays the next refresh.
  const now = Date.now();
  if (now - lastSlotRefresh >= SLOT_REFRESH_INTERVAL) {
    lastSlotRefresh = now;
    refreshSlots(models).then(updateSlotIndicators).catch(() => {});
  } else {
    updateSlotIndicators();
  }
}

async function waitForStop(modelId) {
  for (let i = 0; i < 60; i++) {
    const data = await api(`/api/models/${modelId}/status`);
    if (data.status === "offline") return;
    await sleep(500);
  }
  throw new Error("Timed out waiting for server to stop (30s).");
}

// After a start request, only wait until the process is up ("starting" or
// "online"). Model loading can take minutes; the card's loading strip tracks
// it, and a crash surfaces through the unexpected-exit banner.
async function waitForSpawn(modelId) {
  for (let i = 0; i < 10; i++) {
    await sleep(500);
    const data = await api(`/api/models/${modelId}/status`);
    if (data.status !== "offline") return;
  }
}

async function restartModel(modelId) {
  inFlight.set(modelId, "restart");
  await refreshModels();

  try {
    await api(`/api/models/${modelId}/stop`, { method: "POST" });
    setCardError(modelId, "");
    await waitForStop(modelId);
    await api(`/api/models/${modelId}/start`, { method: "POST" });
    await waitForSpawn(modelId);
  } finally {
    inFlight.delete(modelId);
    await refreshModels();
  }
}

async function startStop(modelId, action) {
  if (action === "restart") {
    return restartModel(modelId);
  }

  if (action === "start") {
    try {
      const m = await api(`/api/models/${encodeURIComponent(modelId)}/status`);
      const est = m.vram_estimate;
      if (est && est.likely_fits === false) {
        const ok = window.confirm(
          `This model is estimated to need ≈${est.total_gb} GB VRAM ` +
          `(weights ${est.weights_gb} GB + KV cache ${est.kv_cache_gb} GB), ` +
          `but only ${est.free_vram_gb} GB is free.\n\n` +
          `It will likely fail to load or run partially on CPU. Start anyway?`
        );
        if (!ok) return;
      }
    } catch {
      // estimate unavailable — proceed
    }
  }

  inFlight.set(modelId, action);
  await refreshModels();
  try {
    await api(`/api/models/${modelId}/${action}`, { method: "POST" });
    setCardError(modelId, "");
    if (action === "start") {
      await waitForSpawn(modelId);
    } else {
      await waitForStop(modelId);
    }
  } finally {
    inFlight.delete(modelId);
    await refreshModels();
  }
}

export function setupModels() {
  if (!modelsEl) {
    return;
  }

  modelsEl.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }

    const modelId = target.dataset.id;
    const action = target.dataset.action;
    const url = target.dataset.url;
    if (!modelId || !action) {
      return;
    }

    try {
      if (action === "copy") {
        if (!url) {
          throw new Error("Missing URL");
        }
        await copyToClipboard(url);
        setConfigMessage("Endpoint copied");
        return;
      }

      if (action === "cmd") {
        const data = await api(`/api/models/${modelId}/command`);
        await copyToClipboard(data.command);
        setCardError(modelId, "");
        setConfigMessage("Launch command copied to clipboard");
        return;
      }

      if (action === "open") {
        if (!url) {
          throw new Error("Missing URL");
        }
        window.open(url, "_blank", "noopener,noreferrer");
        return;
      }

      if (action === "logs") {
        await toggleLogs(modelId);
        await refreshModels();
        return;
      }

      if (action === "dismiss-exit") {
        dismissedExits.set(modelId, target.dataset.at || "");
        await refreshModels();
        return;
      }

      if (action === "edit") {
        const isManaged = target.dataset.managed !== "false";
        openEditModal(modelId, isManaged);
        return;
      }

      await startStop(modelId, action);
    } catch (err) {
      setCardError(modelId, err.message);
      await refreshModels();
      setConfigMessage(err.message, true);
    }
  });

  // ── Modal event listeners ──────────────────────────────
  const modal = document.getElementById("edit-modal");
  if (modal) {
    modal.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) return;
      const action = target.dataset.action;
      if (action === "modal-close" || action === "modal-cancel") {
        closeEditModal();
      } else if (action === "modal-save") {
        saveEditModal();
      } else if (action === "modal-delete") {
        deleteModal();
      }
    });

    // Close on overlay click (outside dialog)
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeEditModal();
      }
    });

    // Close on Escape key
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.classList.contains("is-hidden")) {
        closeEditModal();
      }
    });
  }

  // ── Server filter controls ────────────────────────────
  const filterInput = document.getElementById("server-filter");
  if (filterInput) {
    filterInput.addEventListener("input", () => {
      filterText = filterInput.value;
      refreshModels().catch(() => {});
    });
  }
  document.querySelectorAll(".status-filter .chip-btn").forEach((chip) => {
    chip.addEventListener("click", () => {
      filterStatus = chip.dataset.status || "all";
      document.querySelectorAll(".status-filter .chip-btn").forEach((c) => {
        c.classList.toggle("active", c === chip);
      });
      refreshModels().catch(() => {});
    });
  });

  // ── Add Server button ─────────────────────────────────
  const addBtn = document.getElementById("add-model-btn");
  if (addBtn) {
    addBtn.addEventListener("click", () => {
      openCreateModal("managed");
    });
  }

  // ── Type selector in create mode ──────────────────────
  const typeSelect = document.getElementById("edit-server-type");
  if (typeSelect) {
    typeSelect.addEventListener("change", () => {
      if (modalMode !== "create") return;
      const isManaged = typeSelect.value === "managed";
      editingIsManaged = isManaged;
      setManagedOnlyVisible(isManaged);
      document.getElementById("modal-title").textContent = isManaged ? "Add Local Server" : "Add Remote Server";
      if (isManaged) {
        loadModelFiles().then((mdata) => populateModelSelector(mdata.files || [], ""));
      }
    });
  }

  // ── Stem button in edit modal ─────────────────────────
  const stemBtn = document.getElementById("edit-stem-btn");
  if (stemBtn) {
    stemBtn.addEventListener("click", () => {
      const select = document.getElementById("edit-model-path");
      const currentVal = select?.value || "";
      if (currentVal) {
        const fname = currentVal.replace(/^.*[\\/]/, "").replace(/\.gguf$/i, "");
        document.getElementById("edit-name").value = fname;
      }
    });
  }

  // ── Defaults modal ───────────────────────────────────
  const defaultsModal = document.getElementById("defaults-modal");
  const defaultsBtn = document.getElementById("defaults-btn");
  const defaultsArgs = document.getElementById("defaults-args");

  async function openDefaultsModal() {
    try {
      const data = await api("/api/engine-defaults");
      const args = data.defaults?.llama || [];
      defaultsArgs.value = args.join("\n");
      defaultsModal.classList.remove("is-hidden");
    } catch (err) {
      setConfigMessage(err.message, true);
    }
  }

  function closeDefaultsModal() {
    defaultsModal.classList.add("is-hidden");
  }

  if (defaultsBtn) {
    defaultsBtn.addEventListener("click", openDefaultsModal);
  }

  if (defaultsModal) {
    defaultsModal.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) return;
      const action = target.dataset.action;
      if (action === "defaults-close" || action === "defaults-cancel") {
        closeDefaultsModal();
      } else if (action === "defaults-save") {
        const args = defaultsArgs.value.split("\n").map((s) => s.trim()).filter(Boolean);
        try {
          await api("/api/engine-defaults", {
            method: "POST",
            body: JSON.stringify({ engine: "llama", args }),
          });
          setConfigMessage("Default params saved");
          closeDefaultsModal();
        } catch (err) {
          setConfigMessage(err.message, true);
        }
      }
    });

    defaultsModal.addEventListener("click", (event) => {
      if (event.target === defaultsModal) closeDefaultsModal();
    });
  }
}
