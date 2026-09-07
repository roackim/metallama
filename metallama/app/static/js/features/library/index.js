import { api } from "../../core/api.js";
import { setConfigMessage } from "../../core/uiMessage.js";
import { openCreateForModel } from "../models/index.js";

const REFRESH_INTERVAL = 10000; // ms

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function modelItem(m) {
  const hasServer = (m.servers || []).length > 0;
  const displayName = (m.rel_path || "").split("/").pop() || `${m.name}.gguf`;
  return `
    <div class="library-item" title="${escapeHtml(m.rel_path)}">
      <div class="library-item-body">
        <span class="library-item-name">${escapeHtml(displayName)}</span>
      </div>
      <div class="library-item-actions">
        ${hasServer
          ? `<span class="library-action-spacer"></span>`
          : `<button class="btn-secondary btn-small library-action app-control app-control-positive library-add admin-only" data-path="${escapeHtml(m.path)}" title="Create a server for this model">Serve</button>`}
        <button class="btn-secondary btn-small library-action app-control library-rename admin-only" data-rel="${escapeHtml(m.rel_path)}" data-name="${escapeHtml(displayName)}" title="Rename this model file">Rename</button>
        <button class="btn-danger btn-small library-action app-control app-control-danger library-delete admin-only" data-rel="${escapeHtml(m.rel_path)}" data-name="${escapeHtml(displayName)}" title="Permanently delete this model file">Delete</button>
      </div>
      <span class="library-item-date" title="Downloaded">${escapeHtml(m.downloaded_at || "")}</span>
    </div>`;
}

function partialItem(p) {
  const pct = p.percent != null ? `${Math.round(p.percent)}%` : "…";
  const width = p.percent != null ? Math.min(100, p.percent) : 0;
  const canResume = Boolean(p.repo_id && p.filename);
  return `
    <div class="library-item partial" data-download-id="${escapeHtml(`${p.repo_id || ""}/${p.filename || p.name}`)}" title="${escapeHtml(p.rel_path)}">
      <div class="library-item-body">
        <span class="library-item-name">${escapeHtml(p.name)}</span>
        <div class="library-partial-track"><div class="library-partial-fill" style="width: ${width}%"></div></div>
        <span class="library-item-meta">${pct} downloaded${canResume ? "" : " · re-download the same file to resume"}</span>
      </div>
      <div class="library-partial-actions">
        <button class="btn-secondary btn-small library-action app-control library-pause is-hidden" data-download-id="${escapeHtml(`${p.repo_id || ""}/${p.filename || p.name}`)}" title="Pause download">Pause</button>
        ${canResume
          ? `<button class="btn-primary btn-small library-action app-control app-control-positive library-resume admin-only" data-repo="${escapeHtml(p.repo_id)}" data-file="${escapeHtml(p.filename)}" data-name="${escapeHtml(p.name)}" title="Continue this download">Resume</button>`
          : ""}
        <button class="btn-secondary btn-small library-action app-control library-rename admin-only" data-rel="${escapeHtml(p.rel_path)}" data-name="${escapeHtml(p.name)}" title="Rename this partial download">Rename</button>
        <button class="btn-secondary btn-small library-action app-control app-control-danger library-discard admin-only" data-rel="${escapeHtml(p.rel_path)}" title="Delete the partial file${canResume ? "" : " (source unknown — re-download from search)"}">Discard</button>
      </div>
      <span class="library-item-date" title="Downloaded">${escapeHtml(p.downloaded_at || "")}</span>
    </div>`;
}

export async function refreshLibrary() {
  const listEl = document.getElementById("library-list");
  const dlEl = document.getElementById("library-downloading");
  const emptyEl = document.getElementById("library-empty");
  if (!listEl) return;

  let data;
  try {
    data = await api("/api/library");
  } catch {
    return; // transient — keep last render
  }
  const models = data.models || [];
  const partials = data.partials || [];

  // Skip the DOM swap when nothing changed, to avoid needless churn that can
  // swallow a mid-click on a library button.
  const sig = JSON.stringify({ models, partials });
  if (sig === libraryLastSig && listEl.children.length) {
    return;
  }
  libraryLastSig = sig;

  // Defer the DOM swap while a press is in progress — a swap between
  // mousedown and mouseup suppresses the click event (double-click bug).
  if (libraryPressCount > 0) {
    libraryPendingHtml = { models, partials };
    return;
  }
  renderLibrary(models, partials);
}

let libraryPressCount = 0;
let libraryPendingHtml = null;
let libraryLastSig = null;

