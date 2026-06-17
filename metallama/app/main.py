from __future__ import annotations

import asyncio
import shlex
import signal
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, Config
from .models import ProcessState
from .ollama.config import load_config as load_ollama_config
from .ollama.probe import probe_subservers
from .ollama.registry import init_registry as init_ollama_registry
from .ollama.routes.ollama import router as ollama_router
from .ollama.routes.openai import router as openai_router
from .profiles import MODEL_PROFILES
from .runtime import (
    build_command,
    cleanup_dead,
    is_alive,
    model_locks,
    model_payload,
    runtime_processes,
)

app = FastAPI(title="metallama")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Ollama / OpenAI gateway (mounted at /ollama)
# ---------------------------------------------------------------------------

_ollama_cfg = load_ollama_config()
init_ollama_registry(_ollama_cfg)
app.include_router(ollama_router, prefix="/ollama")
app.include_router(openai_router, prefix="/ollama")

# Server-side history storage (500 samples at 1s = ~8 minutes)
MAX_HISTORY_SAMPLES = 500
vram_history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_SAMPLES)
ram_history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_SAMPLES)


def server_profiles(service: str | None = None) -> dict[str, Any]:
    if service is None:
        return dict(MODEL_PROFILES)
    return {model_id: profile for model_id, profile in MODEL_PROFILES.items() if profile.service == service}


def servers_payload(service: str | None = None) -> list[dict[str, Any]]:
    return [model_payload(profile) for profile in server_profiles(service).values()]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/config")
def get_config() -> dict[str, str]:
    return {
        "EXECUTABLE_LLAMA": str(Config.EXECUTABLE_LLAMA),
        "BASE_URL": str(Config.BASE_URL),
    }


