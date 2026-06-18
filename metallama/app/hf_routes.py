"""Hugging Face Hub API routes — search, list files, download."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .auth import admin_guard
from .hf import download_model, list_gguf_files, search_models

router = APIRouter(prefix="/api/hf", tags=["huggingface"])


@router.get("/search")
async def search_endpoint(q: str = "") -> dict[str, Any]:
    if not q.strip():
        return {"results": []}
    results = await search_models(q.strip())
    return {"results": results}


@router.get("/models/{namespace}/{repo:path}/files")
async def files_endpoint(namespace: str, repo: str) -> dict[str, Any]:
    repo_id = f"{namespace}/{repo}"
    files = await list_gguf_files(repo_id)
    return {"repo_id": repo_id, "files": files}


@router.post("/download")
async def download_endpoint(payload: dict[str, Any] = Body(...), _guard: None = Depends(admin_guard)) -> StreamingResponse:
    repo_id = payload.get("repo_id", "")
    filenames = payload.get("filenames", [])
    if not repo_id or not filenames:
        raise HTTPException(status_code=400, detail="repo_id and filenames required")
    if not isinstance(filenames, list) or not all(isinstance(f, str) for f in filenames):
        raise HTTPException(status_code=400, detail="filenames must be a list of strings")

    async def stream():
        async for line in download_model(repo_id, filenames):
            yield json.dumps(line) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
