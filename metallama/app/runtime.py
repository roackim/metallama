from __future__ import annotations

import asyncio
import socket
import subprocess

import httpx
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .config import Config
from .gguf import estimate_vram_gb
from .gpu import get_free_vram_gb
from .logs import get_unexpected_exit, server_logs
from .models import ModelProfile, ProcessState
from .profiles import MODEL_PROFILES
from .unified_config import load_unified_config


runtime_processes: dict[str, ProcessState] = {}
model_locks: dict[str, asyncio.Lock] = {key: asyncio.Lock() for key in MODEL_PROFILES}


def _get_engine_default_args(engine: str) -> list[str]:
    """Get default CLI args for an engine from unified config."""
    config = load_unified_config()
    return config.engine_defaults.get(engine) or []


def get_profile_with_config(profile: ModelProfile) -> ModelProfile:
    """Get a profile with the latest params from unified config.yaml.

    Looks up the managed_server entry by id and applies any overrides
    for context_window, parallel, and model_draft that may have been updated in config.
    """
    unified = load_unified_config()
    server_entry = next((s for s in unified.managed_servers if s.name == profile.name), None)
    if not server_entry:
        return profile

    overrides: dict = {}
    if server_entry.context_window is not None and server_entry.context_window != profile.context_window:
        overrides["context_window"] = server_entry.context_window
    if server_entry.parallel != profile.parallel:
        overrides["parallel"] = server_entry.parallel
    if server_entry.model_draft != profile.model_draft:
        overrides["model_draft"] = server_entry.model_draft

    return replace(profile, **overrides) if overrides else profile



def is_alive(proc: subprocess.Popen[str]) -> bool:
    return proc.poll() is None


def cleanup_dead(model_name: str) -> None:
    state = runtime_processes.get(model_name)
    if state and not is_alive(state.process):
        # Reap zombie process by calling wait() (poll() alone may not fully reap)
        try:
            state.process.wait()
        except subprocess.SubprocessError:
            pass
        runtime_processes.pop(model_name, None)


def is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False




def _resolve_binary(profile: ModelProfile) -> str:
    binary = Config.EXECUTABLE_LLAMA

    if not binary:
        raise HTTPException(status_code=400, detail=f"{profile.engine} binary is empty")

    binary_path = Path(binary)
    if binary_path.is_absolute() and not binary_path.exists():
        raise HTTPException(status_code=400, detail=f"Binary does not exist: {binary}")

    return binary


def _binary_exists(path: str) -> bool:
    """Check if a binary path exists, catching PermissionError from inaccessible parent dirs."""
    try:
        return Path(path).exists()
    except (PermissionError, OSError):
        return False


def _resolve_binary_or_placeholder(profile: ModelProfile) -> tuple[str, bool]:
    """Resolve binary path, returning (path, found). Returns placeholder if not found."""
    binary = Config.EXECUTABLE_LLAMA

    if not binary:
        return (f"<{profile.engine}-binary>", False)

    binary_path = Path(binary)
    if binary_path.is_absolute() and not _binary_exists(binary):
        return (binary, False)

    return (binary, True)


def binary_health() -> dict:
    """Return binary availability status for all engines."""
    binary = Config.EXECUTABLE_LLAMA
    if not binary:
        return {"llama": {"found": False, "path": "", "reason": "METALLAMA_LLAMACPP_BINARY not set"}}

    if not _binary_exists(binary):
        return {"llama": {"found": False, "path": binary, "reason": f"Binary not found or not accessible at {binary}"}}

    return {"llama": {"found": True, "path": binary, "reason": ""}}


def build_command_preview(profile: ModelProfile) -> tuple[list[str], bool]:
    """Build command for preview/clipboard. Returns (command, binary_found)."""
    profile = get_profile_with_config(profile)
    binary, found = _resolve_binary_or_placeholder(profile)

    # Tokenize: split each arg on whitespace so "--flash-attn on" → ["--flash-attn", "on"]
    extra_args = [
        token
        for arg in _get_engine_default_args(profile.engine) + list(profile.extra_args)
        for token in arg.split()
    ]

    if profile.engine == "llama" and profile.context_window is not None:
        extra_args = _strip_flag(extra_args, "--ctx-size")
        total_ctx = profile.context_window * profile.parallel
        extra_args += ["--ctx-size", str(total_ctx)]

    if profile.engine == "llama" and profile.parallel is not None:
        extra_args = _strip_flag(extra_args, "--parallel")
        extra_args += ["--parallel", str(profile.parallel)]

    cmd = [binary, "--model", str(profile.model_path), "--host", Config.BIND_HOST, "--port", str(profile.port)]
    if profile.model_draft:
        cmd += ["--model-draft", str(profile.model_draft)]
    cmd += extra_args

    return (cmd, found)


def _strip_flag(args: list[str], flag: str) -> list[str]:
    result: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == flag:
            skip_next = True
            continue
        if arg.startswith(f"{flag}="):
            continue
        result.append(arg)
    return result


