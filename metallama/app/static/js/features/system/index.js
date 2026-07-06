import { api } from "../../core/api.js";

const vramStatusEl = document.getElementById("vram-status");
const vramGraphEl = document.getElementById("vram-graph");
const ramStatusEl = document.getElementById("ram-status");
const ramGraphEl = document.getElementById("ram-graph");

function drawGraph(canvas, history, colors) {
  if (!canvas || !history || history.length < 2) {
    return;
  }

  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
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

export async function refreshVram() {
  if (!vramStatusEl) {
    return;
  }

  try {
    const data = await api("/api/system/vram");
    if (!data.available || !data.gpus || data.gpus.length === 0) {
      vramStatusEl.textContent = "N/A";
      return;
    }

    const totalUsed = data.gpus.reduce((sum, gpu) => sum + gpu.used_gb, 0);
    const totalMax = data.gpus.reduce((sum, gpu) => sum + gpu.total_gb, 0);
    const avgPercent = data.gpus.reduce((sum, gpu) => sum + gpu.percent, 0) / data.gpus.length;

    vramStatusEl.textContent = `${totalUsed.toFixed(1)} / ${totalMax.toFixed(1)} GB · ${avgPercent.toFixed(0)}%`;
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
