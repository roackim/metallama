from __future__ import annotations

import asyncio
import io
import json
import os
import shlex
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi import File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class ModelProfile:
    id: str
    display_name: str
    engine: str
    service: str
    family: str
    size: str
    description: str
    model_path: str | Path
    port: int
    extra_args: list[str]


@dataclass
class ProcessState:
    process: subprocess.Popen[str]
    started_at: float
    command: list[str]


@dataclass(frozen=True)
class AudioChunk:
    wav_bytes: bytes
    start_frame: int
    prefix_skip_seconds: float


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


class Config:
    EXECUTABLE_LLAMA = os.getenv("METALLAMA_LLAMACPP_BINARY", "")
    EXECUTABLE_WHISPER = os.getenv("METALLAMA_WHISPER_BINARY", "")
    EXECUTABLE_MINERU_VENV = os.getenv("METALLAMA_MINERU_VENV", "")
    BASE_URL = os.getenv("METALLAMA_BASE_URL", "http://gpu4.hygeos.com")

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

MODEL_PROFILES: dict[str, ModelProfile] = {
    "qwen35-27b-code": ModelProfile(
        id="qwen35-27b-code",
        display_name="Assistant",
        engine="llama",
        service="LLM",
        family="Qwen 3.5",
        size="27B",
        description="Primary coding model for chat and generation tasks.",
        model_path="/envs/local/llm/models/Qwen3.5-27B-Q8_0.gguf",
        port=8011,
        extra_args=[
            "--ctx-size 229376",
            "--threads 16",
            "--n-gpu-layers 999",
            "--temp 1.0",
            "--top-p 0.95",
            "--top-k 20",
            "--min-p 0.00",
            "--presence_penalty 1.5",
            "--repeat-penalty 1.0",
        ],
    ),
    "whisper-large-v3": ModelProfile(
        id="whisper-large-v3",
        display_name="Scribe",
        engine="whisper",
        service="AUDIO",
        family="Whisper",
        size="Large",
        description="Advanced transcription model for diverse audio processing.",
        model_path="/local_home/debian/llm/whisper.cpp/models/ggml-large-v3-turbo.bin",
        port=8013,
        extra_args=[
        ],
    ),
    "mineru-ocr": ModelProfile(
        id="mineru-ocr",
        display_name="Reader",
        engine="mineru",
        service="OCR",
        family="MinerU",
        size="N/A",
        description="OCR API server powered by mineru-api.",
        model_path="",
        port=8014,
        extra_args=[],
    ),
}

app = FastAPI(title="metallama")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


runtime_processes: dict[str, ProcessState] = {}
model_locks: dict[str, asyncio.Lock] = {key: asyncio.Lock() for key in MODEL_PROFILES}
transcript_semaphore = asyncio.Semaphore(1)


def _is_alive(proc: subprocess.Popen[str]) -> bool:
    return proc.poll() is None


def _cleanup_dead(model_id: str) -> None:
    state = runtime_processes.get(model_id)
    if state and not _is_alive(state.process):
        runtime_processes.pop(model_id, None)