@app.get("/api/system/vram")
def get_vram_status() -> dict[str, Any]:
    """Get current VRAM usage from nvidia-smi."""
    try:
        result = subprocess.run(
            ["/usr/bin/nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"error": "nvidia-smi failed", "available": False}
        
        # Parse output: "used, total" (in MiB)
        lines = result.stdout.strip().split("\n")
        gpus = []
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                used_mb = float(parts[0].strip())
                total_mb = float(parts[1].strip())
                gpus.append({
                    "used_gb": round(used_mb / 1024, 2),
                    "total_gb": round(total_mb / 1024, 2),
                    "used_mb": int(used_mb),
                    "total_mb": int(total_mb),
                    "percent": round((used_mb / total_mb * 100) if total_mb > 0 else 0, 1),
                })
        
        # Store in history (aggregate across GPUs)
        if gpus:
            total_used = sum(gpu["used_gb"] for gpu in gpus)
            total_max = sum(gpu["total_gb"] for gpu in gpus)
            avg_percent = sum(gpu["percent"] for gpu in gpus) / len(gpus)
            vram_history.append({
                "timestamp": int(time.time() * 1000),
                "percent": round(avg_percent, 1),
                "used_gb": round(total_used, 2),
                "total_gb": round(total_max, 2),
            })
        
        return {"available": True, "gpus": gpus}
    except FileNotFoundError:
        return {"error": "nvidia-smi not found", "available": False}
    except subprocess.TimeoutExpired:
        return {"error": "nvidia-smi timeout", "available": False}
    except Exception as exc:
        return {"error": str(exc), "available": False}


@app.get("/api/system/ram")
def get_ram_status() -> dict[str, Any]:
    """Get current RAM usage."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        used_gb = round(mem.used / (1024**3), 2)
        total_gb = round(mem.total / (1024**3), 2)
        percent = round(mem.percent, 1)
        
        # Store in history
        ram_history.append({
            "timestamp": int(time.time() * 1000),
            "percent": percent,
            "used_gb": used_gb,
            "total_gb": total_gb,
        })
        
        return {
            "available": True,
            "used_gb": used_gb,
            "total_gb": total_gb,
            "percent": percent,
        }
    except ImportError:
        return {"error": "psutil not installed", "available": False}
    except Exception as exc:
        return {"error": str(exc), "available": False}


@app.get("/api/system/vram/history")
def get_vram_history() -> dict[str, Any]:
    """Get VRAM usage history."""
    return {"history": list(vram_history)}


@app.get("/api/system/ram/history")
def get_ram_history() -> dict[str, Any]:
    """Get RAM usage history."""
    return {"history": list(ram_history)}


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    return {"models": [model_payload(profile) for profile in MODEL_PROFILES.values()]}


@app.get("/api/llm/servers")
def list_llm_servers() -> dict[str, Any]:
    return {"servers": servers_payload()}


@app.get("/api/servers")
def list_servers() -> dict[str, Any]:
    return {"servers": servers_payload()}


@app.get("/api/llm/servers/status")
def list_llm_servers_status() -> dict[str, Any]:
    return {
        "servers": [
            {"id": payload["id"], "status": payload["status"], "pid": payload["pid"], "url": payload["url"]}
            for payload in servers_payload()
        ]
    }


@app.get("/api/servers/status")
def list_servers_status() -> dict[str, Any]:
    return {
        "servers": [
            {"id": payload["id"], "status": payload["status"], "pid": payload["pid"], "url": payload["url"]}
            for payload in servers_payload()
        ]
    }


@app.get("/api/llm/servers/{server_id}/status")
def llm_server_status(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    return model_payload(profile)


@app.get("/api/servers/{server_id}/status")
def server_status(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    return model_payload(profile)


@app.post("/api/models/{model_id}/start")
async def start_model(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")

    async with model_locks[model_id]:
        cleanup_dead(model_id)

        existing = runtime_processes.get(model_id)
        if existing and is_alive(existing.process):
            raise HTTPException(status_code=409, detail="Already running")

        command = build_command(profile)
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=f"Binary not found: {command[0]}") from exc

        runtime_processes[model_id] = ProcessState(
            process=proc,
            started_at=time.time(),
            command=command,
        )

    return {"ok": True, "model": model_payload(profile)}


@app.post("/api/llm/servers/{server_id}/start")
async def start_llm_server(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await start_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/servers/{server_id}/start")
async def start_server(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await start_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/models/{model_id}/stop")
async def stop_model(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")

    async with model_locks[model_id]:
        cleanup_dead(model_id)
        state = runtime_processes.get(model_id)
        if not state:
            return {"ok": True, "model": model_payload(profile)}

        proc = state.process
        if is_alive(proc):
            proc.terminate()
            for _ in range(20):
                if not is_alive(proc):
                    break
                await asyncio.sleep(0.25)
            if is_alive(proc):
                proc.kill()

        runtime_processes.pop(model_id, None)

    return {"ok": True, "model": model_payload(profile)}


@app.post("/api/llm/servers/{server_id}/stop")
async def stop_llm_server(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await stop_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.post("/api/servers/{server_id}/stop")
async def stop_server(server_id: str) -> dict[str, Any]:
    profile = server_profiles().get(server_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown server id")
    result = await stop_model(server_id)
    return {"ok": result["ok"], "server": result["model"]}


@app.get("/api/models/{model_id}/status")
def model_status(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")
    return model_payload(profile)


@app.on_event("startup")
async def probe_ollama_subservers() -> None:
    await probe_subservers()


@app.on_event("shutdown")
def stop_all_on_shutdown() -> None:
    for model_id, state in list(runtime_processes.items()):
        proc = state.process
        if is_alive(proc):
            proc.send_signal(signal.SIGTERM)
        runtime_processes.pop(model_id, None)


@app.get("/api/models/{model_id}/command")
def model_command_preview(model_id: str) -> dict[str, str]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")
    command = build_command(profile)
    return {"command": shlex.join(command)}


@app.post("/api/models/{model_id}/config")
async def update_model_config(model_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .profiles import reload_model_profiles
    from .unified_config import update_managed_server, load_unified_config
    
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")
    
    # Check if server is running - only allow changes when stopped
    async with model_locks[model_id]:
        cleanup_dead(model_id)
        state = runtime_processes.get(model_id)
        if state and is_alive(state.process):
            raise HTTPException(status_code=409, detail="Cannot change config while server is running")
    
    updates: dict[str, Any] = {}
    
    # Validate and collect context_window if provided
    if "context_window" in payload:
        context_window = payload["context_window"]
        if not isinstance(context_window, int) or context_window < 1:
            raise HTTPException(status_code=400, detail="context_window must be a positive integer")
        updates["context_window"] = context_window

    # Validate and collect parallel if provided
    if "parallel" in payload:
        parallel = payload["parallel"]
        if not isinstance(parallel, int) or parallel < 1:
            raise HTTPException(status_code=400, detail="parallel must be a positive integer")
        updates["parallel"] = parallel
    
    if updates:
        # Update config.yaml (machine-managed section)
        update_managed_server(model_id, updates)
        # Reload profiles from disk so changes take effect immediately
        reload_model_profiles()
    
    # Return updated config from unified config
    unified = load_unified_config()
    server_entry = next((s for s in unified.managed_servers if s.id == model_id), None)
    return {
        "ok": True,
        "config": {
            "context_window": server_entry.context_window,
            "parallel": server_entry.parallel,
        } if server_entry else {},
    }

