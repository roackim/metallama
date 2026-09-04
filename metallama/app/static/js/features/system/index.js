import { api } from "../../core/api.js";

const vramStatusEl = document.getElementById("vram-status");
const vramNameEl = document.getElementById("vram-name");
const vramGraphEl = document.getElementById("vram-graph");
const gpuUsageGraphEl = document.getElementById("gpu-usage-graph");
const gpuUsageNameEl = document.getElementById("gpu-usage-name");
const vramGpusEl = document.getElementById("vram-gpus");
const vramGpusToggleEl = document.getElementById("vram-gpus-toggle");
const ramStatusEl = document.getElementById("ram-status");
const ramGraphEl = document.getElementById("ram-graph");
const cpuStatusEl = document.getElementById("cpu-status");
const cpuGraphEl = document.getElementById("cpu-graph");
const GRAPH_FILL_OPACITY = 0.25;

// Per-GPU graph state: gpuId -> { canvas, usageCanvas }
const gpuGraphs = new Map();
// GPU palette (cycled per GPU index)
const GPU_COLORS = [
  { line: "#60a5fa", fill: `rgba(96, 165, 250, ${GRAPH_FILL_OPACITY})` },
  { line: "#34d399", fill: `rgba(52, 211, 153, ${GRAPH_FILL_OPACITY})` },
  { line: "#fbbf24", fill: `rgba(251, 191, 36, ${GRAPH_FILL_OPACITY})` },
  { line: "#f472b6", fill: `rgba(244, 114, 182, ${GRAPH_FILL_OPACITY})` },
  { line: "#a78bfa", fill: `rgba(167, 139, 250, ${GRAPH_FILL_OPACITY})` },
  { line: "#f87171", fill: `rgba(248, 113, 113, ${GRAPH_FILL_OPACITY})` },
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

function drawGraph(canvas, history, colors, axisLabel = "") {
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
  const plotHeight = height;
  ctx.clearRect(0, 0, width, height);

  const isDark = document.documentElement.dataset.theme === "dark";
  const gridColor = isDark ? "rgba(255, 255, 255, 0.1)" : "rgba(0, 0, 0, 0.1)";

  ctx.strokeStyle = gridColor;
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75, 1.0].forEach((pct) => {
    const y = plotHeight - pct * (plotHeight - 2 * padding) - padding;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  });

  const numSamples = history.length;
  const points = history.map((sample, index) => {
    // The visible history is a moving window: oldest sample at the left,
    // newest sample at the right, with no unused lead-in space.
    const x = numSamples > 1 ? (index / (numSamples - 1)) * width : width;
    const y = plotHeight - (sample.percent / 100) * (plotHeight - 2 * padding) - padding;
    return { x, y };
  });

  const drawSmoothPath = (startPath = true) => {
    if (startPath) ctx.moveTo(points[0].x, points[0].y);
    for (let index = 1; index < points.length; index += 1) {
      const current = points[index];
      const previous = points[index - 1];
      const midpointX = (previous.x + current.x) / 2;
      const midpointY = (previous.y + current.y) / 2;
      ctx.quadraticCurveTo(previous.x, previous.y, midpointX, midpointY);
    }
    const last = points[points.length - 1];
    const previous = points[points.length - 2];
    ctx.quadraticCurveTo(previous.x, previous.y, last.x, last.y);
  };

  ctx.fillStyle = colors.fill;
  ctx.beginPath();
  ctx.moveTo(points[0].x, plotHeight);
  ctx.lineTo(points[0].x, points[0].y);
  drawSmoothPath(false);
  ctx.lineTo(points[points.length - 1].x, plotHeight);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = colors.line;
  ctx.lineWidth = 2;
  ctx.beginPath();
  drawSmoothPath();
  ctx.stroke();

  // Render the moving time axis outside the bordered canvas.
  const timePoints = [
    { sample: history[0], position: "start" },
    { sample: history[Math.floor((numSamples - 1) / 2)], position: "middle" },
    { sample: history[numSamples - 1], position: "end" },
  ];
  const timeAxis = canvas.parentElement?.querySelector(".system-time-axis");
  if (timeAxis) timeAxis.innerHTML = timePoints.map(({ sample, position }) => {
    const date = new Date(sample.timestamp);
    const label = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
    return `<span class="system-time-${position}">${label}</span>`;
  }).join("");
  if (axisLabel) {
    ctx.textBaseline = "top";
    ctx.fillText(axisLabel, width - 4, 3);
  }
}

