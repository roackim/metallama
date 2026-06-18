from __future__ import annotations

import asyncio
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .config import Config
from .models import ModelProfile, ProcessState
from .profiles import MODEL_PROFILES
from .unified_config import load_unified_config


runtime_processes: dict[str, ProcessState] = {}
model_locks: dict[str, asyncio.Lock] = {key: asyncio.Lock() for key in MODEL_PROFILES}


def _get_engine_default_args(engine: str) -> list[str]:
    """Get default CLI args for an engine from unified config."""
    config = load_unified_config()
    defaults = config.engine_defaults.get(engine)
    if defaults and hasattr(defaults, "to_cli_args"):
        return defaults.to_cli_args()
    return []


def get_profile_with_config(profile: ModelProfile) -> ModelProfile:
    """Get a profile with the latest params from unified config.yaml.

    Looks up the managed_server entry by id and applies any overrides
    for context_window and parallel that may have been updated in config.
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

    return replace(profile, **overrides) if overrides else profile



def is_alive(proc: subprocess.Popen[str]) -> bool:
    return proc.poll() is None


def cleanup_dead(model_name: str) -> None:
    state = runtime_processes.get(model_name)
    if state and not is_alive(state.process):
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

    extra_args = (
        _get_engine_default_args(profile.engine) + list(profile.extra_args)
    )

    if profile.engine == "llama" and profile.context_window is not None:
        extra_args = _strip_flag(extra_args, "--ctx-size")
        total_ctx = profile.context_window * profile.parallel
        extra_args += ["--ctx-size", str(total_ctx)]

    if profile.engine == "llama" and profile.parallel is not None:
        extra_args = _strip_flag(extra_args, "--parallel")
        extra_args += ["--parallel", str(profile.parallel)]

    return ([binary, "--model", str(profile.model_path), "--host", "0.0.0.0", "--port", str(profile.port), *extra_args], found)


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

    extra_args = (
        _get_engine_default_args(profile.engine) + list(profile.extra_args)
    )

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
    cleanup_dead(profile.name)
    state = runtime_processes.get(profile.name)

    if not state:
        return "offline"
    if not is_alive(state.process):
        return "offline"

    return "online" if is_port_open("127.0.0.1", profile.port) else "starting"


def model_payload(profile: ModelProfile) -> dict[str, Any]:
    # Get the profile with latest context_window from config
    profile = get_profile_with_config(profile)
    
    status = status_for(profile)
    state = runtime_processes.get(profile.name)
    model_found = _binary_exists(str(profile.model_path)) if profile.model_path else False
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
        "model_found": model_found,
        "managed": True,
    }