def _is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_whisper_ready(port: int, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _resolve_mineru_binary() -> str:
    venv_path = Config.EXECUTABLE_MINERU_VENV.strip()
    if not venv_path:
        raise HTTPException(
            status_code=400,
            detail="METALLAMA_MINERU_VENV is not configured",
        )

    binary = Path(venv_path) / "bin" / "mineru-api"
    if not binary.exists():
        raise HTTPException(
            status_code=400,
            detail=f"MinerU executable not found: {binary}",
        )

    return str(binary)


def _build_command(profile: ModelProfile) -> list[str]:
    if profile.engine == "whisper":
        binary = Config.EXECUTABLE_WHISPER
    elif profile.engine == "mineru":
        binary = _resolve_mineru_binary()
    else:
        binary = Config.EXECUTABLE_LLAMA

    if not binary:
        raise HTTPException(status_code=400, detail=f"{profile.engine} binary is empty")

    binary_path = Path(binary)
    if binary_path.is_absolute() and not binary_path.exists():
        raise HTTPException(status_code=400, detail=f"Binary does not exist: {binary}")

    # Accept both extra arg styles:
    normalized_extra_args: list[str] = []
    for arg in profile.extra_args:
        parts = shlex.split(arg)
        normalized_extra_args.extend(parts if parts else [arg])

    if profile.engine == "mineru":
        return [
            str(binary),
            "--host",
            "0.0.0.0",
            "--port",
            str(profile.port),
            *normalized_extra_args,
        ]

    model_path = Path(profile.model_path)
    if not model_path.exists():
        raise HTTPException(status_code=400, detail=f"Model file not found: {profile.model_path}")

    if profile.engine == "whisper":
        return [
            str(binary),
            "--model",
            str(model_path),
            "--host",
            "0.0.0.0",
            "--port",
            str(profile.port),
            *normalized_extra_args,
        ]
    else:
        return [
            str(binary),
            "--model",
            str(model_path),
            "--host",
            "0.0.0.0",
            "--port",
            str(profile.port),
            *normalized_extra_args,
        ]


def _status_for(profile: ModelProfile) -> str:
    _cleanup_dead(profile.id)
    state = runtime_processes.get(profile.id)

    # MinerU may daemonize/fork and detach from the parent process.
    # Treat an open service port as the source of truth for runtime status.
    if profile.engine == "mineru":
        return "running" if _is_port_open("127.0.0.1", profile.port) else "stopped"

    if not state:
        return "stopped"
    if not _is_alive(state.process):
        return "stopped"

    if profile.engine == "whisper":
        return "running" if _is_whisper_ready(profile.port) else "starting"

    return "running" if _is_port_open("127.0.0.1", profile.port) else "starting"


def _model_payload(profile: ModelProfile) -> dict[str, Any]:
    status = _status_for(profile)
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
    }


def _normalize_audio_to_wav(input_bytes: bytes) -> bytes:
    command = [
        "ffmpeg",
        "-i",
        "pipe:0",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed on the server") from exc

    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Audio normalization failed: {result.stderr.decode(errors='ignore').strip()}",
        )

    if not result.stdout:
        raise HTTPException(status_code=400, detail="Audio normalization produced empty output")

    return result.stdout


