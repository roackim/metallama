from __future__ import annotations

import asyncio
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .config import Config, get_server_config
from .models import ModelProfile, ProcessState
from .profiles import MODEL_PROFILES


runtime_processes: dict[str, ProcessState] = {}
model_locks: dict[str, asyncio.Lock] = {key: asyncio.Lock() for key in MODEL_PROFILES}

# Default args prepended before profile extra_args for each engine.
# Profile extra_args are appended after and take precedence (last flag wins in llama-server).
ENGINE_DEFAULT_ARGS: dict[str, list[str]] = {
    "llama": [
        "--flash-attn on", # Enable flash attention
        "--threads 4",
        "--n-gpu-layers 999",
    ],
}


def get_profile_with_config(profile: ModelProfile) -> ModelProfile:
    """Get a profile with the latest ui-configurable params from server_configs.json."""
    config = get_server_config(profile.id)
    overrides: dict = {}

    context_window = config.get("context_window")
    if context_window is not None and context_window != profile.context_window:
        overrides["context_window"] = context_window

    parallel = config.get("parallel")
    if parallel is not None and parallel != profile.parallel:
        overrides["parallel"] = parallel

    return replace(profile, **overrides) if overrides else profile



def is_alive(proc: subprocess.Popen[str]) -> bool:
    return proc.poll() is None


def cleanup_dead(model_id: str) -> None:
    state = runtime_processes.get(model_id)
    if state and not is_alive(state.process):
        runtime_processes.pop(model_id, None)


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

    extra_args = [
        token
        for arg in ENGINE_DEFAULT_ARGS.get(profile.engine, []) + list(profile.extra_args)
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

    return [binary, "--model", str(model_path), "--host", "0.0.0.0", "--port", str(profile.port), *extra_args]


def status_for(profile: ModelProfile) -> str:
    cleanup_dead(profile.id)
    state = runtime_processes.get(profile.id)

    if not state:
        return "stopped"
    if not is_alive(state.process):
        return "stopped"

    return "running" if is_port_open("127.0.0.1", profile.port) else "starting"


def model_payload(profile: ModelProfile) -> dict[str, Any]:
    # Get the profile with latest context_window from config
    profile = get_profile_with_config(profile)
    
    status = status_for(profile)
    state = runtime_processes.get(profile.id)
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "engine": profile.engine,
        "service": profile.service,
        "family": profile.family,
        "size": profile.size,
        "description": profile.description,
        "port": profile.port,
        "url": f"{Config.BASE_URL}:{profile.port}",
        "status": status,
        "pid": state.process.pid if state and status == "running" else None,
        "context_window": profile.context_window,
        "parallel": profile.parallel,
    }
