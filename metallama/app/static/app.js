const modelsEl = document.getElementById("models");
const uiMessageEl = document.getElementById("ui-message");
const summaryEl = document.getElementById("summary");
const themeButtons = document.querySelectorAll(".theme-btn");
const heroLogoEl = document.getElementById("hero-logo");

const THEME_KEY = "metallama.theme";

let inFlight = new Set();

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
  return model.modality === "audio" ? "AUDIO" : "LLM";
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

  return `
    <article class="card ${model.status}">
      <div class="card-header-row">
        <div class="title-wrap">
          <span class="type-label ${type.toLowerCase()}">${type}</span>
          <h3>${model.display_name}</h3>
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
    setConfigMessage(err.message, true);
  }
});

async function init() {
  setupThemeSwitcher();
  await refreshModels();
  setInterval(() => {
    refreshModels().catch(() => {});
  }, 2000);
}

init().catch((err) => {
  setConfigMessage(err.message, true);
});
