import { api } from "./core/api.js";
import { setConfigMessage } from "./core/uiMessage.js";
import { checkAuthEnabled, isAdmin, login, logout, onAdminChange } from "./core/auth.js";
import { setupModels, refreshModels } from "./features/models/index.js";
import { setupHfSearch } from "./features/hf/index.js";
import { refreshRam, refreshRamGraph, refreshVram, refreshVramGraph } from "./features/system/index.js";
import { setupThemeSwitcher } from "./features/theme/index.js";

function showBinaryWarning(binaries) {
  const el = document.getElementById("binary-warning");
  if (!el) return;

  const missing = Object.entries(binaries)
    .filter(([_, info]) => !info.found)
    .map(([engine, info]) => `${engine} (${info.reason})`);

  if (missing.length === 0) {
    el.classList.add("is-hidden");
    el.innerHTML = "";
    return;
  }

  const reason = missing.join("; ");
  el.innerHTML = `
    <span class="warning-icon">⚠️</span>
    <span class="warning-text">
      <strong>llama.cpp binary not found — servers cannot be started locally.</strong>
      ${reason}
      <br>Set <code>METALLAMA_LLAMACPP_BINARY</code> to the path of the llama-server binary.
    </span>
  `;
  el.classList.remove("is-hidden");
}

async function init() {
  setupThemeSwitcher(() => {
    refreshVramGraph().catch(() => {});
    refreshRamGraph().catch(() => {});
  });

  setupModels();
  setupHfSearch();

  // Auth: check if enabled, wire up admin toggle
  await checkAuthEnabled();
  const toggleBtn = document.getElementById("admin-toggle");
  const toggleLabel = document.getElementById("admin-toggle-label");

  function updateAdminUI(admin) {
    document.body.classList.toggle("is-admin", admin);
    document.body.classList.toggle("admin-locked", !admin);
    if (toggleLabel) toggleLabel.textContent = admin ? "Logout" : "Admin";
    if (toggleBtn) toggleBtn.classList.toggle("active", admin);
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", async () => {
      if (isAdmin()) {
        await logout();
      } else {
        const pw = prompt("Admin password:");
        if (pw !== null) {
          try {
            await login(pw);
          } catch (err) {
            setConfigMessage(err.message, true);
          }
        }
      }
    });
  }

  onAdminChange(updateAdminUI);
  updateAdminUI(isAdmin());

  // Check binary health on startup
  try {
    const health = await api("/api/health");
    showBinaryWarning(health.binaries || {});
  } catch {
    // Health endpoint not available, skip warning
  }

  await refreshModels();
  await refreshVram();
  await refreshRam();
  await refreshVramGraph();
  await refreshRamGraph();

  setInterval(() => {
    refreshModels().catch(() => {});
  }, 2000);

  setInterval(() => {
    refreshVram().catch(() => {});
    refreshRam().catch(() => {});
    refreshVramGraph().catch(() => {});
    refreshRamGraph().catch(() => {});
  }, 1000);
}

init().catch((err) => {
  setConfigMessage(err.message || "Initialization failed", true);
});
