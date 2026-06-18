import { api } from "../../core/api.js";
import { setConfigMessage } from "../../core/uiMessage.js";

const PANEL_ID = "hf-panel";
const SEARCH_ID = "hf-search";
const RESULTS_ID = "hf-results";

let searchTimeout = null;
let activeDownloads = new Map(); // filename → { total, completed }
let currentRepoFiles = null;

// ── Public API ─────────────────────────────────────────────

export function setupHfSearch() {
  const input = document.getElementById(SEARCH_ID);
  if (!input) return;

  input.addEventListener("input", () => {
    clearTimeout(searchTimeout);
    const q = input.value.trim();
    if (!q) {
      hideResults();
      return;
    }
    searchTimeout = setTimeout(() => doSearch(q), 400);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      input.value = "";
      hideResults();
    }
  });

  // Close on click outside
  document.addEventListener("click", (e) => {
    const panel = document.getElementById(PANEL_ID);
    if (panel && !panel.contains(e.target)) {
      const inp = document.getElementById(SEARCH_ID);
      if (inp) inp.value = "";
      hideResults();
    }
  });
}

// ── Search ─────────────────────────────────────────────────

async function doSearch(query) {
  const container = document.getElementById(RESULTS_ID);
  container.innerHTML = `<div class="hf-loading">Searching…</div>`;
  showResults();

  try {
    const data = await api(`/api/hf/search?q=${encodeURIComponent(query)}`);
    const results = data.results || [];
    if (!results.length) {
      container.innerHTML = `<div class="hf-empty">No GGUF models found for "${query}"</div>`;
      return;
    }
    container.innerHTML = results.map(renderSearchResult).join("");
    bindResultClicks(container);
  } catch (err) {
    container.innerHTML = `<div class="hf-error">Search failed: ${err.message}</div>`;
  }
}

function renderSearchResult(item) {
  const downloads = formatNumber(item.downloads);
  const likes = formatNumber(item.likes);
  return `
    <div class="hf-result" data-repo-id="${escapeHtml(item.id)}">
      <div class="hf-result-header">
        <span class="hf-result-name">${escapeHtml(item.id)}</span>
        <span class="hf-result-meta">
          <span class="hf-result-stat hf-stat-downloads">↓ ${downloads}</span>
          <span class="hf-result-stat hf-stat-likes">♥ ${likes}</span>
        </span>
      </div>
      <div class="hf-result-files is-hidden"></div>
    </div>
  `;
}

function bindResultClicks(container) {
  container.querySelectorAll(".hf-result-header").forEach((el) => {
    el.addEventListener("click", () => {
      const result = el.closest(".hf-result");
      const repoId = result.dataset.repoId;
      const filesContainer = result.querySelector(".hf-result-files");

      // Toggle
      if (!filesContainer.classList.contains("is-hidden")) {
        filesContainer.classList.add("is-hidden");
        return;
      }
      filesContainer.classList.remove("is-hidden");
      loadFiles(repoId, filesContainer);
    });
  });
}

// ── Files ──────────────────────────────────────────────────

async function loadFiles(repoId, container) {
  container.innerHTML = `<div class="hf-loading">Loading files…</div>`;
  const [ns, repo] = repoId.split("/");
  try {
    const data = await api(`/api/hf/models/${ns}/${repo}/files`);
    const files = data.files || [];
    if (!files.length) {
      container.innerHTML = `<div class="hf-empty">No .gguf files in this repo</div>`;
      return;
    }
    currentRepoFiles = files;
    container.innerHTML = files.map((f) => renderFile(f, repoId)).join("");
    bindDownloadClicks(container, repoId);
  } catch (err) {
    container.innerHTML = `<div class="hf-error">Failed to load files: ${err.message}</div>`;
  }
}

function renderFile(file, repoId) {
  const isSharded = file.type === "sharded";
  const quant = file.quant || "?";
  const name = isSharded
    ? `${file.base_name} (${file.shard_count} shards)`
    : file.filename;
  const size = file.size_human;
  const downloadId = `${repoId}/${isSharded ? file.base_name : file.filename}`;

  const filenames = isSharded
    ? file.shards.map((s) => s.path)
    : [file.path];

  const quantClass = quantColor(quant);

  return `
    <div class="hf-file" data-download-id="${escapeHtml(downloadId)}" data-filenames='${JSON.stringify(filenames)}'>
      <div class="hf-file-info">
        <span class="hf-file-name">${escapeHtml(name)}</span>
        <span class="hf-quant-badge ${quantClass}">${escapeHtml(quant)}</span>
        <span class="hf-file-size">${size}</span>
      </div>
      <div class="hf-file-actions">
        <button class="btn-primary btn-small hf-download-btn admin-only" data-repo-id="${escapeHtml(repoId)}">↓ Download</button>
      </div>
    </div>
  `;
}

function bindDownloadClicks(container, repoId) {
  container.querySelectorAll(".hf-download-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const fileEl = btn.closest(".hf-file");
      const filenames = JSON.parse(fileEl.dataset.filenames);
      const label = fileEl.querySelector(".hf-file-name")?.textContent || repoId;
      btn.disabled = true;
      btn.textContent = "Downloading…";
      await startDownload(repoId, filenames, btn, label);
    });
  });
}

