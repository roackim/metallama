from __future__ import annotations

import asyncio
import io
import json
import urllib.error
import urllib.request
import uuid
import zipfile
from typing import Any

from fastapi import HTTPException

from .profiles import MODEL_PROFILES
from .runtime import status_for

_zip_store: dict[str, tuple[bytes, str]] = {}


def extract_first_markdown(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()

    if isinstance(payload, list):
        for item in payload:
            text = extract_first_markdown(item)
            if text:
                return text
        return ""

    if isinstance(payload, dict):
        preferred_keys = (
            "md_content",
            "markdown",
            "md",
            "content",
            "text",
        )
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("result", "results", "data", "output", "outputs", "files", "pages"):
            if key in payload:
                text = extract_first_markdown(payload[key])
                if text:
                    return text

        for value in payload.values():
            text = extract_first_markdown(value)
            if text:
                return text

    return ""


def _get_mineru_profile():
    profile = MODEL_PROFILES.get("mineru-ocr")
    if not profile:
        raise HTTPException(status_code=500, detail="MinerU model profile is not configured")
    if status_for(profile) != "running":
        raise HTTPException(status_code=409, detail="OCR server is not running. Start MinerU first.")
    return profile


def _build_multipart_body(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    form_fields: dict[str, str],
) -> tuple[str, bytes]:
    boundary = f"----metallama-ocr-{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in form_fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    return boundary, bytes(body)


async def request_mineru_markdown(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    parse_method: str,
    backend: str,
) -> str:
    profile = _get_mineru_profile()
    request_filename = f"{uuid.uuid4().hex}_{filename}"

    form_fields = {
        "return_md": "true",
        "parse_method": parse_method or "auto",
        "backend": backend,
    }
    boundary, body = _build_multipart_body(file_bytes, request_filename, content_type, form_fields)

    def _send_request() -> tuple[int, str, str]:
        request = urllib.request.Request(
            url=f"http://127.0.0.1:{profile.port}/file_parse",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                status = response.status
                response_type = response.headers.get("Content-Type", "")
                payload = response.read().decode("utf-8", errors="ignore")
                return status, response_type, payload
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(
                status_code=502,
                detail=f"MinerU parse failed ({exc.code}): {payload[:400]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach OCR server: {exc}") from exc

    status, response_type, payload = await asyncio.to_thread(_send_request)
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"MinerU parse failed ({status})")

    parsed_payload: Any = payload
    if "json" in response_type:
        try:
            parsed_payload = json.loads(payload)
        except json.JSONDecodeError:
            parsed_payload = payload

    markdown = extract_first_markdown(parsed_payload)
    if not markdown:
        raise HTTPException(status_code=502, detail="MinerU returned no markdown content")

    return markdown


async def request_mineru_zip(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    parse_method: str,
    backend: str,
) -> tuple[str, str]:
    profile = _get_mineru_profile()
    request_filename = f"{uuid.uuid4().hex}_{filename}"

    form_fields = {
        "return_md": "true",
        "response_format_zip": "true",
        "parse_method": parse_method or "auto",
        "backend": backend,
    }
    boundary, body = _build_multipart_body(file_bytes, request_filename, content_type, form_fields)

    def _send_request() -> tuple[int, str, bytes]:
        request = urllib.request.Request(
            url=f"http://127.0.0.1:{profile.port}/file_parse",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                status = response.status
                resp_type = response.headers.get("Content-Type", "")
                raw = response.read()
                return status, resp_type, raw
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(
                status_code=502,
                detail=f"MinerU parse failed ({exc.code}): {payload[:400]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach OCR server: {exc}") from exc

    status, resp_type, raw = await asyncio.to_thread(_send_request)
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"MinerU parse failed ({status})")

    if not raw:
        raise HTTPException(status_code=502, detail="MinerU returned empty response")

    # Extract markdown from the ZIP
    markdown = ""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith(".md"):
                    markdown = zf.read(name).decode("utf-8", errors="ignore").strip()
                    if markdown:
                        break
    except zipfile.BadZipFile:
        pass

    if not markdown:
        markdown = "(Images extracted — no markdown found in ZIP)"

    from pathlib import Path
    stem = Path(filename).stem
    zip_id = uuid.uuid4().hex
    _zip_store[zip_id] = (raw, f"{stem}_ocr.zip")

    return markdown, zip_id


def pop_zip(zip_id: str) -> tuple[bytes, str] | None:
    return _zip_store.pop(zip_id, None)