function renderLibrary(models, partials) {
  const listEl = document.getElementById("library-list");
  const dlEl = document.getElementById("library-downloading");
  const emptyEl = document.getElementById("library-empty");
  if (!listEl) return;

  listEl.innerHTML = models.map(modelItem).join("");
  emptyEl?.classList.toggle("is-hidden", models.length > 0 || partials.length > 0);

  if (partials.length) {
    dlEl.innerHTML = `<h3 class="side-subtitle">Downloads</h3>` + partials.map(partialItem).join("");
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

async function deleteModel(relPath, name) {
  if (!window.confirm(`Permanently delete "${name}"?\n\nThis cannot be undone.`)) {
    return;
  }
  try {
    await api("/api/library/models/delete", {
      method: "POST",
      body: JSON.stringify({ rel_path: relPath }),
    });
    setConfigMessage(`Deleted model: ${name}`);
    window.__metallamaInvalidateModelCache?.();
  } catch (err) {
    setConfigMessage(err.message, true);
  }
  await refreshLibrary();
}

async function renameItem(relPath, name, isPartial) {
  const current = name || relPath.split("/").pop() || "";
  const base = current.replace(/\.(gguf|partial)$/i, "");
  const newName = window.prompt(`Rename "${current}" to:`, base);
  if (newName === null) return; // cancelled
  const trimmed = newName.trim();
  if (!trimmed) {
    setConfigMessage("Rename cancelled — name is empty", true);
    return;
  }
  const endpoint = isPartial ? "/api/library/partials/rename" : "/api/library/models/rename";
  try {
    await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ rel_path: relPath, new_name: trimmed }),
    });
    setConfigMessage(`Renamed to: ${trimmed}`);
    window.__metallamaInvalidateModelCache?.();
  } catch (err) {
    setConfigMessage(err.message, true);
  }
  await refreshLibrary();
}

export function setupLibrary() {
  const panel = document.getElementById("library-panel");
  if (!panel) return;
  const toggle = document.getElementById("library-toggle");
  const content = document.getElementById("library-content");
  const storageKey = "metallama.librarySectionOpen";
  const setOpen = (open) => {
    localStorage.setItem(storageKey, open ? "1" : "0");
    toggle?.setAttribute("aria-expanded", open ? "true" : "false");
    const caret = toggle?.querySelector(".vram-gpus-toggle-caret");
    if (caret) caret.textContent = open ? "▾" : "▸";
    const label = toggle?.querySelector(".library-toggle-label");
    if (label) label.textContent = open ? "Hide" : "Show";
    toggle?.setAttribute("aria-label", `${open ? "Hide" : "Show"} model library`);
    toggle?.setAttribute("title", `${open ? "Hide" : "Show"} model library`);
    content?.classList.toggle("collapsed", !open);
  };
  toggle?.addEventListener("click", () => setOpen(localStorage.getItem(storageKey) !== "1"));
  setOpen(localStorage.getItem(storageKey) !== "0");

  // Press tracking so refreshLibrary() defers its DOM swap mid-click.
  panel.addEventListener("pointerdown", () => { libraryPressCount++; });
  document.addEventListener("pointerup", () => { libraryPressCount = Math.max(0, libraryPressCount - 1); });
  document.addEventListener("pointercancel", () => { libraryPressCount = Math.max(0, libraryPressCount - 1); });
  // Flush any render that was deferred while the user was pressing.
  document.addEventListener("pointerup", () => {
    if (libraryPressCount === 0 && libraryPendingHtml) {
      const { models, partials } = libraryPendingHtml;
      libraryPendingHtml = null;
      renderLibrary(models, partials);
    }
  });

  // models/index.js can't import us (we import it), so expose a hook
  window.__metallamaRefreshLibrary = () => refreshLibrary().catch(() => {});
  window.__metallamaUpdateDownloadProgress = (downloadId, percent, text) => {
    const item = panel.querySelector(`.library-item.partial[data-download-id="${CSS.escape(downloadId)}"]`);
    if (!item) return;
    const fill = item.querySelector(".library-partial-fill");
    const meta = item.querySelector(".library-item-meta");
    if (fill) fill.style.width = `${Math.min(100, percent)}%`;
    if (meta) meta.textContent = `${Math.round(percent)}% downloaded${text ? ` — ${text}` : ""}`;
  };
  window.__metallamaSetDownloadActive = (downloadId, active) => {
    const item = panel.querySelector(`.library-item.partial[data-download-id="${CSS.escape(downloadId)}"]`);
    const pause = item?.querySelector(".library-pause");
    if (pause) pause.classList.toggle("is-hidden", !active);
  };

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
    } else if (target.classList.contains("library-pause")) {
      window.__metallamaPauseDownload?.(target.dataset.downloadId);
    } else if (target.classList.contains("library-rename")) {
      const isPartial = target.closest(".library-item")?.classList.contains("partial") || false;
      renameItem(target.dataset.rel || "", target.dataset.name || "", isPartial);
    } else if (target.classList.contains("library-discard")) {
      const item = target.closest(".library-item");
      const name = item?.querySelector(".library-item-name")?.textContent || "this file";
      discardPartial(target.dataset.rel || "", name);
    } else if (target.classList.contains("library-delete")) {
      deleteModel(target.dataset.rel || "", target.dataset.name || "this model");
    }
  });

  refreshLibrary().catch(() => {});
  setInterval(() => refreshLibrary().catch(() => {}), REFRESH_INTERVAL);
}