def _split_wav_chunks(
    wav_bytes: bytes,
    chunk_seconds: float = 25.0,
    overlap_seconds: float = 0.5,
) -> tuple[list[AudioChunk], int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_reader:
        channels = wav_reader.getnchannels()
        sample_width = wav_reader.getsampwidth()
        sample_rate = wav_reader.getframerate()
        header_frame_count = wav_reader.getnframes()
        raw_frames = wav_reader.readframes(header_frame_count)

    frame_size = channels * sample_width
    frame_count = len(raw_frames) // frame_size
    frames_per_chunk = max(1, int(sample_rate * chunk_seconds))
    overlap_frames = max(0, int(sample_rate * overlap_seconds))
    step_frames = max(1, frames_per_chunk - overlap_frames)
    chunks: list[AudioChunk] = []

    for start_frame in range(0, frame_count, step_frames):
        end_frame = min(frame_count, start_frame + frames_per_chunk)
        start_byte = start_frame * frame_size
        end_byte = end_frame * frame_size
        chunk_frames = raw_frames[start_byte:end_byte]

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(sample_width)
            writer.setframerate(sample_rate)
            writer.writeframes(chunk_frames)
        chunks.append(
            AudioChunk(
                wav_bytes=buffer.getvalue(),
                start_frame=start_frame,
                prefix_skip_seconds=overlap_seconds if start_frame > 0 else 0.0,
            )
        )

        if end_frame >= frame_count:
            break

    return chunks, sample_rate


def _to_segment_seconds(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    # whisper.cpp often emits centiseconds (t0/t1); fallback to seconds if already small.
    return numeric / 100.0 if numeric > 200 else numeric


def _extract_segments(payload: Any) -> list[tuple[float, float, str]]:
    if not isinstance(payload, dict):
        return []

    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return []

    segments: list[tuple[float, float, str]] = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue

        text = str(segment.get("text", "")).strip()
        if not text:
            continue

        start_s = _to_segment_seconds(segment.get("t0", 0))
        end_s = _to_segment_seconds(segment.get("t1", 0))
        if end_s <= start_s:
            continue

        segments.append((start_s, end_s, text))

    return segments


def _format_timestamp(seconds: float) -> str:
    whole = max(0, int(seconds))
    mins, secs = divmod(whole, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _extract_chunk_text(
    payload: Any,
    include_timecodes: bool,
    chunk_start_seconds: float,
    prefix_skip_seconds: float,
) -> str:
    segments = _extract_segments(payload)
    if segments:
        # Keep only segments that begin after the overlap guard band.
        # This avoids keeping half-cut leading words from the current chunk.
        threshold = max(0.0, prefix_skip_seconds - 0.05)
        kept_segments = [seg for seg in segments if seg[0] >= threshold]
        if not kept_segments:
            kept_segments = segments
        if include_timecodes:
            lines: list[str] = []
            for start_s, end_s, text in kept_segments:
                start = _format_timestamp(chunk_start_seconds + start_s)
                end = _format_timestamp(chunk_start_seconds + end_s)
                lines.append(f"[{start} - {end}] {text}")
            if lines:
                return "\n".join(lines)
        else:
            text_parts = [text for _, _, text in kept_segments]
            if text_parts:
                return " ".join(text_parts).strip()

    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()

    if isinstance(payload, str):
        return payload.strip()

    return ""


def _collapse_repetitions(text: str) -> str:
    tokens = text.split()
    if len(tokens) < 20:
        return text.strip()

    cleaned: list[str] = []
    current = ""
    run = 0
    for token in tokens:
        if token == current:
            run += 1
            if run <= 6:
                cleaned.append(token)
        else:
            current = token
            run = 1
            cleaned.append(token)

    return " ".join(cleaned).strip()


async def _request_whisper_chunk(chunk_wav: bytes, language: str) -> Any:
    profile = MODEL_PROFILES.get("whisper-large-v3")
    if not profile:
        raise HTTPException(status_code=500, detail="Whisper model profile is not configured")

    if _status_for(profile) != "running":
        raise HTTPException(status_code=409, detail="Audio server is not running. Start Whisper server first.")

    data = {
        "task": "transcribe",
        "temperature": "0.0",
    }
    if language in {"fr", "en"}:
        data["language"] = language

    boundary = f"----metallama-{uuid.uuid4().hex}"
    body = bytearray()
    for key, value in data.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="file"; filename="chunk.wav"\r\n')
    body.extend(b"Content-Type: audio/wav\r\n\r\n")
    body.extend(chunk_wav)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    def _send_request() -> tuple[int, str, str]:
        request = urllib.request.Request(
            url=f"http://127.0.0.1:{profile.port}/inference",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                payload = response.read().decode("utf-8", errors="ignore")
                return status, content_type, payload
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(
                status_code=502,
                detail=f"Whisper inference failed ({exc.code}): {payload[:400]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach whisper server: {exc}") from exc

    status, content_type, payload = await asyncio.to_thread(_send_request)

    if status >= 400:
        raise HTTPException(status_code=502, detail=f"Whisper inference failed ({status})")

    if "json" in content_type:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {"text": payload}
    return payload


def _ndjson_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")


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
    return {"models": [_model_payload(profile) for profile in MODEL_PROFILES.values()]}


@app.post("/api/models/{model_id}/start")
async def start_model(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")

    async with model_locks[model_id]:
        _cleanup_dead(model_id)

        if profile.engine == "mineru" and _is_port_open("127.0.0.1", profile.port):
            raise HTTPException(status_code=409, detail="Already running")

        existing = runtime_processes.get(model_id)
        if existing and _is_alive(existing.process):
            raise HTTPException(status_code=409, detail="Already running")

        command = _build_command(profile)
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

    return {"ok": True, "model": _model_payload(profile)}


@app.post("/api/models/{model_id}/stop")
async def stop_model(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")

    async with model_locks[model_id]:
        _cleanup_dead(model_id)
        state = runtime_processes.get(model_id)
        if not state:
            return {"ok": True, "model": _model_payload(profile)}

        proc = state.process
        if _is_alive(proc):
            proc.terminate()
            for _ in range(20):
                if not _is_alive(proc):
                    break
                await asyncio.sleep(0.25)
            if _is_alive(proc):
                proc.kill()

        runtime_processes.pop(model_id, None)

    return {"ok": True, "model": _model_payload(profile)}


@app.get("/api/models/{model_id}/status")
def model_status(model_id: str) -> dict[str, Any]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")
    return _model_payload(profile)


@app.on_event("shutdown")
def stop_all_on_shutdown() -> None:
    for model_id, state in list(runtime_processes.items()):
        proc = state.process
        if _is_alive(proc):
            proc.send_signal(signal.SIGTERM)
        runtime_processes.pop(model_id, None)


@app.get("/api/models/{model_id}/command")
def model_command_preview(model_id: str) -> dict[str, str]:
    profile = MODEL_PROFILES.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown model id")
    command = _build_command(profile)
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
                yield _ndjson_line(
                    {
                        "event": "queued",
                        "message": "Another transcription is running. Waiting for GPU slot...",
                        "progress": 0,
                    }
                )

            async with transcript_semaphore:
                started_at = time.time()
                yield _ndjson_line(
                    {
                        "event": "status",
                        "message": "Normalizing audio with ffmpeg...",
                        "progress": 2,
                    }
                )

                wav_bytes = await asyncio.to_thread(_normalize_audio_to_wav, raw_audio)

                yield _ndjson_line(
                    {
                        "event": "status",
                        "message": "Chunking audio with overlap-aware stitching...",
                        "progress": 5,
                    }
                )

                chunks, sample_rate = await asyncio.to_thread(_split_wav_chunks, wav_bytes, 25.0, 0.8)
                total_chunks = max(1, len(chunks))
                parts: list[str] = []

                for index, chunk in enumerate(chunks, start=1):
                    before_chunk_progress = 5 + int(((index - 1) / total_chunks) * 90)
                    after_chunk_progress = 5 + int((index / total_chunks) * 90)
                    yield _ndjson_line(
                        {
                            "event": "status",
                            "message": f"Transcribing chunk {index}/{total_chunks}...",
                            "progress": before_chunk_progress,
                        }
                    )

                    payload = await _request_whisper_chunk(chunk.wav_bytes, language)
                    chunk_text = _extract_chunk_text(
                        payload,
                        include_timecodes=include_timecodes,
                        chunk_start_seconds=chunk.start_frame / sample_rate,
                        prefix_skip_seconds=chunk.prefix_skip_seconds,
                    )
                    if chunk_text:
                        parts.append(chunk_text)

                    joined_text = "\n".join(parts) if include_timecodes else " ".join(parts)
                    live_text = _collapse_repetitions(joined_text)
                    yield _ndjson_line(
                        {
                            "event": "partial",
                            "progress": after_chunk_progress,
                            "text": live_text,
                            "chunk_index": index,
                            "chunk_total": total_chunks,
                        }
                    )

                final_joined = "\n".join(parts) if include_timecodes else " ".join(parts)
                final_text = _collapse_repetitions(final_joined)
                elapsed_ms = int((time.time() - started_at) * 1000)
                yield _ndjson_line(
                    {
                        "event": "done",
                        "progress": 100,
                        "text": final_text,
                        "elapsed_ms": elapsed_ms,
                        "language": language,
                    }
                )
        except HTTPException as exc:
            yield _ndjson_line(
                {
                    "event": "error",
                    "message": str(exc.detail),
                }
            )
        except Exception as exc:  # pragma: no cover
            yield _ndjson_line(
                {
                    "event": "error",
                    "message": f"Unexpected transcription failure: {exc}",
                }
            )

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
