from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

# A generous default; callers that need a specific bound (fast health checks,
# long streaming reads) pass an explicit ``timeout=`` on the individual call.
_DEFAULT_TIMEOUT = httpx.Timeout(10.0)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the process-wide shared AsyncClient.

    Reusing a single client (and its connection pool) avoids the large,
    non-reclaimable glibc heap growth caused by constructing a new client per
    request under sustained load. Pass per-request timeouts to individual calls.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
    return _client


@asynccontextmanager
async def shared_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield the shared AsyncClient without closing it.

    Drop-in replacement for ``httpx.AsyncClient(...)`` in ``async with`` blocks.
    Unlike constructing a new client, exiting this context does NOT close the
    underlying client, so its connection pool is reused across requests.
    """
    yield get_client()


async def aclose_client() -> None:
    """Close the shared client (call on application shutdown)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
