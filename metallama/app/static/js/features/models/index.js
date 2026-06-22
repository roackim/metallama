import { api } from "../../core/api.js";
import { copyToClipboard } from "../../core/clipboard.js";
import { setConfigMessage } from "../../core/uiMessage.js";

const modelsEl = document.getElementById("models");
const summaryEl = document.getElementById("summary");

const inFlight = new Map(); // modelId -> "start" | "stop"
const cardErrors = new Map();
const slotCache = new Map(); // modelId -> { slots: [...], ts: number }

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

function populateMtpModelSelector(files, currentPath) {
  const select = document.getElementById("edit-mtp-model-path");
  select.innerHTML = "";

  const warning = document.getElementById("edit-mtp-model-warning");
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

  // Check if current MTP model is in the list
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
      warning.textContent = `⚠ MTP model file not found locally: ${normalizedCurrent}`;
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
  document.getElementById("edit-mtp-model-path").innerHTML = "";
  document.getElementById("edit-port").value = "";
  document.getElementById("edit-context-window").value = "";
  document.getElementById("edit-parallel").value = "";
  document.getElementById("edit-extra-args").value = "";
  const warning = document.getElementById("edit-model-warning");
  if (warning) warning.classList.add("is-hidden");
  const mtpWarning = document.getElementById("edit-mtp-model-warning");
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
        populateMtpModelSelector(mdata.files || [], data.mtp_model_path || "");
      });
    }
    document.getElementById("edit-modal").classList.remove("is-hidden");
    document.getElementById("modal-delete-btn").classList.remove("is-hidden");
  });
}

