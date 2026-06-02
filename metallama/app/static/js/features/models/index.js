import { api } from "../../core/api.js";
import { copyToClipboard } from "../../core/clipboard.js";
import { setConfigMessage } from "../../core/uiMessage.js";

const modelsEl = document.getElementById("models");
const summaryEl = document.getElementById("summary");

const inFlight = new Set();
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

  if (model.engine === "whisper") {
    return "AUDIO";
  }
  if (model.engine === "mineru") {
    return "OCR";
  }
  return "LLM";
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

  const isLLM = type === "LLM";
  const isStopped = model.status === "stopped";
  const ctxValue = model.context_window || "";
  const ctxKTokens = ctxValue ? Math.round(ctxValue / 1000) : "";
  const ctxDisplay =
    isLLM
      ? isStopped
        ? `
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
  `
        : `
    <span class="info-item">CTX: ${ctxKTokens}k</span>
  `
      : "";

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
  if (!modelsEl || !summaryEl) {
    return;
  }

  modelsEl.innerHTML = models.map(cardTemplate).join("");
  const running = models.filter((m) => m.status === "running").length;
  summaryEl.textContent = `${running} / ${models.length} ACTIVE SERVERS`;
}

export async function refreshModels() {
  const activeElement = document.activeElement;
  if (activeElement && activeElement.classList?.contains("ctx-inline-input")) {
    return;
  }

  const data = await api("/api/models");
  renderModels(data.models || []);
}

async function restartModel(modelId) {
  inFlight.add(modelId);
  await refreshModels();

  try {
    await api(`/api/models/${modelId}/stop`, { method: "POST" });
    setCardError(modelId, "");

    for (let i = 0; i < 60; i++) {
      const data = await api(`/api/models/${modelId}/status`);
      if (data.status === "stopped") {
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }

    await api(`/api/models/${modelId}/start`, { method: "POST" });

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
    return restartModel(modelId);
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

      await startStop(modelId, action);
    } catch (err) {
      setCardError(modelId, err.message);
      await refreshModels();
      setConfigMessage(err.message, true);
    }
  });

  modelsEl.addEventListener(
    "blur",
    async (event) => {
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
        target.dataset.originalValue = String(newValue);
        setConfigMessage("Context window updated");
        setTimeout(() => {
          refreshModels().catch(() => {});
        }, 100);
      } catch (err) {
        setCardError(modelId, `Failed to save context: ${err.message}`);
        setTimeout(() => {
          refreshModels().catch(() => {});
        }, 100);
      }
    },
    true,
  );

  modelsEl.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") {
      return;
    }

    const target = event.target;
    if (!(target instanceof HTMLInputElement) || !target.classList.contains("ctx-inline-input")) {
      return;
    }

    event.preventDefault();
    target.blur();
  });
}
