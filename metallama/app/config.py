from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


class Config:
    EXECUTABLE_LLAMA = os.getenv("METALLAMA_LLAMACPP_BINARY", "")
    EXECUTABLE_WHISPER = os.getenv("METALLAMA_WHISPER_BINARY", "")
    EXECUTABLE_MINERU_VENV = os.getenv("METALLAMA_MINERU_VENV", "")
    MINERU_BACKEND = os.getenv("METALLAMA_MINERU_BACKEND", "pipeline")
    # Keep MinerU caches off the root filesystem.
    MINERU_HF_HOME = os.getenv("METALLAMA_MINERU_HF_HOME")
    MINERU_HF_HUB_CACHE = os.getenv("METALLAMA_MINERU_HF_HUB_CACHE")
    BASE_URL = os.getenv("METALLAMA_BASE_URL", "http://gpu4.hygeos.com")
    OUTPUT_RETENTION_HOURS = int(os.getenv("METALLAMA_OUTPUT_RETENTION_HOURS", "12"))
    OUTPUT_MAX_ENTRIES = int(os.getenv("METALLAMA_OUTPUT_MAX_ENTRIES", "60"))


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
