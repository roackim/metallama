import { api } from "../../core/api.js";
import { setConfigMessage } from "../../core/uiMessage.js";
import { openCreateForModel } from "../models/index.js";

const REFRESH_INTERVAL = 10000; // ms

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function formatGb(gb) {
  return gb >= 10 ? Math.round(gb) + " GB" : gb.toFixed(1) + " GB";
}

function modelItem(m) {
  const hasServer = (m.servers || []).length > 0;
  const dotTitle = hasServer
    ? `Served by: ${m.servers.join(", ")}`
    : "No server configured for this model";
  const metaBits = [m.params, m.arch, formatGb(m.size_gb)].filter(Boolean).join(" · ");
  return `
    <div class="library-item" title="${escapeHtml(m.rel_path)}">
      <span class="library-dot ${hasServer ? "served" : ""}" title="${escapeHtml(dotTitle)}"></span>
      <div class="library-item-body">
        <span class="library-item-name">${escapeHtml(m.name)}</span>
        <span class="library-item-meta">${escapeHtml(metaBits)}</span>
      </div>
      ${hasServer
        ? ""
        : `<button class="btn-secondary btn-small library-add admin-only" data-path="${escapeHtml(m.path)}" title="Create a server for this model">+ Serve</button>`}
    </div>`;
}

function partialItem(p) {
  const pct = p.percent != null ? `${Math.round(p.percent)}%` : "…";
  const width = p.percent != null ? Math.min(100, p.percent) : 0;
  const canResume = Boolean(p.repo_id && p.filename);
  return `
    <div class="library-item partial" title="${escapeHtml(p.rel_path)}">
      <div class="library-item-body">
        <span class="library-item-name">${escapeHtml(p.name)}</span>
        <div class="library-partial-track"><div class="library-partial-fill" style="width: ${width}%"></div></div>
        <span class="library-item-meta">${pct} downloaded${canResume ? "" : " · re-download the same file to resume"}</span>
      </div>
      <div class="library-partial-actions">
        ${canResume
          ? `<button class="btn-primary btn-small library-resume admin-only" data-repo="${escapeHtml(p.repo_id)}" data-file="${escapeHtml(p.filename)}" data-name="${escapeHtml(p.name)}" title="Continue this download">Resume</button>`
          : ""}
        <button class="btn-secondary btn-small library-discard admin-only" data-rel="${escapeHtml(p.rel_path)}" title="Delete the partial file${canResume ? "" : " (source unknown — re-download from search)"}">Discard</button>
      </div>
    </div>`;
}

export async function refreshLibrary() {
  const listEl = document.getElementById("library-list");
  const dlEl = document.getElementById("library-downloading");
  const emptyEl = document.getElementById("library-empty");
  const listTitle = document.getElementById("library-list-title");
  if (!listEl) return;

  let data;
  try {
    data = await api("/api/library");
  } catch {
    return; // transient — keep last render
  }
  const models = data.models || [];
  const partials = data.partials || [];

  listEl.innerHTML = models.map(modelItem).join("");
  listTitle?.classList.toggle("is-hidden", models.length === 0);
  emptyEl?.classList.toggle("is-hidden", models.length > 0 || partials.length > 0);

  if (partials.length) {
    dlEl.innerHTML =
      `<h3 class="side-subtitle">Interrupted downloads</h3>` + partials.map(partialItem).join("");
    dlEl.classList.remove("is-hidden");
  } else {
    dlEl.innerHTML = "";
    dlEl.classList.add("is-hidden");
  }
}

async function discardPartial(relPath, name) {
  if (!window.confirm(`Delete the partial download of "${name}"? The downloaded blocks will be lost.`)) {
    return;
  }
  try {
    await api("/api/library/partials/discard", {
      method: "POST",
      body: JSON.stringify({ rel_path: relPath }),
    });
    setConfigMessage(`Discarded partial download: ${name}`);
  } catch (err) {
    setConfigMessage(err.message, true);
  }
  await refreshLibrary();
}

export function setupLibrary() {
  const panel = document.getElementById("library-panel");
  if (!panel) return;

  // models/index.js can't import us (we import it), so expose a hook
  window.__metallamaRefreshLibrary = () => refreshLibrary().catch(() => {});

  panel.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;

    if (target.classList.contains("library-add")) {
      openCreateForModel(target.dataset.path || "");
    } else if (target.classList.contains("library-resume")) {
      window.__metallamaResumeDownload?.(
        target.dataset.repo,
        [target.dataset.file],
        target.dataset.name || target.dataset.file
      );
      setConfigMessage(`Resuming download: ${target.dataset.name}`);
    } else if (target.classList.contains("library-discard")) {
      const item = target.closest(".library-item");
      const name = item?.querySelector(".library-item-name")?.textContent || "this file";
      discardPartial(target.dataset.rel || "", name);
    }
  });

  refreshLibrary().catch(() => {});
  setInterval(() => refreshLibrary().catch(() => {}), REFRESH_INTERVAL);
}
