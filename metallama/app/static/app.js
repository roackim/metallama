const modelsEl = document.getElementById("models");
const uiMessageEl = document.getElementById("ui-message");
const summaryEl = document.getElementById("summary");
const themeButtons = document.querySelectorAll(".theme-btn");
const heroLogoEl = document.getElementById("hero-logo");
const vramStatusEl = document.getElementById("vram-status");
const transcriptFormEl = document.getElementById("transcript-form");
const audioFileEl = document.getElementById("audio-file");
const fileLabelEl = document.querySelector(".service-audio .file-drop-label");
const languageEl = document.getElementById("transcript-language");
const timecodesEl = document.getElementById("timecodes");
const transcribeBtnEl = document.getElementById("transcribe-btn");
const transcriptOverlayEl = document.getElementById("transcript-overlay");
const transcriptStatusEl = document.getElementById("transcript-status");
const cancelTranscriptBtnEl = document.getElementById("cancel-transcript-btn");
const transcriptErrorEl = document.getElementById("transcript-error");
const transcriptLiveEl = document.getElementById("transcript-live");
const transcriptOutputSectionEl = document.getElementById("transcript-output-section");
const copyTranscriptBtnEl = document.getElementById("copy-transcript-btn");
const downloadTranscriptBtnEl = document.getElementById("download-transcript-btn");

const ocrFormEl = document.getElementById("ocr-form");
const ocrFileEl = document.getElementById("ocr-file");
const ocrFileLabelEl = document.querySelector(".service-ocr .file-drop-label");
const ocrParseMethodEl = document.getElementById("ocr-parse-method");
const ocrBtnEl = document.getElementById("ocr-btn");
const ocrClearBtnEl = document.getElementById("ocr-clear-btn");
const ocrOverlayEl = document.getElementById("ocr-overlay");
const ocrStatusEl = document.getElementById("ocr-status");
const cancelOcrBtnEl = document.getElementById("cancel-ocr-btn");
const ocrErrorEl = document.getElementById("ocr-error");
const ocrLiveEl = document.getElementById("ocr-live");
const ocrImageCountEl = document.getElementById("ocr-image-count");
const ocrQueueListEl = document.getElementById("ocr-queue-list");
const ocrDetailFilenameEl = document.getElementById("ocr-detail-filename");
const ocrDetailStatusEl = document.getElementById("ocr-detail-status");
const ocrOutputSectionEl = document.getElementById("ocr-output-section");
const copyOcrBtnEl = document.getElementById("copy-ocr-btn");
const downloadOcrBtnEl = document.getElementById("download-ocr-btn");
const downloadOcrZipBtnEl = document.getElementById("download-ocr-zip-btn");
const OCR_ADD_LABEL = "Add documents [+]";
const OCR_QUEUE_FILE_ICON_SVG = '<svg class="ocr-queue-file-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
const OCR_QUEUE_ARCHIVE_ICON_SVG = '<svg class="ocr-queue-file-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="4"/><path d="M5 8h14v12H5z"/><path d="M10 12h4"/></svg>';
const OCR_QUEUE_DOWNLOAD_ICON_SVG = '<svg class="ocr-queue-action-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>';

const THEME_KEY = "metallama.theme";

let inFlight = new Set();
let transcriptionInFlight = false;
let ocrInFlight = false;
let transcriptAbortController = null;
let ocrAbortController = null;
let ocrCancelRequested = false;
let ocrQueue = [];
let ocrSelectedId = null;
let ocrModelIdCache = null;
const cardErrors = new Map();

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

function setConfigMessage(msg, isError = false) {
  uiMessageEl.textContent = msg;
  uiMessageEl.classList.toggle("error", isError);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const detail = data.detail || `Request failed (${response.status})`;
    throw new Error(detail);
  }

  return data;
}

function canStart(model) {
  return model.status === "stopped" && !inFlight.has(model.id);
}

function canStop(model) {
  return model.status === "running" && !inFlight.has(model.id);
}

function modelTypeLabel(model) {
  const normalized = String(model.service || "").trim().toUpperCase();
  if (["LLM", "AUDIO", "DOCS", "OCR"].includes(normalized)) {
    return normalized;
  }

  // Backward compatibility fallback during reloads.
  if (model.engine === "whisper") {
    return "AUDIO";
  }
  if (model.engine === "mineru") {
    return "OCR";
  }
  return "LLM";
}

function getThemePreference() {
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark" || saved === "system") {
    return saved;
  }
  return "system";
}

function resolveSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(themePreference) {
  const theme = themePreference === "system" ? resolveSystemTheme() : themePreference;
  document.documentElement.dataset.theme = theme;

  const titleLogo = document.getElementById("hero-logo");
  if (titleLogo) {
    titleLogo.src =
      theme === "dark" ? "/static/assets/logo-carre-blanc.svg" : "/static/assets/logo-carre-noir.svg";
  }

  themeButtons.forEach((button) => {
    const isActive = button.dataset.theme === themePreference;
    button.classList.toggle("active", isActive);
  });
}

function setupThemeSwitcher() {
  const pref = getThemePreference();
  applyTheme(pref);

  themeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const nextTheme = button.dataset.theme;
      window.localStorage.setItem(THEME_KEY, nextTheme);
      applyTheme(nextTheme);
    });
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (getThemePreference() === "system") {
      applyTheme("system");
    }
  });
}

function cardAccentColor(type) {
  const colors = { LLM: "#3B95DD", AUDIO: "#F4A501", OCR: "#8EC561", DOCS: "#8EC561" };
  return colors[type] || "var(--line)";
}

function cardTemplate(model) {
  const action = model.status === "running" ? "stop" : "start";
  const label = action === "stop" ? "Stop" : "Start";
  const canRunAction = action === "stop" ? canStop(model) : canStart(model);
  const type = modelTypeLabel(model);
  const cardError = cardErrors.get(model.id) || "";
  const cardErrorClass = cardError ? "card-error visible" : "card-error";
  const accent = cardAccentColor(type);
  const isLoading = inFlight.has(model.id);
  const overlayClass = isLoading ? "panel-overlay card-overlay" : "panel-overlay card-overlay is-hidden";
  const statusText = action === "start" ? "Starting..." : "Stopping...";

  // Context window display for LLM servers
  const isLLM = type === "LLM";
  const isStopped = model.status === "stopped";
  const ctxValue = model.context_window || "";
  const ctxKTokens = ctxValue ? Math.round(ctxValue / 1000) : "";
  const ctxDisplay = isLLM ? (isStopped ? `
    <span class="info-item ctx-editable" data-model-id="${model.id}">
      CTX: <input 
        type="number" 
        class="ctx-inline-input" 
        data-model-id="${model.id}" 
        data-original-value="${ctxValue}"
        value="${ctxKTokens}" 
        min="1" 
        step="1"
        placeholder="Auto"
        title="Context window in k tokens (editable when stopped)"
      />k
    </span>
  ` : `
    <span class="info-item">CTX: ${ctxKTokens}k</span>
  `) : "";

  return `
    <article class="card ${model.status}" data-model-id="${model.id}" style="--card-accent: ${accent}">
      <div class="card-header-row">
        <div class="title-wrap">
          <h3>${model.display_name}</h3>
          <span class="model-name-muted">${model.id}</span>
          <span class="type-label ${type.toLowerCase()}">${type}</span>
        </div>
        <div class="status-badge ${model.status}">${model.status}</div>
      </div>

      <div class="card-main-row">
        <div class="card-meta-col">
          <div class="endpoint-row">
            <span class="endpoint-label">URL:</span>
            <a class="endpoint-link" href="${model.url}" target="_blank">${model.url}</a>
          </div>

          <div class="info-row">
            <span class="info-item">PORT: ${model.port}</span>
            <span class="info-item">PID: ${model.pid ?? "-"}</span>
            ${ctxDisplay}
            <button class="btn-secondary btn-small" data-id="${model.id}" data-action="cmd" title="Copy launch command">CMD</button>
          </div>
        </div>

        <p class="description">${model.description}</p>

        <div class="card-actions-col">
          <button class="btn-action-${action}" data-id="${model.id}" data-action="${action}" ${canRunAction ? "" : "disabled"}>${label}</button>
        </div>
      </div>

      <p class="${cardErrorClass}" aria-live="polite">${cardError}</p>

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
  modelsEl.innerHTML = models.map(cardTemplate).join("");

  const running = models.filter((m) => m.status === "running").length;
  summaryEl.textContent = `${running} / ${models.length} ACTIVE SERVERS`;
}

async function refreshModels() {
  // Don't refresh if user is editing a context input field
  const activeElement = document.activeElement;
  if (activeElement && activeElement.classList.contains("ctx-inline-input")) {
    return;
  }
  
  const data = await api("/api/models");
  renderModels(data.models || []);
}

async function startStop(modelId, action) {
  const targetStatus = action === "start" ? "running" : "stopped";
  inFlight.add(modelId);
  await refreshModels();
  try {
    await api(`/api/models/${modelId}/${action}`, { method: "POST" });
    setCardError(modelId, "");
    for (let i = 0; i < 60; i++) {
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === targetStatus) {
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
  } finally {
    inFlight.delete(modelId);
    await refreshModels();
  }
}

async function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const temp = document.createElement("textarea");
  temp.value = text;
  document.body.appendChild(temp);
  temp.select();
  document.execCommand("copy");
  document.body.removeChild(temp);
}

function sanitizeFilename(input) {
  return String(input || "")
    .replace(/\.[^/.]+$/, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
}

function downloadMarkdownFile(fileNameBase, markdownText) {
  const base = sanitizeFilename(fileNameBase) || "output";
  const blob = new Blob([markdownText], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${base}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
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

    await startStop(modelId, action);
  } catch (err) {
    setCardError(modelId, err.message);
    await refreshModels();
    setConfigMessage(err.message, true);
  }
});

// Handle context window input changes
modelsEl.addEventListener("input", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || !target.classList.contains("ctx-inline-input")) {
    return;
  }

  const modelId = target.dataset.modelId;
  if (!modelId) {
    return;
  }

  // No need to change button text since we're in stopped state
});

// Save context window on blur (when user leaves the field)
modelsEl.addEventListener("blur", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || !target.classList.contains("ctx-inline-input")) {
    return;
  }

  const modelId = target.dataset.modelId;
  const kTokens = parseInt(target.value, 10);

  if (!modelId || isNaN(kTokens) || kTokens < 1) {
    return;
  }

  const newValue = kTokens * 1000;

  try {
    await api(`/api/models/${modelId}/config`, {
      method: "POST",
      body: JSON.stringify({ context_window: newValue }),
    });
    
    // Update the original value so we know it's been saved
    target.dataset.originalValue = String(newValue);
    setConfigMessage("Context window updated");
    
    // Delay refresh to allow click events to process first
    setTimeout(() => {
      refreshModels().catch(() => {});
    }, 100);
  } catch (err) {
    setCardError(modelId, `Failed to save context: ${err.message}`);
    setTimeout(() => {
      refreshModels().catch(() => {});
    }, 100);
  }
}, true);

// Handle Enter key to validate context window input
modelsEl.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") {
    return;
  }

  const target = event.target;
  if (!(target instanceof HTMLInputElement) || !target.classList.contains("ctx-inline-input")) {
    return;
  }

  event.preventDefault();
  target.blur(); // Trigger blur event which saves the value
});

async function restartModel(modelId) {
  // Stop then start
  inFlight.add(modelId);
  await refreshModels();
  
  try {
    // Stop
    await api(`/api/models/${modelId}/stop`, { method: "POST" });
    setCardError(modelId, "");
    
    // Wait for it to stop
    for (let i = 0; i < 60; i++) {
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === "stopped") {
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    
    // Start
    await api(`/api/models/${modelId}/start`, { method: "POST" });
    
    // Wait for it to start
    for (let i = 0; i < 60; i++) {
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === "running") {
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
  } finally {
    inFlight.delete(modelId);
    await refreshModels();
  }
}

async function startStop(modelId, action) {
  if (action === "restart") {
    return await restartModel(modelId);
  }
  
  const targetStatus = action === "start" ? "running" : "stopped";
  inFlight.add(modelId);
  await refreshModels();
  try {
    await api(`/api/models/${modelId}/${action}`, { method: "POST" });
    setCardError(modelId, "");
    for (let i = 0; i < 60; i++) {
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === targetStatus) {
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
  } finally {
    inFlight.delete(modelId);
    await refreshModels();
  }
}

async function init() {
  setupThemeSwitcher();
  setupTranscriptUI();
  setupOcrUI();
  await refreshModels();
  await refreshVram();
  setInterval(() => {
    refreshModels().catch(() => {});
  }, 2000);
  setInterval(() => {
    refreshVram().catch(() => {});
  }, 3000);
}

async function refreshVram() {
  try {
    const data = await api("/api/system/vram");
    if (!data.available || !data.gpus || data.gpus.length === 0) {
      vramStatusEl.textContent = "VRAM: N/A";
      return;
    }
    
    // Show total across all GPUs
    const totalUsed = data.gpus.reduce((sum, gpu) => sum + gpu.used_gb, 0);
    const totalMax = data.gpus.reduce((sum, gpu) => sum + gpu.total_gb, 0);
    const avgPercent = data.gpus.reduce((sum, gpu) => sum + gpu.percent, 0) / data.gpus.length;
    
    vramStatusEl.textContent = `VRAM: ${totalUsed.toFixed(1)} GB / ${totalMax.toFixed(1)} GB (${avgPercent.toFixed(0)}%)`;
  } catch (err) {
    vramStatusEl.textContent = "VRAM: --";
  }
}

function updateTranscriptStatus(statusText) {
  transcriptStatusEl.textContent = statusText || "Working...";
}

function setTranscriptionRunning(running) {
  transcriptionInFlight = running;
  transcribeBtnEl.disabled = running;
  audioFileEl.disabled = running;
  languageEl.disabled = running;
  timecodesEl.disabled = running;
  cancelTranscriptBtnEl.disabled = !running;
  transcriptOverlayEl.classList.toggle("is-hidden", !running);
}

const FILE_ICON_SVG = '<svg class="file-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

function updateFileLabel() {
  const file = audioFileEl.files?.[0];
  if (file) {
    fileLabelEl.innerHTML = `${FILE_ICON_SVG} ${file.name}`;
    fileLabelEl.classList.add("file-selected");
  } else {
    fileLabelEl.textContent = "Drop audio file here or click to select";
    fileLabelEl.classList.remove("file-selected");
  }
}

function setTranscriptError(message = "") {
  if (!message) {
    transcriptErrorEl.textContent = "";
    transcriptErrorEl.classList.remove("visible");
    return;
  }

  transcriptErrorEl.textContent = message;
  transcriptErrorEl.classList.add("visible");
}

function updateOcrStatus(statusText) {
  ocrStatusEl.textContent = statusText || "Working...";
}

function setOcrRunning(running) {
  ocrInFlight = running;
  ocrBtnEl.disabled = running;
  ocrFileEl.disabled = running;
  ocrParseMethodEl.disabled = running;
  cancelOcrBtnEl.disabled = !running;
}

function updateOcrFileLabel() {
  if (ocrQueue.length > 0) {
    ocrFileLabelEl.textContent = "";
    ocrFileLabelEl.classList.add("file-selected");
  } else {
    ocrFileLabelEl.textContent = OCR_ADD_LABEL;
    ocrFileLabelEl.classList.remove("file-selected");
  }
}

function ocrFileKey(file) {
  return `${file.name}::${file.size}::${file.lastModified}`;
}

function addFilesToOcrQueue(files) {
  if (!files.length || ocrInFlight) {
    return;
  }

  if (ocrQueue.some((item) => item.status !== "pending")) {
    ocrQueue = [];
    ocrSelectedId = null;
  }

  const seen = new Set(ocrQueue.map((item) => ocrFileKey(item.file)));
  let idx = ocrQueue.length;
  for (const file of files) {
    const key = ocrFileKey(file);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    ocrQueue.push({
      id: `staged-${Date.now()}-${idx}-${file.name}`,
      name: file.name,
      file,
      status: "pending",
      markdown: "",
      zipId: null,
      imageCount: 0,
      error: "",
    });
    idx += 1;
  }

  if (!ocrSelectedId && ocrQueue.length > 0) {
    ocrSelectedId = ocrQueue[0].id;
  }
}

function stageOcrQueueFromInput() {
  if (ocrInFlight) {
    return;
  }

  const files = Array.from(ocrFileEl.files || []);
  addFilesToOcrQueue(files);
  ocrFileEl.value = "";
  updateOcrFileLabel();
  updateOcrVisibility();
}

function setOcrError(message = "") {
  if (!message) {
    ocrErrorEl.textContent = "";
    ocrErrorEl.classList.remove("visible");
    return;
  }

  ocrErrorEl.textContent = message;
  ocrErrorEl.classList.add("visible");
}

function getSelectedOcrItem() {
  return ocrQueue.find((item) => item.id === ocrSelectedId) || null;
}

function statusClass(status) {
  if (status === "done") {
    return "status-done";
  }
  if (status === "processing") {
    return "status-processing";
  }
  if (status === "error") {
    return "status-error";
  }
  if (status === "canceled") {
    return "status-canceled";
  }
  return "status-pending";
}

function withExtension(fileName, extension) {
  const base = String(fileName || "output").replace(/\.[^/.]+$/, "");
  return `${base}${extension}`;
}

async function resolveOcrModelId() {
  if (ocrModelIdCache) {
    return ocrModelIdCache;
  }

  const data = await api("/api/models");
  const model = (data.models || []).find((entry) => String(entry.service || "").toUpperCase() === "OCR");
  ocrModelIdCache = model?.id || null;
  return ocrModelIdCache;
}

async function ensureOcrServerReady() {
  const modelId = await resolveOcrModelId();
  if (!modelId) {
    throw new Error("OCR server profile not found");
  }

  const statusPayload = await api(`/api/models/${modelId}/status`);
  if (statusPayload.status === "running") {
    return;
  }

  try {
    await api(`/api/models/${modelId}/start`, { method: "POST" });
  } catch (err) {
    const message = String(err?.message || "").toLowerCase();
    if (!message.includes("already running")) {
      throw err;
    }
  }

  for (let i = 0; i < 30; i += 1) {
    const probe = await api(`/api/models/${modelId}/status`);
    if (probe.status === "running") {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error("OCR server is not ready");
}

function statusLabel(status) {
  if (status === "done") {
    return "DONE";
  }
  if (status === "processing") {
    return "PROCESSING";
  }
  if (status === "error") {
    return "ERROR";
  }
  if (status === "canceled") {
    return "CANCELED";
  }
  return "PENDING";
}

function renderOcrQueue() {
  if (!ocrQueueListEl) {
    return;
  }
  ocrQueueListEl.innerHTML = ocrQueue
    .map((item) => {
      const active = item.id === ocrSelectedId ? "active" : "";
      const klass = statusClass(item.status);
      const isZipReady = item.status === "done" && Boolean(item.zipId);
      const displayName = isZipReady ? withExtension(item.name, ".ocr.zip") : item.name;
      const icon = isZipReady ? OCR_QUEUE_ARCHIVE_ICON_SVG : OCR_QUEUE_FILE_ICON_SVG;
      const removeDisabled = ocrInFlight ? "disabled" : "";
      const actionButton = isZipReady
        ? `<button class="ocr-queue-action ocr-queue-download" type="button" data-ocr-download-id="${item.id}" aria-label="Download ${displayName}" title="Download ${displayName}">${OCR_QUEUE_DOWNLOAD_ICON_SVG}</button>`
        : `<button class="ocr-queue-action ocr-queue-remove" type="button" data-ocr-remove-id="${item.id}" ${removeDisabled} aria-label="Remove ${item.name}">X</button>`;
      return `<li class="ocr-queue-item ${klass} ${active}">
        <button class="ocr-queue-main" type="button" data-ocr-item-id="${item.id}" title="${item.name}">
          ${icon}
          <span class="ocr-queue-name">${displayName}</span>
        </button>
        ${actionButton}
      </li>`;
    })
    .join("");
}

function allDoneWithZip() {
  return (
    ocrQueue.length > 0 &&
    ocrQueue.every((item) => item.status === "done" && Boolean(item.zipId))
  );
}

async function triggerZipDownload(zipId, fallbackName = "ocr_output.zip") {
  const response = await fetch(`/api/ocr/zip/${zipId}`);
  if (!response.ok) {
    throw new Error("ZIP download failed");
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";\n]+)"?/);
  const zipName = match ? match[1] : fallbackName;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = zipName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function downloadAllOcrZipBundle() {
  const items = ocrQueue
    .filter((item) => item.status === "done" && item.zipId)
    .map((item) => ({ zip_id: item.zipId, file_name: item.name }));

  if (items.length === 0) {
    setConfigMessage("No ZIP available", true);
    return;
  }

  const response = await fetch("/api/ocr/zip/bundle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "ZIP bundle download failed");
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";\n]+)"?/);
  const name = match ? match[1] : "ocr_bundle.zip";

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderOcrDetail() {
  const item = getSelectedOcrItem();
  if (!item) {
    ocrDetailFilenameEl.textContent = "Preview";
    ocrDetailStatusEl.textContent = "";
    ocrDetailStatusEl.classList.add("is-hidden");
    ocrLiveEl.textContent = "No result selected yet.";
    ocrImageCountEl.textContent = "";
    ocrImageCountEl.classList.add("is-hidden");
    copyOcrBtnEl.disabled = true;
    downloadOcrBtnEl.disabled = true;
    downloadOcrZipBtnEl.disabled = true;
    downloadOcrZipBtnEl.classList.add("is-hidden");
    return;
  }

  ocrDetailFilenameEl.textContent = withExtension(item.name, ".md");
  if (item.status === "error") {
    ocrDetailStatusEl.textContent = item.error || "OCR failed";
    ocrDetailStatusEl.classList.remove("is-hidden");
  } else if (item.status === "processing") {
    ocrDetailStatusEl.textContent = "Processing...";
    ocrDetailStatusEl.classList.remove("is-hidden");
  } else if (item.status === "pending") {
    ocrDetailStatusEl.textContent = "Pending";
    ocrDetailStatusEl.classList.remove("is-hidden");
  } else if (item.status === "canceled") {
    ocrDetailStatusEl.textContent = "Canceled";
    ocrDetailStatusEl.classList.remove("is-hidden");
  } else {
    ocrDetailStatusEl.textContent = "";
    ocrDetailStatusEl.classList.add("is-hidden");
  }

  if (item.status === "done") {
    ocrLiveEl.textContent = item.markdown || "";
    if (item.imageCount > 0) {
      ocrImageCountEl.textContent = `${item.imageCount} images extracted`;
      ocrImageCountEl.classList.remove("is-hidden");
    } else {
      ocrImageCountEl.textContent = "";
      ocrImageCountEl.classList.add("is-hidden");
    }
  } else {
    ocrLiveEl.textContent = "";
    ocrImageCountEl.textContent = "";
    ocrImageCountEl.classList.add("is-hidden");
  }

  const ready = item.status === "done" && Boolean((item.markdown || "").trim());
  copyOcrBtnEl.disabled = !ready;
  downloadOcrBtnEl.disabled = !ready;

  const hasZip = ready && Boolean(item.zipId);
  downloadOcrZipBtnEl.disabled = !hasZip;
  downloadOcrZipBtnEl.classList.toggle("is-hidden", !hasZip);
}

function updateOcrOverlayForSelection() {
  const item = getSelectedOcrItem();
  const shouldShow = Boolean(
    ocrInFlight && item && (item.status === "pending" || item.status === "processing")
  );

  ocrOverlayEl.classList.toggle("is-hidden", !shouldShow);
  if (!shouldShow) {
    return;
  }

  if (item.status === "pending") {
    updateOcrStatus("Waiting in queue...");
  } else {
    updateOcrStatus(`Processing ${item.name}`);
  }
}

function updateOcrVisibility() {
  ocrOutputSectionEl.classList.remove("is-hidden");
  renderOcrQueue();
  renderOcrDetail();
  updateOcrOverlayForSelection();

  if (allDoneWithZip() && !ocrInFlight) {
    ocrBtnEl.textContent = "Download all (.zip)";
  } else {
    ocrBtnEl.textContent = "Extract text";
  }

  if (ocrClearBtnEl) {
    const canClear = !ocrInFlight && ocrQueue.length >= 2;
    ocrClearBtnEl.disabled = !canClear;
    ocrClearBtnEl.classList.toggle("is-hidden", !canClear);
  }
}

function updateTranscriptVisibility() {
  const hasText = Boolean((transcriptLiveEl.textContent || "").trim());
  transcriptOutputSectionEl.classList.toggle("is-hidden", !hasText);
}

function setupTranscriptUI() {
  if (!transcriptFormEl) {
    return;
  }

  updateTranscriptVisibility();

  audioFileEl.addEventListener("change", updateFileLabel);

  const dropZone = transcriptFormEl.querySelector(".file-drop");
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (eventName === "drop") {
        const dt = event.dataTransfer;
        if (dt?.files?.length) {
          audioFileEl.files = dt.files;
          updateFileLabel();
        }
      }
      dropZone.classList.remove("drag-over");
    });
  });

  transcriptFormEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (transcriptionInFlight) {
      return;
    }

    const file = audioFileEl.files?.[0];
    if (!file) {
      setTranscriptError("Choose an audio file first");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("language", languageEl.value);
    formData.append("include_timecodes", String(Boolean(timecodesEl.checked)));

    transcriptLiveEl.textContent = "";
    setTranscriptError("");
    setTranscriptionRunning(true);
    updateTranscriptVisibility();
    updateTranscriptStatus("Uploading and preparing...");
    transcriptAbortController = new AbortController();

    try {
      const response = await fetch("/api/transcript/stream", {
        method: "POST",
        body: formData,
        signal: transcriptAbortController.signal,
      });

      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(text || `Request failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            continue;
          }

          let payload;
          try {
            payload = JSON.parse(trimmed);
          } catch {
            continue;
          }

          if (payload.event === "queued") {
            updateTranscriptStatus(payload.message || "Queued...");
          }

          if (payload.event === "status") {
            updateTranscriptStatus(payload.message || "Working...");
          }

          if (payload.event === "partial") {
            transcriptLiveEl.textContent = payload.text || "";
            updateTranscriptVisibility();
            updateTranscriptStatus(`Transcribing ${payload.chunk_index || ""}/${payload.chunk_total || ""}`);
          }

          if (payload.event === "done") {
            transcriptLiveEl.textContent = payload.text || "";
            updateTranscriptVisibility();
          }

          if (payload.event === "error") {
            throw new Error(payload.message || "Transcription failed");
          }
        }
      }
    } catch (err) {
      const message = err.name === "AbortError" ? "Transcription canceled" : err.message || "Transcription failed";
      setConfigMessage(message, true);
      setTranscriptError(message);
    } finally {
      transcriptAbortController = null;
      setTranscriptionRunning(false);
      updateTranscriptVisibility();
    }
  });

  cancelTranscriptBtnEl.addEventListener("click", () => {
    if (transcriptionInFlight && transcriptAbortController) {
      transcriptAbortController.abort();
    }
  });

  copyTranscriptBtnEl.addEventListener("click", async () => {
    const text = transcriptLiveEl.textContent || "";
    if (!text.trim()) {
      setConfigMessage("No transcript text to copy", true);
      return;
    }

    try {
      await copyToClipboard(text);
      setConfigMessage("Transcript copied");
    } catch (err) {
      setConfigMessage(err.message || "Copy failed", true);
    }
  });

  downloadTranscriptBtnEl.addEventListener("click", () => {
    const text = transcriptLiveEl.textContent || "";
    if (!text.trim()) {
      setConfigMessage("No transcript text to download", true);
      return;
    }

    downloadMarkdownFile(`transcript-${new Date().toISOString().slice(0, 10)}`, text);
    setConfigMessage("Transcript markdown downloaded");
  });
}

