from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelProfile:
    name: str
    engine: str
    model_path: str | Path
    port: int
    extra_args: list[str]
    context_window: int | None = None
    parallel: int = 1
    model_draft: str | Path | None = None
    mmproj: str | Path | None = None


@dataclass
class ProcessState:
    process: subprocess.Popen[str]
    started_at: float
    command: list[str]

