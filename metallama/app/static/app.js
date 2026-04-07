const modelsEl = document.getElementById("models");
const uiMessageEl = document.getElementById("ui-message");
const summaryEl = document.getElementById("summary");
const themeButtons = document.querySelectorAll(".theme-btn");
const heroLogoEl = document.getElementById("hero-logo");
const transcriptFormEl = document.getElementById("transcript-form");
const audioFileEl = document.getElementById("audio-file");
const fileLabelEl = document.getElementById("file-label");
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
const ocrFileLabelEl = document.getElementById("ocr-file-label");
const ocrParseMethodEl = document.getElementById("ocr-parse-method");
const ocrBtnEl = document.getElementById("ocr-btn");
const ocrOverlayEl = document.getElementById("ocr-overlay");
const ocrStatusEl = document.getElementById("ocr-status");
const cancelOcrBtnEl = document.getElementById("cancel-ocr-btn");
const ocrErrorEl = document.getElementById("ocr-error");
const ocrLiveEl = document.getElementById("ocr-live");
const ocrOutputSectionEl = document.getElementById("ocr-output-section");
const copyOcrBtnEl = document.getElementById("copy-ocr-btn");
const downloadOcrBtnEl = document.getElementById("download-ocr-btn");

const THEME_KEY = "metallama.theme";

let inFlight = new Set();
let transcriptionInFlight = false;
let ocrInFlight = false;
let transcriptAbortController = null;
let ocrAbortController = null;
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

function cardTemplate(model) {
  const action = model.status === "running" ? "stop" : "start";
  const label = action === "stop" ? "Stop" : "Start";
  const canRunAction = action === "stop" ? canStop(model) : canStart(model);
  const type = modelTypeLabel(model);
  const cardError = cardErrors.get(model.id) || "";
  const cardErrorClass = cardError ? "card-error visible" : "card-error";

  return `
    <article class="card ${model.status}">
      <div class="card-header-row">
        <div class="title-wrap">
          <span class="type-label ${type.toLowerCase()}">${type}</span>
          <h3>${model.display_name}</h3>
          <span class="model-name-muted">${model.id}</span>
        </div>
        <div class="spacer"></div>
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
            <button class="btn-secondary btn-small" data-id="${model.id}" data-action="cmd" title="Copy launch command">CMD</button>
          </div>
        </div>

        <p class="description">${model.description}</p>

        <div class="card-actions-col">
          <button class="btn-action-${action}" data-id="${model.id}" data-action="${action}" ${canRunAction ? "" : "disabled"}>${label}</button>
        </div>
      </div>

      <p class="${cardErrorClass}" aria-live="polite">${cardError}</p>
    </article>
  `;
}

function renderModels(models) {
  modelsEl.innerHTML = models.map(cardTemplate).join("");

  const running = models.filter((m) => m.status === "running").length;
  summaryEl.textContent = `${running} / ${models.length} ACTIVE SERVERS`;
}

async function refreshModels() {
  const data = await api("/api/models");
  renderModels(data.models || []);
}

async function startStop(modelId, action) {
  inFlight.add(modelId);
  try {
    await api(`/api/models/${modelId}/${action}`, { method: "POST" });
    setCardError(modelId, "");
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

async function init() {
  setupThemeSwitcher();
  setupTranscriptUI();
  setupOcrUI();
  await refreshModels();
  setInterval(() => {
    refreshModels().catch(() => {});
  }, 2000);
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

function updateFileLabel() {
  const file = audioFileEl.files?.[0];
  fileLabelEl.textContent = file ? `Selected: ${file.name}` : "No file selected";
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
  ocrOverlayEl.classList.toggle("is-hidden", !running);
}

function updateOcrFileLabel() {
  const file = ocrFileEl.files?.[0];
  ocrFileLabelEl.textContent = file ? `Selected: ${file.name}` : "No file selected";
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

function updateOcrVisibility() {
  const hasText = Boolean((ocrLiveEl.textContent || "").trim());
  const shouldShow = ocrInFlight || hasText;
  ocrOutputSectionEl.classList.toggle("is-hidden", !shouldShow);
}

function updateTranscriptVisibility() {
  const hasText = Boolean((transcriptLiveEl.textContent || "").trim());
  const shouldShow = transcriptionInFlight || hasText;
  transcriptOutputSectionEl.classList.toggle("is-hidden", !shouldShow);
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
  ocrFileEl.addEventListener("change", updateOcrFileLabel);

  const dropZone = ocrFormEl.querySelector(".file-drop");
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
          ocrFileEl.files = dt.files;
          updateOcrFileLabel();
        }
      }
      dropZone.classList.remove("drag-over");
    });
  });

  ocrFormEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (ocrInFlight) {
      return;
    }

    const file = ocrFileEl.files?.[0];
    if (!file) {
      setOcrError("Choose a document file first");
      return;
    }

    const suffix = (file.name.split(".").pop() || "").toLowerCase();
    if (!["pdf", "png", "jpg", "jpeg"].includes(suffix)) {
      setOcrError("Unsupported format. Use PDF, PNG, JPG, or JPEG.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("parse_method", ocrParseMethodEl.value || "auto");
    formData.append("backend", "pipeline");

    ocrLiveEl.textContent = "";
    setOcrError("");
    setOcrRunning(true);
    updateOcrVisibility();
    updateOcrStatus("Uploading file...");
    ocrAbortController = new AbortController();

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

      updateOcrStatus("Parsing document...");
      const data = await response.json();
      const markdown = String(data.markdown || "");
      if (!markdown.trim()) {
        throw new Error("OCR completed but no markdown was returned");
      }

      ocrLiveEl.textContent = markdown;
      ocrLiveEl.dataset.sourceName = data.filename || file.name;
      updateOcrVisibility();
      setConfigMessage("OCR extraction finished");
    } catch (err) {
      const message = err.name === "AbortError" ? "OCR canceled" : err.message || "OCR extraction failed";
      setConfigMessage(message, true);
      setOcrError(message);
    } finally {
      ocrAbortController = null;
      setOcrRunning(false);
      updateOcrVisibility();
    }
  });

  cancelOcrBtnEl.addEventListener("click", () => {
    if (ocrInFlight && ocrAbortController) {
      ocrAbortController.abort();
    }
  });

  copyOcrBtnEl.addEventListener("click", async () => {
    const text = ocrLiveEl.textContent || "";
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
    const text = ocrLiveEl.textContent || "";
    if (!text.trim()) {
      setConfigMessage("No OCR text to download", true);
      return;
    }

    const sourceName = ocrLiveEl.dataset.sourceName || "ocr-output";
    downloadMarkdownFile(sourceName, text);
    setConfigMessage("OCR markdown downloaded");
  });
}

init().catch((err) => {
  setConfigMessage(err.message, true);
});
