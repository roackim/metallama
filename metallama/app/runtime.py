from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import urllib.error
import urllib.request
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
    """Get a profile with the latest context_window from server_configs.json."""
    config = get_server_config(profile.id)
    context_window = config.get("context_window")
    
    if context_window is not None and context_window != profile.context_window:
        return replace(profile, context_window=context_window)
    
    return profile


def mineru_runtime_env() -> dict[str, str]:
    env = os.environ.copy()

    hf_home = Path(Config.MINERU_HF_HOME).expanduser()
    hf_hub_cache = Path(Config.MINERU_HF_HUB_CACHE).expanduser()

    for path in (hf_home, hf_hub_cache):
        parent = path.parent
        if not parent.exists():
            raise HTTPException(
                status_code=400,
                detail=f"MinerU cache parent does not exist: {parent}",
            )
        path.mkdir(exist_ok=True)

    env["HF_HOME"] = str(hf_home)
    env["HUGGINGFACE_HUB_CACHE"] = str(hf_hub_cache)
    return env


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


def is_whisper_ready(port: int, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def resolve_mineru_binary() -> str:
    venv_path = Config.EXECUTABLE_MINERU_VENV.strip()
    if not venv_path:
        raise HTTPException(status_code=400, detail="METALLAMA_MINERU_VENV is not configured")

    binary = Path(venv_path) / "bin" / "mineru-api"
    if not binary.exists():
        raise HTTPException(status_code=400, detail=f"MinerU executable not found: {binary}")

    return str(binary)


def _resolve_binary(profile: ModelProfile) -> str:
    if profile.engine == "whisper":
        binary = Config.EXECUTABLE_WHISPER
    elif profile.engine == "mineru":
        return resolve_mineru_binary()
    else:
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
        extra_args += ["--ctx-size", str(profile.context_window)]

    if profile.engine == "mineru":
        return [binary, "--host", "0.0.0.0", "--port", str(profile.port), *extra_args]

    model_path = Path(profile.model_path)
    if not model_path.exists():
        raise HTTPException(status_code=400, detail=f"Model file not found: {profile.model_path}")

    return [binary, "--model", str(model_path), "--host", "0.0.0.0", "--port", str(profile.port), *extra_args]


def status_for(profile: ModelProfile) -> str:
    cleanup_dead(profile.id)
    state = runtime_processes.get(profile.id)

    if profile.engine == "mineru":
        return "running" if is_port_open("127.0.0.1", profile.port) else "stopped"

    if not state:
        return "stopped"
    if not is_alive(state.process):
        return "stopped"

    if profile.engine == "whisper":
        return "running" if is_whisper_ready(profile.port) else "starting"

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
    }
