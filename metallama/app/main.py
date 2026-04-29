from __future__ import annotations

import asyncio
import io
import shlex
import shutil
import signal
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, STATIC_DIR, Config
from .models import ProcessState
from .ocr_utils import get_zip, request_mineru_markdown, request_mineru_zip
from .profiles import MODEL_PROFILES
from .runtime import (
    build_command,
    cleanup_dead,
    is_alive,
    is_port_open,
    mineru_runtime_env,
    model_locks,
    model_payload,
    runtime_processes,
)
from .transcript_utils import (
    collapse_repetitions,
    extract_chunk_text,
    ndjson_line,
    normalize_audio_to_wav,
    request_whisper_chunk,
    split_wav_chunks,
)

app = FastAPI(title="metallama")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

transcript_semaphore = asyncio.Semaphore(1)


def server_profiles(service: str | None = None) -> dict[str, Any]:
    if service is None:
        return dict(MODEL_PROFILES)
    return {model_id: profile for model_id, profile in MODEL_PROFILES.items() if profile.service == service}


def servers_payload(service: str | None = None) -> list[dict[str, Any]]:
    return [model_payload(profile) for profile in server_profiles(service).values()]


def cleanup_output_directory(retention_hours: int, max_entries: int) -> None:
    output_dir = PROJECT_ROOT / "output"
    if not output_dir.exists() or not output_dir.is_dir():
        return

    now = time.time()
    ttl_seconds = max(0, retention_hours) * 3600
    entries: list[Path] = []

    for path in output_dir.iterdir():
        try:
            entries.append(path)
            if ttl_seconds > 0 and now - path.stat().st_mtime > ttl_seconds:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        except OSError:
            continue

    if max_entries <= 0:
        return

    try:
        remaining = [p for p in output_dir.iterdir()]
    except OSError:
        return

    if len(remaining) <= max_entries:
        return

    try:
        remaining.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return

    for stale in remaining[max_entries:]:
        try:
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            else:
                stale.unlink(missing_ok=True)
        except OSError:
            continue


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/config")
def get_config() -> dict[str, str]:
    return {
        "EXECUTABLE_LLAMA": str(Config.EXECUTABLE_LLAMA),
        "EXECUTABLE_WHISPER": str(Config.EXECUTABLE_WHISPER),
        "EXECUTABLE_MINERU_VENV": str(Config.EXECUTABLE_MINERU_VENV),
        "MINERU_BACKEND": str(Config.MINERU_BACKEND),
        "MINERU_HF_HOME": str(Config.MINERU_HF_HOME),
        "MINERU_HF_HUB_CACHE": str(Config.MINERU_HF_HUB_CACHE),
        "BASE_URL": str(Config.BASE_URL),
    }


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

        if profile.engine == "mineru" and is_port_open("127.0.0.1", profile.port):
            raise HTTPException(status_code=409, detail="Already running")

        existing = runtime_processes.get(model_id)
        if existing and is_alive(existing.process):
            raise HTTPException(status_code=409, detail="Already running")

        command = build_command(profile)
        try:
            proc_env = mineru_runtime_env() if profile.engine == "mineru" else None
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=proc_env,
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


