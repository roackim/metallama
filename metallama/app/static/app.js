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
const transcriptProgressWrapEl = document.getElementById("transcript-progress-wrap");
const transcriptProgressEl = document.getElementById("transcript-progress");
const transcriptProgressValueEl = document.getElementById("transcript-progress-value");
const transcriptStatusEl = document.getElementById("transcript-status");
const transcriptErrorEl = document.getElementById("transcript-error");
const transcriptLiveEl = document.getElementById("transcript-live");
const transcriptOutputSectionEl = document.getElementById("transcript-output-section");
const copyTranscriptBtnEl = document.getElementById("copy-transcript-btn");

const THEME_KEY = "metallama.theme";

let inFlight = new Set();
let transcriptionInFlight = false;
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
  await refreshModels();
  setInterval(() => {
    refreshModels().catch(() => {});
  }, 2000);
}

function updateTranscriptProgress(value, statusText) {
  const normalizedValue = Math.max(0, Math.min(100, Number(value || 0)));
  transcriptProgressEl.style.width = `${normalizedValue}%`;
  transcriptProgressValueEl.textContent = `${Math.round(normalizedValue)}%`;
  const progressTrack = transcriptProgressEl.closest(".transcript-progress-track");
  if (progressTrack) {
    progressTrack.setAttribute("aria-valuenow", String(Math.round(normalizedValue)));
  }
  transcriptStatusEl.textContent = statusText || "Working...";
}

function setTranscriptionRunning(running) {
  transcriptionInFlight = running;
  transcribeBtnEl.disabled = running;
  audioFileEl.disabled = running;
  languageEl.disabled = running;
  timecodesEl.disabled = running;
  transcriptProgressWrapEl.classList.toggle("is-hidden", !running);
  if (!running) {
    updateTranscriptProgress(0, "Idle");
  }
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
      setTranscriptError("");
      updateTranscriptProgress(0, "Choose an audio file first");
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
    updateTranscriptProgress(0, "Uploading and preparing...");

    try {
      const response = await fetch("/api/transcript/stream", {
        method: "POST",
        body: formData,
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
            updateTranscriptProgress(payload.progress || 1, payload.message || "Queued...");
          }

          if (payload.event === "status") {
            updateTranscriptProgress(payload.progress || 0, payload.message || "Working...");
          }

          if (payload.event === "partial") {
            transcriptLiveEl.textContent = payload.text || "";
            updateTranscriptVisibility();
            updateTranscriptProgress(payload.progress || 0, `Transcribing ${payload.chunk_index || ""}/${payload.chunk_total || ""}`);
          }

          if (payload.event === "done") {
            transcriptLiveEl.textContent = payload.text || "";
            updateTranscriptVisibility();
            const elapsed = Number(payload.elapsed_ms || 0);
            const elapsedSec = (elapsed / 1000).toFixed(1);
            updateTranscriptProgress(100, `Completed in ${elapsedSec}s`);
          }

          if (payload.event === "error") {
            throw new Error(payload.message || "Transcription failed");
          }
        }
      }
    } catch (err) {
      const message = err.message || "Transcription failed";
      setConfigMessage(message, true);
      setTranscriptError(message);
      updateTranscriptProgress(0, message);
    } finally {
      setTranscriptionRunning(false);
      updateTranscriptVisibility();
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
}

init().catch((err) => {
  setConfigMessage(err.message, true);
});
