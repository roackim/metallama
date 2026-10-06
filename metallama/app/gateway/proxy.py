from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from ..http_client import get_client

_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)

# Hop-by-hop / re-encoded headers that must not be copied from the upstream
# response (httpx already decoded the body, and Starlette sets its own length).
_DROP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}


async def proxy(
    method: str,
    url: str,
    *,
    json_body: Any = None,
    content: bytes | None = None,
    params: Any = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Forward a request upstream and stream the response back verbatim.

    Status code and content type are preserved, so upstream errors (4xx/5xx)
    reach the client as-is instead of being masked as 200 or a JSON crash.
    """
    client = get_client()
    request = client.build_request(
        method, url, json=json_body, content=content, params=params, headers=headers, timeout=_TIMEOUT,
    )
    try:
        resp = await client.send(request, stream=True)
    except httpx.ConnectError:
        return JSONResponse({"error": "upstream unreachable"}, status_code=502)
    except httpx.TimeoutException:
        return JSONResponse({"error": "upstream timeout"}, status_code=504)

    is_sse = resp.headers.get("content-type", "").startswith("text/event-stream")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        except (httpx.ReadError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            # Headers are already sent; surface the failure in-band for SSE clients.
            if is_sse:
                error = "upstream timeout" if isinstance(exc, httpx.TimeoutException) else "upstream disconnected"
                yield b"data: " + json.dumps({"error": error}).encode() + b"\n\n"

    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}
    return StreamingResponse(
        body(), status_code=resp.status_code, headers=out_headers, background=BackgroundTask(resp.aclose),
    )