function drawVramGraph(history) {
  const isDark = document.documentElement.dataset.theme === "dark";
  const colors = {
    line: isDark ? "#60a5fa" : "#2563eb",
    fill: isDark ? `rgba(96, 165, 250, ${GRAPH_FILL_OPACITY})` : `rgba(37, 99, 235, ${GRAPH_FILL_OPACITY})`,
  };
  drawGraph(vramGraphEl, history, colors);
}

function drawRamGraph(history) {
  const isDark = document.documentElement.dataset.theme === "dark";
  const colors = {
    line: isDark ? "#f59e0b" : "#d97706",
    fill: isDark ? `rgba(245, 158, 11, ${GRAPH_FILL_OPACITY})` : `rgba(217, 119, 6, ${GRAPH_FILL_OPACITY})`,
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
          <div class="system-graph-wrap">
            <div class="system-metric-name">VRAM usage</div>
            <canvas class="system-graph vram-gpu-graph" width="400" height="60"></canvas>
            <div class="system-time-axis" aria-hidden="true"></div>
          </div>
          <div class="system-graph-wrap">
            <div class="system-metric-name">GPU usage</div>
            <canvas class="system-graph gpu-usage-graph" width="400" height="60"></canvas>
            <div class="system-time-axis" aria-hidden="true"></div>
          </div>
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
    const usageCanvas = row.querySelector(".gpu-usage-graph");
    gpuGraphs.set(id, { canvas, usageCanvas });
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
    const isMultiGpu = tracked.length > 1;
    if (vramNameEl) vramNameEl.textContent = isMultiGpu ? "TOTAL VRAM" : "VRAM";
    if (gpuUsageNameEl) gpuUsageNameEl.textContent = isMultiGpu ? "TOTAL GPU USAGE" : "GPU USAGE";
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

export async function refreshCpu() {
  if (!cpuStatusEl) return;
  try {
    const data = await api("/api/system/cpu");
    cpuStatusEl.textContent = data.available ? `${data.percent.toFixed(0)}%` : "N/A";
  } catch {
    cpuStatusEl.textContent = "--";
  }
}

export async function refreshVramGraph() {
  try {
    const data = await api("/api/system/vram/history");
    if (data.history && data.history.length > 0) {
      drawVramGraph(data.history);
    }
    if (data.gpu_usage_history && data.gpu_usage_history.length > 0) {
      const isDark = document.documentElement.dataset.theme === "dark";
      drawGraph(gpuUsageGraphEl, data.gpu_usage_history, {
        line: isDark ? "#34d399" : "#059669",
        fill: isDark ? `rgba(52, 211, 153, ${GRAPH_FILL_OPACITY})` : `rgba(5, 150, 105, ${GRAPH_FILL_OPACITY})`,
      });
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
      const usageHist = (data.gpu_usage || {})[id] || [];
      if (entry.usageCanvas && usageHist.length > 0) {
        const idx = ids.indexOf(id);
        const colors = GPU_COLORS[idx % GPU_COLORS.length];
        drawGraph(entry.usageCanvas, usageHist, colors);
      }
    }
  } catch {
    // Ignore graph refresh failures.
  }
}

export async function refreshCpuGraph() {
  try {
    const data = await api("/api/system/cpu/history");
    if (data.history && data.history.length > 0) {
      const isDark = document.documentElement.dataset.theme === "dark";
      drawGraph(cpuGraphEl, data.history, {
        line: isDark ? "#a78bfa" : "#7c3aed",
        fill: isDark ? `rgba(167, 139, 250, ${GRAPH_FILL_OPACITY})` : `rgba(124, 58, 237, ${GRAPH_FILL_OPACITY})`,
      });
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
    const open = !isGpusSectionOpen();
    setGpusSectionOpen(open);
    if (open) {
      requestAnimationFrame(() => refreshVramGraph());
    }
  });
  setGpusSectionOpen(isGpusSectionOpen());
}