function openCreateModal(type) {
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
      populateModelSelector(mdata.files || [], "");
      populateMtpModelSelector(mdata.files || [], "");
    });
    // Pre-fill defaults: port = max + 1, CTX = 32K, PAR = 2
    api("/api/models").then((data) => {
      const models = data.models || [];
      const maxPort = models.reduce((max, m) => {
        if (m.managed && m.port && m.port > max) return m.port;
        return max;
      }, 0);
      document.getElementById("edit-port").value = maxPort > 0 ? maxPort + 1 : 8080;
      document.getElementById("edit-context-window").value = 32000;
      document.getElementById("edit-parallel").value = 2;
    });
  }
  document.getElementById("edit-modal").classList.remove("is-hidden");
  document.getElementById("modal-delete-btn").classList.add("is-hidden");
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
      mtp_model_path: document.getElementById("edit-mtp-model-path").value.trim(),
      port: parseInt(document.getElementById("edit-port").value, 10),
      context_window: parseInt(document.getElementById("edit-context-window").value, 10),
      parallel: parseInt(document.getElementById("edit-parallel").value, 10),
      extra_args: document.getElementById("edit-extra-args").value
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    Object.keys(payload).forEach((key) => {
      if (key === "extra_args" || key === "name" || key === "model_path" || key === "mtp_model_path") return;
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
      mtp_model_path: document.getElementById("edit-mtp-model-path").value.trim(),
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

function canStart(model) {
  return model.status === "offline" && !inFlight.has(model.id);
}

function canStop(model) {
  return model.status === "online" && !inFlight.has(model.id);
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
  if (model.managed === false || model.status !== "online") return "";
  const cached = slotCache.get(model.id);
  const par = model.parallel || 1;
  let slots = cached?.slots;
  // If we don't have live data yet, render placeholder dots based on PAR count
  if (!slots) {
    let html = `<div class="slot-indicators" data-slot-model="${model.id}" title="Loading slot status…">`;
    for (let i = 0; i < par; i++) {
      html += `<span class="slot-dot unknown"></span>`;
    }
    html += `</div>`;
    return html;
  }
  // If upstream returned fewer slots than PAR, pad; if more, show all
  const count = Math.max(slots.length, par);
  let html = `<div class="slot-indicators" data-slot-model="${model.id}" title="${slots.filter(s => s.is_processing).length}/${slots.length} slots busy">`;
  for (let i = 0; i < count; i++) {
    const s = slots[i];
    const cls = !s ? "unknown" : (s.is_processing ? "busy" : "free");
    html += `<span class="slot-dot ${cls}"></span>`;
  }
  html += `</div>`;
  return html;
}

async function refreshSlots(models) {
  const targets = (models || []).filter(
    (m) => m.managed !== false && m.status === "online" && !inFlight.has(m.id)
  );
  if (!targets.length) {
    // Clear stale cache for servers no longer online
    for (const key of slotCache.keys()) {
      if (!targets.some((m) => m.id === key)) slotCache.delete(key);
    }
    return;
  }
  // Clear stale entries
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
  // Update only the slot indicator DOM nodes without full re-render
  document.querySelectorAll(".slot-indicators[data-slot-model]").forEach((el) => {
    const modelId = el.dataset.slotModel;
    const cached = slotCache.get(modelId);
    if (!cached) return;
    const slots = cached.slots;
    const busy = slots.filter((s) => s.is_processing).length;
    el.title = `${busy}/${slots.length} slots busy`;
    // Rebuild dots
    const existing = el.querySelectorAll(".slot-dot");
    slots.forEach((s, i) => {
      const dot = existing[i];
      if (!dot) return;
      const cls = s.is_processing ? "busy" : "free";
      if (!dot.classList.contains(cls)) {
        dot.classList.remove("free", "busy", "unknown");
        dot.classList.add(cls);
      }
    });
  });
}

function cardTemplate(model) {
  const isManaged = model.managed !== false;
  const action = model.status === "online" ? "stop" : "start";
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
  const ctxDisplay =
    isLLM
      ? `
    <span class="info-item">CTX: ${ctxKTokens}k</span>
    ${parValue ? `<span class="info-item">PAR: ${parValue}</span>` : ""}
    ${slotsHtml}
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
          </div>

          <div class="info-row">
            ${isManaged && model.pid !== undefined ? `<span class="info-item">PID: ${model.pid ?? "-"}</span>` : ""}
            ${ctxDisplay}
            ${isManaged ? `<button class="btn-secondary btn-small admin-only" data-id="${model.id}" data-action="cmd" title="Copy launch command">CMD</button>` : ""}
            <button class="btn-secondary btn-small admin-only" data-id="${model.id}" data-managed="${isManaged}" data-action="edit" title="Edit server config">Edit</button>
          </div>
        </div>

        <p class="description">${model.description || ""}</p>

        <div class="card-actions-col">
          ${isManaged ? `<button class="btn-action-${action} admin-only" data-id="${model.id}" data-action="${action}" ${canRunAction ? "" : "disabled"}>${label}</button>` : ""}
        </div>
      </div>

      <p class="${cardErrorClass}" aria-live="polite">${cardError}</p>
      ${modelWarning}

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

  modelsEl.innerHTML = models.map(cardTemplate).join("");
  const running = models.filter((m) => m.status === "online").length;
  summaryEl.textContent = `${running} / ${models.length} ACTIVE SERVERS`;
}

export async function refreshModels() {
  const activeElement = document.activeElement;
  if (activeElement && (activeElement.classList?.contains("ctx-inline-input") || activeElement.classList?.contains("par-inline-input"))) {
    return;
  }

  const data = await api("/api/models");
  const models = data.models || [];
  renderModels(models);
  // Fetch slot status for online managed servers, then update dots in place
  refreshSlots(models).then(updateSlotIndicators).catch(() => {});
}

async function restartModel(modelId) {
  inFlight.set(modelId, "restart");
  await refreshModels();

  try {
    await api(`/api/models/${modelId}/stop`, { method: "POST" });
    setCardError(modelId, "");

    for (let i = 0; i < 60; i++) {
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === "offline") break;
      await new Promise((r) => setTimeout(r, 500));
    }

    await api(`/api/models/${modelId}/start`, { method: "POST" });

    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === "online") return;
      if (data.status === "offline" && i > 1) {
        throw new Error("Server process exited unexpectedly after restart. Check CMD for details.");
      }
    }
    throw new Error("Timed out waiting for server to come online after restart (30s).");
  } finally {
    inFlight.delete(modelId);
    await refreshModels();
  }
}

async function startStop(modelId, action) {
  if (action === "restart") {
    return restartModel(modelId);
  }

  const targetStatus = action === "start" ? "online" : "offline";
  inFlight.set(modelId, action);
  await refreshModels();
  try {
    const startResp = await api(`/api/models/${modelId}/${action}`, { method: "POST" });
    setCardError(modelId, "");

    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === targetStatus) {
        return; // success
      }
      // Process died during startup — stop polling and report
      if (action === "start" && data.status === "offline" && i > 1) {
        throw new Error("Server process exited unexpectedly. Check the launch command (CMD) for details.");
      }
    }
    // Timed out
    if (action === "start") {
      throw new Error("Timed out waiting for server to come online (30s).");
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
