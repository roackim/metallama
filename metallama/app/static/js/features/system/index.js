import { api } from "../../core/api.js";

const vramStatusEl = document.getElementById("vram-status");
const vramGraphEl = document.getElementById("vram-graph");
const vramGpusEl = document.getElementById("vram-gpus");
const vramGpusToggleEl = document.getElementById("vram-gpus-toggle");
const ramStatusEl = document.getElementById("ram-status");
const ramGraphEl = document.getElementById("ram-graph");

// Per-GPU graph state: gpuId -> { canvas, history }
const gpuGraphs = new Map();
// GPU palette (cycled per GPU index)
const GPU_COLORS = [
  { line: "#60a5fa", fill: "rgba(96, 165, 250, 0.12)" },
  { line: "#34d399", fill: "rgba(52, 211, 153, 0.12)" },
  { line: "#fbbf24", fill: "rgba(251, 191, 36, 0.12)" },
  { line: "#f472b6", fill: "rgba(244, 114, 182, 0.12)" },
  { line: "#a78bfa", fill: "rgba(167, 139, 250, 0.12)" },
  { line: "#f87171", fill: "rgba(248, 113, 113, 0.12)" },
];

// Collapsible "Individual GPUs" section. Persisted in localStorage.
const GPUS_SECTION_KEY = "metallama.gpusSectionOpen";
function isGpusSectionOpen() {
  return localStorage.getItem(GPUS_SECTION_KEY) !== "0";
}
function setGpusSectionOpen(open) {
  localStorage.setItem(GPUS_SECTION_KEY, open ? "1" : "0");
  if (vramGpusToggleEl) {
    vramGpusToggleEl.setAttribute("aria-expanded", open ? "true" : "false");
    const caret = vramGpusToggleEl.querySelector(".vram-gpus-toggle-caret");
    if (caret) caret.textContent = open ? "▾" : "▸";
  }
  if (vramGpusEl) vramGpusEl.classList.toggle("collapsed", !open);
}

function drawGraph(canvas, history, colors) {
  if (!canvas || !history || history.length < 2) {
    return;
  }

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cssW = Math.max(1, Math.floor(rect.width));
  const cssH = Math.max(1, Math.floor(rect.height));
  if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
  }

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const width = cssW;
  const height = cssH;
  const padding = 2;
  const maxSamples = 500;

  ctx.clearRect(0, 0, width, height);

  const isDark = document.documentElement.dataset.theme === "dark";
  const gridColor = isDark ? "rgba(255, 255, 255, 0.1)" : "rgba(0, 0, 0, 0.1)";

  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75, 1.0].forEach((pct) => {
    const y = height - pct * (height - 2 * padding) - padding;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  });

  const numSamples = history.length;
  const pixelsPerSample = width / maxSamples;

  const points = history.map((sample, index) => {
    const x = width - (numSamples - index) * pixelsPerSample;
    const y = height - (sample.percent / 100) * (height - 2 * padding) - padding;
    return { x, y };
  });

  ctx.fillStyle = colors.fill;
  ctx.beginPath();
  ctx.moveTo(points[0].x, height);
  points.forEach((point) => ctx.lineTo(point.x, point.y));
  ctx.lineTo(points[points.length - 1].x, height);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = colors.line;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  points.forEach((point) => ctx.lineTo(point.x, point.y));
  ctx.stroke();
}

function drawVramGraph(history) {
  const isDark = document.documentElement.dataset.theme === "dark";
  const colors = {
    line: isDark ? "#60a5fa" : "#2563eb",
    fill: isDark ? "rgba(96, 165, 250, 0.1)" : "rgba(37, 99, 235, 0.1)",
  };
  drawGraph(vramGraphEl, history, colors);
}

function drawRamGraph(history) {
  const isDark = document.documentElement.dataset.theme === "dark";
  const colors = {
    line: isDark ? "#f59e0b" : "#d97706",
    fill: isDark ? "rgba(245, 158, 11, 0.1)" : "rgba(217, 119, 6, 0.1)",
  };
  drawGraph(ramGraphEl, history, colors);
}

