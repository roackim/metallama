from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT

MAX_LOG_LINES = 2000
EXIT_TAIL_LINES = 12

LOGS_DIR = PROJECT_ROOT / "logs"


class ServerLog:
    """Thread-safe ring buffer of (seq, text) log lines for one server."""

    def __init__(self) -> None:
        self._lines: deque[tuple[int, str]] = deque(maxlen=MAX_LOG_LINES)
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, text: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, text))

    def since(self, seq: int) -> list[tuple[int, str]]:
        with self._lock:
            return [(s, t) for (s, t) in self._lines if s > seq]

    def tail(self, n: int) -> list[tuple[int, str]]:
        with self._lock:
            return list(self._lines)[-n:]


server_logs: dict[str, ServerLog] = {}
_last_exit: dict[str, dict[str, Any]] = {}
_expected_stops: set[str] = set()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)


def log_file_path(model_name: str) -> Path:
    return LOGS_DIR / f"{_safe_filename(model_name)}.log"


def mark_expected_stop(model_name: str) -> None:
    """Flag that the next exit of this server is user-initiated (not a crash)."""
    _expected_stops.add(model_name)


def get_last_exit(model_name: str) -> dict[str, Any] | None:
    return _last_exit.get(model_name)


def get_unexpected_exit(model_name: str) -> dict[str, Any] | None:
    entry = _last_exit.get(model_name)
    if entry and not entry.get("expected"):
        return entry
    return None


def begin_capture(model_name: str, proc: subprocess.Popen[str]) -> None:
    """Start a daemon thread that drains proc.stdout into a ring buffer and a
    log file (truncated on each start). Records exit info when the process dies.
    """
    log = ServerLog()
    server_logs[model_name] = log
    _last_exit.pop(model_name, None)
    _expected_stops.discard(model_name)

    file_path = log_file_path(model_name)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = file_path.open("w", encoding="utf-8", errors="replace")
    except OSError:
        fh = None

    def _reader() -> None:
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    text = line.rstrip("\n")
                    log.append(text)
                    if fh is not None:
                        try:
                            fh.write(text + "\n")
                            fh.flush()
                        except OSError:
                            pass
        finally:
            code = proc.wait()
            expected = model_name in _expected_stops
            _expected_stops.discard(model_name)
            _last_exit[model_name] = {
                "code": code,
                "at": int(time.time() * 1000),
                "expected": expected,
                "tail": [t for _, t in log.tail(EXIT_TAIL_LINES)],
            }
            log.append(f"[metallama] process exited with code {code}")
            if fh is not None:
                try:
                    fh.write(f"[metallama] process exited with code {code}\n")
                    fh.close()
                except OSError:
                    pass

    threading.Thread(target=_reader, name=f"log-{model_name}", daemon=True).start()
