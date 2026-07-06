from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Any

# Detected once at import; each entry is (used_mb, total_mb) per GPU.
_tool: str | None = None
_tool_detected = False

_MEM_CACHE_TTL = 5.0
_mem_cache: tuple[float, list[dict[str, float]] | None] = (0.0, None)


def detect_tool() -> str | None:
    """Return the first available GPU memory tool, or None."""
    global _tool, _tool_detected
    if not _tool_detected:
        _tool = next(
            (t for t in ("nvidia-smi", "rocm-smi", "amd-smi") if shutil.which(t)),
            None,
        )
        _tool_detected = True
    return _tool


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def _query_nvidia() -> list[dict[str, float]]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    for line in out.strip().splitlines():
        parts = line.split(",")
        if len(parts) >= 2:
            gpus.append({"used_mb": float(parts[0]), "total_mb": float(parts[1])})
    return gpus


def _query_rocm() -> list[dict[str, float]]:
    out = _run(["rocm-smi", "--showmeminfo", "vram", "--json"])
    data = json.loads(out)
    gpus = []
    for card in sorted(data):
        entry = data[card]
        if not isinstance(entry, dict):
            continue
        total = entry.get("VRAM Total Memory (B)")
        used = entry.get("VRAM Total Used Memory (B)")
        if total is None or used is None:
            continue
        gpus.append({
            "used_mb": float(used) / (1024**2),
            "total_mb": float(total) / (1024**2),
        })
    return gpus


def _query_amd() -> list[dict[str, float]]:
    out = _run(["amd-smi", "metric", "--mem-usage", "--json"])
    data = json.loads(out)
    gpus = []
    for entry in data if isinstance(data, list) else []:
        usage = entry.get("mem_usage", {}) if isinstance(entry, dict) else {}
        total = usage.get("total_vram", {}).get("value")
        used = usage.get("used_vram", {}).get("value")
        if total is None or used is None:
            continue
        # amd-smi reports MB
        gpus.append({"used_mb": float(used), "total_mb": float(total)})
    return gpus


def get_gpu_memory() -> list[dict[str, float]] | None:
    """Return [{used_mb, total_mb}] per GPU, or None if no tool/GPU available.

    Cached for a few seconds — callers may poll every couple of seconds
    per server card and the underlying tools fork a process each call.
    """
    global _mem_cache
    ts, cached = _mem_cache
    if time.time() - ts < _MEM_CACHE_TTL:
        return cached

    tool = detect_tool()
    gpus: list[dict[str, float]] | None
    try:
        if tool == "nvidia-smi":
            gpus = _query_nvidia()
        elif tool == "rocm-smi":
            gpus = _query_rocm()
        elif tool == "amd-smi":
            gpus = _query_amd()
        else:
            gpus = None
    except Exception:
        gpus = None

    _mem_cache = (time.time(), gpus)
    return gpus


def get_free_vram_gb() -> float | None:
    """Total free VRAM across all GPUs, in GB."""
    gpus = get_gpu_memory()
    if not gpus:
        return None
    free_mb = sum(g["total_mb"] - g["used_mb"] for g in gpus)
    return round(free_mb / 1024, 2)


def vram_status() -> dict[str, Any]:
    """Payload for /api/system/vram, shaped like the original nvidia-only version."""
    tool = detect_tool()
    if tool is None:
        return {"error": "no GPU tool found (nvidia-smi / rocm-smi / amd-smi)", "available": False}
    gpus_raw = get_gpu_memory()
    if gpus_raw is None:
        return {"error": f"{tool} failed", "available": False}
    gpus = []
    for g in gpus_raw:
        used_mb, total_mb = g["used_mb"], g["total_mb"]
        gpus.append({
            "used_gb": round(used_mb / 1024, 2),
            "total_gb": round(total_mb / 1024, 2),
            "used_mb": int(used_mb),
            "total_mb": int(total_mb),
            "percent": round((used_mb / total_mb * 100) if total_mb > 0 else 0, 1),
        })
    return {"available": True, "gpus": gpus, "tool": tool}
