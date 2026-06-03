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
    parallel: int = 1


@dataclass
class ProcessState:
    process: subprocess.Popen[str]
    started_at: float
    command: list[str]

