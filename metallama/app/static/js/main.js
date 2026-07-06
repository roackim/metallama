import { api } from "./core/api.js";
import { setConfigMessage } from "./core/uiMessage.js";
import { checkAuthEnabled, isAdmin, login, logout, onAdminChange, verifyToken } from "./core/auth.js";
import { setupModels, refreshModels } from "./features/models/index.js";
import { setupHfSearch } from "./features/hf/index.js";
import { setupLibrary } from "./features/library/index.js";
import { setupConnect } from "./features/connect/index.js";
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
  setupLibrary();
  setupConnect();

  // Auth: check if enabled, wire up admin toggle
  const authEnabled = await checkAuthEnabled();
  await verifyToken();
  const toggleBtn = document.getElementById("admin-toggle");
  const toggleLabel = document.getElementById("admin-toggle-label");
  // No password configured — everyone is admin, the button is noise
  if (!authEnabled) toggleBtn?.classList.add("is-hidden");

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
        openLoginModal();
      }
    });
  }

  // ── Login modal wiring ────────────────────────────────
  const loginModal = document.getElementById("login-modal");
  const loginPw = document.getElementById("login-password");
  const loginErr = document.getElementById("login-error");

  function openLoginModal() {
    loginErr.classList.add("is-hidden");
    loginErr.textContent = "";
    if (loginPw) { loginPw.value = ""; }
    loginModal?.classList.remove("is-hidden");
    setTimeout(() => loginPw?.focus(), 50);
  }

  function closeLoginModal() {
    loginModal?.classList.add("is-hidden");
    if (loginPw) loginPw.value = "";
  }

  async function submitLogin() {
    const pw = loginPw?.value || "";
    if (!pw) return;
    try {
      await login(pw);
      closeLoginModal();
    } catch (err) {
      loginErr.textContent = err.message || "Login failed";
      loginErr.classList.remove("is-hidden");
    }
  }

  if (loginModal) {
    loginModal.addEventListener("click", async (e) => {
      if (!(e.target instanceof HTMLButtonElement)) {
        // Click on overlay closes
        if (e.target === loginModal) closeLoginModal();
        return;
      }
      const action = e.target.dataset.action;
      if (action === "login-close" || action === "login-cancel") closeLoginModal();
      else if (action === "login-submit") await submitLogin();
    });
  }

  if (loginPw) {
    loginPw.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") { e.preventDefault(); await submitLogin(); }
      if (e.key === "Escape") closeLoginModal();
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
    verifyToken().catch(() => {});
  }, 5000);

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