@app.post("/api/transcript/stream")
async def transcript_stream(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    include_timecodes: bool = Form(False),
) -> StreamingResponse:
    if language not in {"auto", "fr", "en"}:
        raise HTTPException(status_code=400, detail="Invalid language. Use auto, fr, or en.")

    raw_audio = await file.read()
    if not raw_audio:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty")

    async def stream() -> AsyncIterator[bytes]:
        try:
            if transcript_semaphore.locked():
                yield ndjson_line(
                    {
                        "event": "queued",
                        "message": "Another transcription is running. Waiting for GPU slot...",
                        "progress": 0,
                    }
                )

            async with transcript_semaphore:
                started_at = time.time()
                yield ndjson_line({"event": "status", "message": "Normalizing audio with ffmpeg...", "progress": 2})

                wav_bytes = await asyncio.to_thread(normalize_audio_to_wav, raw_audio)

                yield ndjson_line({"event": "status", "message": "Chunking audio with overlap-aware stitching...", "progress": 5})

                chunks, sample_rate = await asyncio.to_thread(split_wav_chunks, wav_bytes, 25.0, 0.8)
                total_chunks = max(1, len(chunks))
                parts: list[str] = []

                for index, chunk in enumerate(chunks, start=1):
                    before_chunk_progress = 5 + int(((index - 1) / total_chunks) * 90)
                    after_chunk_progress = 5 + int((index / total_chunks) * 90)
                    yield ndjson_line(
                        {
                            "event": "status",
                            "message": f"Transcribing chunk {index}/{total_chunks}...",
                            "progress": before_chunk_progress,
                        }
                    )

                    payload = await request_whisper_chunk(chunk.wav_bytes, language)
                    chunk_text = extract_chunk_text(
                        payload,
                        include_timecodes=include_timecodes,
                        chunk_start_seconds=chunk.start_frame / sample_rate,
                        prefix_skip_seconds=chunk.prefix_skip_seconds,
                    )
                    if chunk_text:
                        parts.append(chunk_text)

                    joined_text = "\n".join(parts) if include_timecodes else " ".join(parts)
                    live_text = collapse_repetitions(joined_text)
                    yield ndjson_line(
                        {
                            "event": "partial",
                            "progress": after_chunk_progress,
                            "text": live_text,
                            "chunk_index": index,
                            "chunk_total": total_chunks,
                        }
                    )

                final_joined = "\n".join(parts) if include_timecodes else " ".join(parts)
                final_text = collapse_repetitions(final_joined)
                elapsed_ms = int((time.time() - started_at) * 1000)
                yield ndjson_line(
                    {
                        "event": "done",
                        "progress": 100,
                        "text": final_text,
                        "elapsed_ms": elapsed_ms,
                        "language": language,
                    }
                )
        except HTTPException as exc:
            yield ndjson_line({"event": "error", "message": str(exc.detail)})
        except Exception as exc:  # pragma: no cover
            yield ndjson_line({"event": "error", "message": f"Unexpected transcription failure: {exc}"})

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/ocr/parse")
async def ocr_parse(
    file: UploadFile = File(...),
    parse_method: str = Form("auto"),
    extract_images: bool = Form(False),
) -> Any:
    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, PNG, JPG, or JPEG.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    content_type = file.content_type or "application/octet-stream"

    try:
        if extract_images:
            markdown, zip_id, image_count = await request_mineru_zip(
                file_bytes=file_bytes,
                filename=filename,
                content_type=content_type,
                parse_method=parse_method,
                backend=Config.MINERU_BACKEND,
            )
            return {"filename": filename, "markdown": markdown, "zip_id": zip_id, "image_count": image_count}

        markdown = await request_mineru_markdown(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            parse_method=parse_method,
            backend=Config.MINERU_BACKEND,
        )

        return {"filename": filename, "markdown": markdown}
    finally:
        await asyncio.to_thread(
            cleanup_output_directory,
            Config.OUTPUT_RETENTION_HOURS,
            Config.OUTPUT_MAX_ENTRIES,
        )


@app.get("/api/ocr/zip/{zip_id}")
def download_ocr_zip(zip_id: str) -> StreamingResponse:
    entry = get_zip(zip_id)
    if not entry:
        raise HTTPException(status_code=404, detail="ZIP not found")
    zip_bytes, zip_name = entry
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.post("/api/ocr/zip/bundle")
def download_ocr_zip_bundle(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Missing zip bundle items")

    bundle_buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(bundle_buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in items:
            if not isinstance(item, dict):
                continue
            zip_id = str(item.get("zip_id") or "").strip()
            if not zip_id:
                continue
            entry = get_zip(zip_id)
            if not entry:
                continue

            zip_bytes, zip_name = entry
            file_name = str(item.get("file_name") or "").strip()
            if file_name:
                safe_name = f"{Path(file_name).stem}.ocr.zip"
            else:
                safe_name = zip_name
            safe_name = Path(safe_name).name or f"ocr_{count + 1:04d}.zip"

            bundle.writestr(safe_name, zip_bytes)
            count += 1

    if count == 0:
        raise HTTPException(status_code=404, detail="No OCR ZIP entries available")

    return StreamingResponse(
        iter([bundle_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="ocr_bundle.zip"'},
    )
