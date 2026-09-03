from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

# Detected once at import; each entry is (used_mb, total_mb) per GPU.
_tool: str | None = None
_tool_detected = False

_MEM_CACHE_TTL = 5.0
_mem_cache: tuple[float, list[dict[str, float]] | None] = (0.0, None)

# Common install locations for nvidia-smi (not always on PATH under systemd/containers)
_NVIDIA_SMI_CANDIDATES = (
    "/usr/bin/nvidia-smi",
    "/usr/local/bin/nvidia-smi",
    "/usr/lib/nvidia/bin/nvidia-smi",
)

# Common install locations for the AMD/ROCm tools (hidden when a systemd service
# overrides PATH to only include the venv).
_ROCM_SMI_CANDIDATES = (
    "/usr/bin/rocm-smi",
    "/opt/rocm/bin/rocm-smi",
    "/usr/bin/rocm-smi",
    "/opt/rocm/rocm-smi/bin/rocm-smi",
)
_AMD_SMI_CANDIDATES = (
    "/usr/bin/amd-smi",
    "/opt/amdgpu/bin/amd-smi",
    "/usr/bin/amd-smi",
)


def _resolve_tool_path(name: str) -> str | None:
    """Resolve a tool name to a runnable path (bare name on PATH, or a
    known absolute candidate). Returns None if unavailable."""
    if shutil.which(name):
        return name
    candidates = {
        "nvidia-smi": _NVIDIA_SMI_CANDIDATES,
        "rocm-smi": _ROCM_SMI_CANDIDATES,
        "amd-smi": _AMD_SMI_CANDIDATES,
    }
    for path in candidates.get(name, ()):
        if os.path.exists(path):
            return path
    return None


def detect_tool() -> str | None:
    """Return the first available GPU memory tool, or None."""
    global _tool, _tool_detected
    if not _tool_detected:
        # First: find the tool on PATH.
        _tool = next(
            (t for t in ("nvidia-smi", "rocm-smi", "amd-smi") if shutil.which(t)),
            None,
        )
        # Fallback: check known absolute install locations if the tool isn't on
        # PATH (common under systemd services or containers with minimal PATH).
        if _tool is None:
            found = _resolve_tool_path("nvidia-smi") or \
                _resolve_tool_path("rocm-smi") or \
                _resolve_tool_path("amd-smi")
            _tool = found
        _tool_detected = True
        logger.info("GPU tool detected: %s", _tool or "none")
    return _tool


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def _query_nvidia(tool: str = "nvidia-smi") -> list[dict[str, float]]:
    out = _run([
        tool,
        "--query-gpu=index,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) >= 3:
            try:
                idx = parts[0].strip()
                # .split()[0] strips units if nounits is ignored by older drivers
                used_mb = float(parts[1].strip().split()[0])
                total_mb = float(parts[2].strip().split()[0])
            except (ValueError, IndexError) as exc:
                logger.warning("nvidia-smi: failed to parse line %r: %s", line, exc)
                continue
            gpus.append({"id": f"gpu{idx}", "used_mb": used_mb, "total_mb": total_mb})
    if not gpus:
        logger.warning("nvidia-smi: no GPUs parsed from output:\n%s", out[:500])
    return gpus


def _query_rocm(tool: str = "rocm-smi") -> list[dict[str, float]]:
    out = _run([tool, "--showmeminfo", "vram", "--json"])
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
            "id": card,  # e.g. "card0", "card1"
            "used_mb": float(used) / (1024**2),
            "total_mb": float(total) / (1024**2),
        })
    return gpus


def _query_amd(tool: str = "amd-smi") -> list[dict[str, float]]:
    """Query amd-smi. Handles both output formats across amd-smi versions:

    - Newer versions wrap entries in a top-level "gpu_data" list:
      {"gpu_data": [{"gpu": 0, "mem_usage": {...}}, ...]}
    - Older versions return a bare list:
      [{"gpu": 0, "mem_usage": {...}}, ...]
    """
    out = _run([tool, "metric", "--mem-usage", "--json"])
    data = json.loads(out)
    if isinstance(data, dict):
        entries = data.get("gpu_data") or []
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    gpus = []
    for entry in entries:
        usage = entry.get("mem_usage", {}) if isinstance(entry, dict) else {}
        total = usage.get("total_vram", {}).get("value")
        used = usage.get("used_vram", {}).get("value")
        if total is None or used is None:
            continue
        gpu_id = entry.get("gpu")
        if gpu_id is None:
            gpu_id = len(gpus)
        # amd-smi reports MB
        gpus.append({"id": f"gpu{gpu_id}", "used_mb": float(used), "total_mb": float(total)})
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
        if tool == "nvidia-smi" or (tool and tool.endswith("nvidia-smi")):
            gpus = _query_nvidia(tool)
        elif tool == "rocm-smi" or (tool and tool.endswith("rocm-smi")):
            gpus = _query_rocm(tool)
        elif tool == "amd-smi" or (tool and tool.endswith("amd-smi")):
            gpus = _query_amd(tool)
        else:
            gpus = None
    except Exception as exc:
        logger.error("GPU memory query failed (tool=%s): %s", tool, exc, exc_info=True)
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
        # The detected tool failed (or parsed nothing). Try the other installed
        # tools before giving up — e.g. rocm-smi can fail under restricted
        # service environments where amd-smi still works, and vice versa.
        for alt in ("nvidia-smi", "rocm-smi", "amd-smi"):
            if alt == os.path.basename(tool):
                continue
            alt_path = _resolve_tool_path(alt)
            if alt_path is None:
                continue
            try:
                if alt == "nvidia-smi":
                    gpus_raw = _query_nvidia(alt_path)
                elif alt == "rocm-smi":
                    gpus_raw = _query_rocm(alt_path)
                else:
                    gpus_raw = _query_amd(alt_path)
                if gpus_raw:
                    logger.info("Primary GPU tool %s failed; fallback %s succeeded", tool, alt)
                    tool = alt_path
                    break
            except Exception:
                continue
    if not gpus_raw:
        return {"error": f"{tool} failed (check server logs)", "available": False}
    gpus = []
    for g in gpus_raw:
        used_mb, total_mb = g["used_mb"], g["total_mb"]
        gpus.append({
            "id": g.get("id", f"gpu{len(gpus)}"),
            "used_gb": round(used_mb / 1024, 2),
            "total_gb": round(total_mb / 1024, 2),
            "used_mb": int(used_mb),
            "total_mb": int(total_mb),
            "percent": round((used_mb / total_mb * 100) if total_mb > 0 else 0, 1),
        })
    return {"available": True, "gpus": gpus, "tool": tool}