function setupOcrUI() {
  if (!ocrFormEl) {
    return;
  }

  updateOcrVisibility();
  ocrFileEl.addEventListener("change", () => {
    updateOcrFileLabel();
    stageOcrQueueFromInput();
  });

  const dropZone = ocrFormEl.querySelector(".ocr-drop-zone");
  if (!dropZone) {
    return;
  }

  dropZone.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest(".ocr-queue-main") || target.closest(".ocr-queue-action")) {
      return;
    }
    ocrFileEl.click();
  });

  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      ocrFileEl.click();
    }
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (eventName === "drop") {
        const dt = event.dataTransfer;
        if (dt?.files?.length) {
          addFilesToOcrQueue(Array.from(dt.files));
          updateOcrFileLabel();
          updateOcrVisibility();
        }
      }
      dropZone.classList.remove("drag-over");
    });
  });

  if (ocrQueueListEl) {
    ocrQueueListEl.addEventListener("click", (event) => {
      const target = event.target;
      const downloadButton = target instanceof Element ? target.closest("[data-ocr-download-id]") : null;
      if (downloadButton instanceof HTMLButtonElement) {
        const downloadId = downloadButton.dataset.ocrDownloadId;
        const item = ocrQueue.find((entry) => entry.id === downloadId);
        if (!item?.zipId) {
          return;
        }
        triggerZipDownload(item.zipId, withExtension(item.name, ".ocr.zip")).catch((err) => {
          setConfigMessage(err.message || "ZIP download failed", true);
        });
        return;
      }

      const removeButton = target instanceof Element ? target.closest("[data-ocr-remove-id]") : null;
      if (removeButton instanceof HTMLButtonElement) {
        if (ocrInFlight) {
          return;
        }
        const removeId = removeButton.dataset.ocrRemoveId;
        if (!removeId) {
          return;
        }
        ocrQueue = ocrQueue.filter((item) => item.id !== removeId);
        if (ocrSelectedId === removeId) {
          ocrSelectedId = ocrQueue[0]?.id || null;
        }
        updateOcrFileLabel();
        updateOcrVisibility();
        return;
      }

      const rowButton = target instanceof Element ? target.closest("[data-ocr-item-id]") : null;
      if (!(rowButton instanceof HTMLButtonElement)) {
        return;
      }
      const itemId = rowButton.dataset.ocrItemId;
      if (!itemId) {
        return;
      }
      event.stopPropagation();
      ocrSelectedId = itemId;
      updateOcrVisibility();
    });
  }

  if (ocrClearBtnEl) {
    ocrClearBtnEl.addEventListener("click", () => {
      if (ocrInFlight) {
        return;
      }
      ocrQueue = [];
      ocrSelectedId = null;
      ocrFileEl.value = "";
      setOcrError("");
      updateOcrFileLabel();
      updateOcrVisibility();
    });
  }

  ocrFormEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (ocrInFlight) {
      return;
    }

    if (allDoneWithZip()) {
      try {
        await downloadAllOcrZipBundle();
        setConfigMessage("OCR bundle downloaded");
      } catch (err) {
        setConfigMessage(err.message || "ZIP bundle download failed", true);
      }
      return;
    }

    const files = ocrQueue.map((item) => item.file);
    if (files.length === 0) {
      setOcrError("Choose at least one document file");
      return;
    }

    for (const file of files) {
      const suffix = (file.name.split(".").pop() || "").toLowerCase();
      if (!["pdf", "png", "jpg", "jpeg"].includes(suffix)) {
        setOcrError(`Unsupported format for ${file.name}. Use PDF, PNG, JPG, or JPEG.`);
        return;
      }
    }

    const method = ocrParseMethodEl.value || "fast";
    if (method === "precise") {
      setOcrError("Precise mode is not implemented yet");
      return;
    }

    const wantZip = true;

    // New extraction run starts a fresh queue/results snapshot.
    ocrQueue = files.map((file, index) => ({
      id: `${Date.now()}-${index}-${file.name}`,
      name: file.name,
      file,
      status: "pending",
      markdown: "",
      zipId: null,
      imageCount: 0,
      error: "",
    }));
    ocrSelectedId = ocrQueue[0]?.id || null;

    setOcrError("");
    setOcrRunning(true);
    ocrCancelRequested = false;
    updateOcrVisibility();
    updateOcrStatus(`Queued ${ocrQueue.length} file${ocrQueue.length > 1 ? "s" : ""}...`);
    ocrAbortController = new AbortController();

    try {
      let done = 0;
      let errors = 0;
      let canceled = 0;

      for (let index = 0; index < ocrQueue.length; index += 1) {
        const item = ocrQueue[index];
        if (ocrCancelRequested) {
          canceled += 1;
          continue;
        }

        updateOcrStatus(`Checking OCR server ${index + 1}/${ocrQueue.length}...`);
        try {
          await ensureOcrServerReady();
        } catch (err) {
          item.status = "error";
          item.error = `Server unavailable: ${err.message || "OCR service check failed"}`;
          errors += 1;
          updateOcrVisibility();
          setOcrError("OCR server unavailable. Check the Reader service status.");
          continue;
        }

        item.status = "processing";
        ocrSelectedId = item.id;
        updateOcrVisibility();
        updateOcrStatus(`Processing ${index + 1}/${ocrQueue.length}: ${item.name}`);

        const formData = new FormData();
        formData.append("file", item.file);
        formData.append("parse_method", "auto");
        formData.append("extract_images", "true");

        try {
          const response = await fetch("/api/ocr/parse", {
            method: "POST",
            body: formData,
            signal: ocrAbortController.signal,
          });

          if (!response.ok) {
            const payload = await response.json().catch(async () => ({ detail: await response.text() }));
            throw new Error(payload.detail || `Request failed (${response.status})`);
          }

          const data = await response.json();
          const markdown = String(data.markdown || "");
          if (!markdown.trim()) {
            throw new Error("OCR completed but no markdown was returned");
          }

          item.markdown = markdown;
          item.zipId = data.zip_id || null;
          item.imageCount = Number(data.image_count || 0);
          item.error = "";
          item.status = "done";
          done += 1;
          updateOcrVisibility();
        } catch (err) {
          if (err.name === "AbortError") {
            item.status = "canceled";
            item.error = "Canceled";
            canceled += 1;
            ocrCancelRequested = true;
          } else {
            item.status = "error";
            item.error = err.message || "OCR extraction failed";
            errors += 1;
          }
          updateOcrVisibility();
        }
      }

      const summary = `${done} done${errors ? `, ${errors} error` : ""}${canceled ? `, ${canceled} canceled` : ""}`;
      setConfigMessage(summary, errors > 0);
      if (errors > 0) {
        setOcrError(`${errors} file${errors > 1 ? "s" : ""} failed. Select a file to see details.`);
      } else if (canceled > 0) {
        setOcrError("OCR canceled");
      } else {
        setOcrError("");
      }
    } catch (err) {
      const message = err.name === "AbortError" ? "OCR canceled" : err.message || "OCR extraction failed";
      setConfigMessage(message, true);
      setOcrError(message);
    } finally {
      ocrCancelRequested = false;
      ocrAbortController = null;
      setOcrRunning(false);
      updateOcrStatus("Idle");
      updateOcrFileLabel();
      updateOcrVisibility();
    }
  });

  cancelOcrBtnEl.addEventListener("click", () => {
    if (ocrInFlight && ocrAbortController) {
      ocrCancelRequested = true;
      ocrAbortController.abort();
    }
  });

  copyOcrBtnEl.addEventListener("click", async () => {
    const item = getSelectedOcrItem();
    const text = item?.markdown || "";
    if (!text.trim()) {
      setConfigMessage("No OCR text to copy", true);
      return;
    }

    try {
      await copyToClipboard(text);
      setConfigMessage("OCR markdown copied");
    } catch (err) {
      setConfigMessage(err.message || "Copy failed", true);
    }
  });

  downloadOcrBtnEl.addEventListener("click", () => {
    const item = getSelectedOcrItem();
    const text = item?.markdown || "";
    if (!text.trim()) {
      setConfigMessage("No OCR text to download", true);
      return;
    }

    const sourceName = item?.name || "ocr-output";
    downloadMarkdownFile(sourceName, text);
    setConfigMessage("OCR markdown downloaded");
  });

  downloadOcrZipBtnEl.addEventListener("click", async () => {
    const item = getSelectedOcrItem();
    if (!item?.zipId) {
      setConfigMessage("No ZIP available", true);
      return;
    }

    try {
      await triggerZipDownload(item.zipId, withExtension(item.name, ".ocr.zip"));

      setConfigMessage("OCR ZIP downloaded");
    } catch (err) {
      setConfigMessage(err.message || "ZIP download failed", true);
    }
  });
}

init().catch((err) => {
  setConfigMessage(err.message, true);
});
