from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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
    context_window: int | None = None


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