def build_command(profile: ModelProfile) -> list[str]:
    profile = get_profile_with_config(profile)
    binary = _resolve_binary(profile)

    # Tokenize: split each arg on whitespace so "--flash-attn on" → ["--flash-attn", "on"]
    extra_args = [
        token
        for arg in _get_engine_default_args(profile.engine) + list(profile.extra_args)
        for token in arg.split()
    ]

    if profile.engine == "llama" and profile.context_window is not None:
        extra_args = _strip_flag(extra_args, "--ctx-size")
        total_ctx = profile.context_window * profile.parallel
        extra_args += ["--ctx-size", str(total_ctx)]

    if profile.engine == "llama" and profile.parallel is not None:
        extra_args = _strip_flag(extra_args, "--parallel")
        extra_args += ["--parallel", str(profile.parallel)]


    model_path = Path(profile.model_path)
    if not model_path.exists():
        raise HTTPException(status_code=400, detail=f"Model file not found: {profile.model_path}")

    cmd = [binary, "--model", str(model_path), "--host", Config.BIND_HOST, "--port", str(profile.port)]
    if profile.model_draft:
        cmd += ["--model-draft", str(profile.model_draft)]
    cmd += extra_args

    return cmd


async def _health_check(port: int) -> bool:
    """Async health check for a llama-server port (non-blocking)."""
    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/health")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def status_for(profile: ModelProfile) -> str:
    cleanup_dead(profile.name)
    state = runtime_processes.get(profile.name)

    if not state:
        return "offline"
    if not is_alive(state.process):
        return "offline"

    if not is_port_open("127.0.0.1", profile.port):
        return "starting"

    # llama-server binds its port before the model is loaded and serves
    # 503 on /health until it is ready — port-open alone is not "online".
    healthy = await _health_check(profile.port)
    return "online" if healthy else "starting"


# Approximate bytes per KV-cache element for llama.cpp --cache-type-k/v values
_KV_TYPE_BYTES = {
    "f32": 4.0, "f16": 2.0, "bf16": 2.0,
    "q8_0": 1.0625, "q5_1": 0.75, "q5_0": 0.6875,
    "q4_1": 0.625, "q4_0": 0.5625, "iq4_nl": 0.5625,
}

# Fit tolerance: estimates assume worst-case f16 dense-attention KV, so only
# warn when the estimate exceeds free VRAM by a clear margin.
_FIT_TOLERANCE = 1.25


def _kv_bytes_per_element(profile: ModelProfile) -> float:
    """Derive KV-cache element size from --cache-type-k/v in merged args."""
    args = [
        token
        for arg in _get_engine_default_args(profile.engine) + list(profile.extra_args)
        for token in arg.split()
    ]

    def flag_value(flag: str) -> str | None:
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    k = _KV_TYPE_BYTES.get((flag_value("--cache-type-k") or "f16").lower(), 2.0)
    v = _KV_TYPE_BYTES.get((flag_value("--cache-type-v") or "f16").lower(), 2.0)
    return (k + v) / 2


def vram_estimate_for(profile: ModelProfile) -> dict[str, Any] | None:
    """VRAM-fit estimate for a managed server's current config."""
    ctx_total = (profile.context_window or 4096) * (profile.parallel or 1)
    est = estimate_vram_gb(
        profile.model_path,
        ctx_total,
        profile.model_draft,
        kv_bytes_per_element=_kv_bytes_per_element(profile),
    )
    if not est:
        return None
    free = get_free_vram_gb()
    est["free_vram_gb"] = free
    est["likely_fits"] = (est["total_gb"] <= free * _FIT_TOLERANCE) if free is not None else None
    return est


def _load_progress(profile: ModelProfile, state: ProcessState) -> float | None:
    """Estimate model-load progress as bytes-read-by-process / model file size.

    Uses /proc/<pid>/io rchar, which tracks read() syscalls — accurate with
    --no-mmap, an underestimate with mmap (page faults bypass rchar).
    Returns None when the estimate is unavailable (non-Linux, permissions).
    """
    try:
        rchar: int | None = None
        with open(f"/proc/{state.process.pid}/io") as fh:
            for line in fh:
                if line.startswith("rchar:"):
                    rchar = int(line.split()[1])
                    break
        if rchar is None:
            return None
        total = Path(profile.model_path).stat().st_size
        if profile.model_draft:
            try:
                total += Path(profile.model_draft).stat().st_size
            except OSError:
                pass
        if total <= 0:
            return None
        return min(rchar / total, 1.0)
    except (OSError, ValueError):
        return None


async def model_payload(profile: ModelProfile) -> dict[str, Any]:
    # Get the profile with latest context_window from config
    profile = get_profile_with_config(profile)
    
    status = await status_for(profile)
    state = runtime_processes.get(profile.name)
    model_found = _binary_exists(str(profile.model_path)) if profile.model_path else False

    last_log = ""
    load_progress: float | None = None
    if status == "starting":
        log = server_logs.get(profile.name)
        tail = log.tail(1) if log else []
        last_log = tail[0][1] if tail else ""
        if state:
            progress = _load_progress(profile, state)
            load_progress = round(progress, 3) if progress is not None else None

    return {
        "id": profile.name,
        "display_name": profile.name,
        "model_path": str(profile.model_path),
        "engine": profile.engine,
        "service": "LLM",
        "family": "unknown",
        "size": "unknown",
        "description": "",
        "port": profile.port,
        "url": f"{Config.BASE_URL}:{profile.port}",
        "status": status,
        "pid": state.process.pid if state and status == "online" else None,
        "context_window": profile.context_window,
        "parallel": profile.parallel,
        "extra_args": profile.extra_args,
        "model_draft": profile.model_draft,
        "model_found": model_found,
        "managed": True,
        "last_exit": get_unexpected_exit(profile.name) if status == "offline" else None,
        "started_at": state.started_at if state else None,
        "last_log": last_log,
        "load_progress": load_progress,
        "vram_estimate": vram_estimate_for(profile) if model_found else None,
    }
