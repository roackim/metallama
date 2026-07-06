import { api } from "../../core/api.js";
import { copyToClipboard } from "../../core/clipboard.js";
import { setConfigMessage } from "../../core/uiMessage.js";

function base() {
  return window.location.origin;
}

function fillSnippets(model) {
  const m = model || "<model>";
  document.getElementById("connect-ollama-url").textContent = `${base()}/ollama`;
  document.getElementById("connect-env").textContent =
    `export OPENAI_BASE_URL="${base()}/ollama/v1"\n` +
    `export OPENAI_API_KEY="metallama"\n` +
    `export OPENAI_MODEL="${m}"`;
  document.getElementById("connect-openai").textContent =
    `Base URL: ${base()}/ollama/v1\n` +
    `API key:  any non-empty string\n` +
    `Model:    ${m}`;
  document.getElementById("connect-curl").textContent =
    `curl ${base()}/ollama/v1/chat/completions \\\n` +
    `  -H 'Content-Type: application/json' \\\n` +
    `  -d '{"model": "${m}", "messages": [{"role": "user", "content": "Hello"}]}'`;
}

async function openConnectModal() {
  const select = document.getElementById("connect-model");
  select.innerHTML = "";
  try {
    const data = await api("/api/models");
    const models = data.models || [];
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.status === "online" ? `${m.id} (online)` : m.id;
      select.appendChild(opt);
    }
    const online = models.find((m) => m.status === "online");
    if (online) select.value = online.id;
  } catch {
    // no models — snippets fall back to a placeholder
  }
  fillSnippets(select.value);
  document.getElementById("connect-modal").classList.remove("is-hidden");
}

export function setupConnect() {
  const modal = document.getElementById("connect-modal");
  const btn = document.getElementById("connect-btn");
  if (!modal || !btn) return;

  btn.addEventListener("click", () => {
    openConnectModal().catch(() => {});
  });

  document.getElementById("connect-model")?.addEventListener("change", (e) => {
    fillSnippets(e.target.value);
  });

  modal.addEventListener("click", async (event) => {
    const target = event.target;
    if (event.target === modal) {
      modal.classList.add("is-hidden");
      return;
    }
    if (!(target instanceof HTMLButtonElement)) return;
    if (target.dataset.action === "connect-close") {
      modal.classList.add("is-hidden");
    } else if (target.dataset.copy) {
      const el = document.getElementById(target.dataset.copy);
      if (el) {
        await copyToClipboard(el.textContent);
        setConfigMessage("Copied to clipboard");
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("is-hidden")) {
      modal.classList.add("is-hidden");
    }
  });
}
