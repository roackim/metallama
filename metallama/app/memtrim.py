from __future__ import annotations

import asyncio
import ctypes
import ctypes.util

_libc: ctypes.CDLL | None = None
_resolved = False


def _get_libc() -> ctypes.CDLL | None:
    global _libc, _resolved
    if not _resolved:
        _resolved = True
        try:
            name = ctypes.util.find_library("c")
            _libc = ctypes.CDLL(name) if name else None
        except Exception:
            _libc = None
    return _libc


def malloc_trim() -> None:
    """Return free heap held by glibc back to the OS.

    glibc's allocator keeps freed memory in its heap by default and rarely
    returns it to the kernel, so transient large allocations (JSON parsing,
    HTTP buffers) inflate RSS permanently. Calling ``malloc_trim`` releases the
    reclaimable portion. No-op on platforms without glibc.
    """
    libc = _get_libc()
    if libc is not None and hasattr(libc, "malloc_trim"):
        try:
            libc.malloc_trim(0)
        except Exception:
            pass


async def periodic_malloc_trim(interval: float = 30.0) -> None:
    """Periodically release freed heap back to the OS until cancelled."""
    while True:
        await asyncio.sleep(interval)
        malloc_trim()
