from __future__ import annotations

import asyncio
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, Config
from .models import ProcessState
from .ocr_utils import pop_zip, request_mineru_markdown, request_mineru_zip
from .profiles import MODEL_PROFILES
from .runtime import (
    build_command,
    cleanup_dead,
    is_alive,
    is_port_open,
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/config")
def get_config() -> dict[str, str]:
    return {
        "EXECUTABLE_LLAMA": str(Config.EXECUTABLE_LLAMA),
        "EXECUTABLE_WHISPER": str(Config.EXECUTABLE_WHISPER),
        "EXECUTABLE_MINERU_VENV": str(Config.EXECUTABLE_MINERU_VENV),
        "BASE_URL": str(Config.BASE_URL),
    }


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    return {"models": [model_payload(profile) for profile in MODEL_PROFILES.values()]}


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
    backend: str = Form("pipeline"),
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

    if extract_images:
        markdown, zip_id = await request_mineru_zip(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            parse_method=parse_method,
            backend=backend,
        )
        return {"filename": filename, "markdown": markdown, "zip_id": zip_id}

    markdown = await request_mineru_markdown(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        parse_method=parse_method,
        backend=backend,
    )

    return {"filename": filename, "markdown": markdown}


@app.get("/api/ocr/zip/{zip_id}")
def download_ocr_zip(zip_id: str) -> StreamingResponse:
    entry = pop_zip(zip_id)
    if not entry:
        raise HTTPException(status_code=404, detail="ZIP not found or already downloaded")
    zip_bytes, zip_name = entry
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