// ── Download ───────────────────────────────────────────────

function getOrCreateDownloadBar(downloadId) {
  const downloads = document.getElementById("hf-downloads");
  downloads.classList.remove("is-hidden");

  // Reuse existing bar for same download
  let bar = downloads.querySelector(`[data-dl-id="${CSS.escape(downloadId)}"]`);
  if (bar) return bar;

  bar = document.createElement("div");
  bar.className = "hf-dl-bar";
  bar.dataset.dlId = downloadId;
  bar.innerHTML = `
    <span class="hf-dl-label"></span>
    <div class="hf-dl-track">
      <div class="hf-dl-fill" style="width: 0%"></div>
    </div>
    <span class="hf-dl-text">0%</span>
  `;
  downloads.appendChild(bar);
  return bar;
}

async function startDownload(repoId, filenames, btn, label) {
  const downloadId = `${repoId}/${filenames[0].split("/").pop()}`;
  const bar = getOrCreateDownloadBar(downloadId);
  const dlLabel = bar.querySelector(".hf-dl-label");
  const dlFill = bar.querySelector(".hf-dl-fill");
  const dlText = bar.querySelector(".hf-dl-text");

  dlLabel.textContent = label;
  dlFill.style.width = "0%";
  dlFill.className = "hf-dl-fill";
  dlText.textContent = "0%";

  // Track per-file progress
  const fileProgress = {};
  filenames.forEach((f) => (fileProgress[f] = { total: 0, completed: 0 }));

  try {
    const resp = await fetch("/api/hf/download", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...((sessionStorage.getItem("metallama_admin_token") && { "Authorization": `Bearer ${sessionStorage.getItem("metallama_admin_token")}` }) || {}),
      },
      body: JSON.stringify({ repo_id: repoId, filenames }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "Download failed" }));
      throw new Error(err.detail || "Download failed");
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        const msg = JSON.parse(line);
        const fname = msg.filename || filenames[0];

        if (msg.status === "downloading") {
          fileProgress[fname] = { total: msg.total, completed: msg.completed };
        } else if (msg.status === "done") {
          fileProgress[fname] = { total: msg.size, completed: msg.size };
        } else if (msg.status === "error") {
          throw new Error(msg.error || "Download error");
        }

        let totalCompleted = 0;
        let totalSize = 0;
        for (const f of filenames) {
          totalCompleted += fileProgress[f].completed;
          totalSize += fileProgress[f].total;
        }
        const pct = totalSize > 0 ? Math.round((totalCompleted / totalSize) * 100) : 0;
        dlFill.style.width = `${pct}%`;
        dlText.textContent = `${pct}% — ${formatBytes(totalCompleted)} / ${formatBytes(totalSize)}`;
      }
    }

    dlFill.style.width = "100%";
    dlFill.classList.add("done");
    dlText.textContent = "✓ Done";
    btn.textContent = "Done";
    btn.classList.remove("btn-secondary");
    btn.classList.add("btn-primary");
    setConfigMessage(`Downloaded: ${filenames.length === 1 ? filenames[0].split("/").pop() : filenames.length + " files"}`);

    // Fade out the download bar after 5s
    setTimeout(() => {
      bar.classList.add("fade-out");
      setTimeout(() => {
        bar.remove();
        const downloads = document.getElementById("hf-downloads");
        if (!downloads.children.length) {
          downloads.classList.add("is-hidden");
        }
      }, 600);
    }, 5000);

    invalidateModelFilesCache();
  } catch (err) {
    dlFill.classList.add("error");
    dlText.textContent = `Error: ${err.message}`;
    btn.textContent = "Retry";
    btn.disabled = false;
    setConfigMessage(err.message, true);
  }
}

// ── Helpers ────────────────────────────────────────────────

function showResults() {
  document.getElementById(RESULTS_ID)?.classList.remove("is-hidden");
}

function hideResults() {
  document.getElementById(RESULTS_ID)?.classList.add("is-hidden");
}

function invalidateModelFilesCache() {
  // Access the cache from models module — we do this via a global function
  if (typeof window.__metallamaInvalidateModelCache === "function") {
    window.__metallamaInvalidateModelCache();
  }
}

function formatNumber(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function formatBytes(n) {
  if (n >= 1 << 30) return (n / (1 << 30)).toFixed(1) + " GB";
  if (n >= 1 << 20) return (n / (1 << 20)).toFixed(1) + " MB";
  if (n >= 1 << 10) return (n / (1 << 10)).toFixed(1) + " KB";
  return n + " B";
}

function quantColor(quant) {
  const q = quant.toUpperCase();
  if (q.startsWith("Q2") || q.startsWith("Q3")) return "hf-quant-low";
  if (q.startsWith("Q4")) return "hf-quant-mid";
  if (q.startsWith("Q5") || q.startsWith("Q6")) return "hf-quant-high";
  if (q.startsWith("Q8")) return "hf-quant-max";
  if (q.startsWith("F16") || q.startsWith("BF16") || q.startsWith("F32")) return "hf-quant-fp";
  if (q.startsWith("IQ")) return "hf-quant-iq";
  return "hf-quant-unknown";
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