// Render the per-GPU toggle list + graphs. Called when the GPU set changes.
// Tracked GPUs come first (with their graph); untracked GPUs are moved to the
// bottom with their graph hidden.
function renderGpuList(gpus) {
  if (!vramGpusEl) return;
  const seen = new Set(gpus.map((g) => g.id));
  for (const [id, entry] of gpuGraphs) {
    if (!seen.has(id)) {
      entry.canvas.remove();
      gpuGraphs.delete(id);
    }
  }

  // Sort: tracked first (stable), untracked at the bottom.
  const sorted = [...gpus].sort((a, b) => Number(b.tracked) - Number(a.tracked));

  vramGpusEl.innerHTML = sorted
    .map((gpu, i) => {
      const colors = GPU_COLORS[i % GPU_COLORS.length];
      return `
        <div class="vram-gpu ${gpu.tracked ? "" : "untracked"}" data-gpu-id="${gpu.id}">
          <label class="vram-gpu-toggle" title="${gpu.tracked ? "Click to stop tracking this GPU" : "Click to track this GPU"}">
            <input type="checkbox" data-gpu-id="${gpu.id}" ${gpu.tracked ? "checked" : ""} />
            <span class="vram-gpu-name">${gpu.id}</span>
            <span class="vram-gpu-val">${gpu.used_gb.toFixed(1)} / ${gpu.total_gb.toFixed(1)} GB</span>
          </label>
          <canvas class="system-graph vram-gpu-graph" width="400" height="40"></canvas>
        </div>
      `;
    })
    .join("");

  vramGpusEl.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener("change", async () => {
      const id = cb.dataset.gpuId;
      try {
        await api("/api/system/vram/gpus/toggle", {
          method: "POST",
          body: JSON.stringify({ id }),
        });
        await refreshVram();
        await refreshVramGraph();
      } catch (err) {
        cb.checked = !cb.checked;
        console.error("toggle failed", err);
      }
    });
  });

  vramGpusEl.querySelectorAll(".vram-gpu").forEach((row) => {
    const id = row.dataset.gpuId;
    const canvas = row.querySelector(".vram-gpu-graph");
    gpuGraphs.set(id, { canvas, history: [] });
  });
}

export async function refreshVram() {
  if (!vramStatusEl) {
    return;
  }

  try {
    const data = await api("/api/system/vram");
    if (!data.available || !data.gpus || data.gpus.length === 0) {
      vramStatusEl.textContent = "N/A";
      if (vramGpusEl) vramGpusEl.innerHTML = "";
      return;
    }

    const tracked = data.gpus.filter((g) => g.tracked);
    const pool = tracked.length ? tracked : data.gpus;
    const totalUsed = pool.reduce((sum, gpu) => sum + gpu.used_gb, 0);
    const totalMax = pool.reduce((sum, gpu) => sum + gpu.total_gb, 0);
    const avgPercent = totalMax > 0 ? (totalUsed / totalMax) * 100 : 0;

    vramStatusEl.textContent = `${totalUsed.toFixed(1)} / ${totalMax.toFixed(1)} GB · ${avgPercent.toFixed(0)}%`;

    const sig = data.gpus.map((g) => `${g.id}:${g.tracked}`).join("|");
    if (vramGpusEl && vramGpusEl.dataset.sig !== sig) {
      vramGpusEl.dataset.sig = sig;
      renderGpuList(data.gpus);
    } else if (vramGpusEl) {
      data.gpus.forEach((gpu) => {
        const row = vramGpusEl.querySelector(`.vram-gpu[data-gpu-id="${gpu.id}"]`);
        if (row) {
          const val = row.querySelector(".vram-gpu-val");
          if (val) val.textContent = `${gpu.used_gb.toFixed(1)} / ${gpu.total_gb.toFixed(1)} GB`;
        }
      });
    }
  } catch {
    vramStatusEl.textContent = "--";
  }
}

export async function refreshRam() {
  if (!ramStatusEl) {
    return;
  }

  try {
    const data = await api("/api/system/ram");
    if (!data.available) {
      ramStatusEl.textContent = "N/A";
      return;
    }

    ramStatusEl.textContent = `${data.used_gb.toFixed(1)} / ${data.total_gb.toFixed(1)} GB · ${data.percent.toFixed(0)}%`;
  } catch {
    ramStatusEl.textContent = "--";
  }
}

export async function refreshVramGraph() {
  try {
    const data = await api("/api/system/vram/history");
    if (data.history && data.history.length > 0) {
      drawVramGraph(data.history);
    }
    const gpuHist = data.gpus || {};
    const ids = [...gpuGraphs.keys()];
    for (const [id, entry] of gpuGraphs) {
      const hist = gpuHist[id] || [];
      if (hist.length > 0) {
        const idx = ids.indexOf(id);
        const colors = GPU_COLORS[idx % GPU_COLORS.length];
        drawGraph(entry.canvas, hist, colors);
      }
    }
  } catch {
    // Ignore graph refresh failures.
  }
}

export async function refreshRamGraph() {
  try {
    const data = await api("/api/system/ram/history");
    if (data.history && data.history.length > 0) {
      drawRamGraph(data.history);
    }
  } catch {
    // Ignore graph refresh failures.
  }
}

// Wire up the collapsible "Individual GPUs" section.
if (vramGpusToggleEl) {
  vramGpusToggleEl.addEventListener("click", () => {
    setGpusSectionOpen(!isGpusSectionOpen());
  });
  setGpusSectionOpen(isGpusSectionOpen());
}
