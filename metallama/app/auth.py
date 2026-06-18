"""Admin authentication — session-token based, scrypt password check."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SESSION_TTL = 8 * 60 * 60  # 8 hours in seconds
_sessions: dict[str, float] = {}  # token → expires_at (epoch)

_password_hash = os.getenv("METALLAMA_ADMIN_PASS_HASH", "").strip()

# scrypt params (stored inside the hash string)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def auth_enabled() -> bool:
    """Return True if admin auth is configured."""
    return bool(_password_hash)


# ---------------------------------------------------------------------------
# Password hashing (hashlib.scrypt — no external deps)
# ---------------------------------------------------------------------------

def _hash_password(plain: str, salt: bytes) -> bytes:
    """Derive a key from *plain* using scrypt with the given *salt*."""
    return hashlib.scrypt(
        plain.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )


def hash_password(plain: str) -> str:
    """Return a self-contained hash string: ``scrypt$N$r$p$<salt_b64>$<key_b64>``."""
    import base64
    salt = secrets.token_bytes(16)
    key = _hash_password(plain, salt)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def check_password(plain: str) -> bool:
    """Verify *plain* against the stored scrypt hash string."""
    import base64
    parts = _password_hash.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
    salt = base64.b64decode(parts[4])
    expected = base64.b64decode(parts[5])
    actual = hashlib.scrypt(plain.encode(), salt=salt, n=n, r=r, p=p, dklen=len(expected))
    return hmac.compare_digest(actual, expected)


def create_session() -> tuple[str, float]:
    """Create a new session token. Returns (token, expires_at)."""
    token = secrets.token_urlsafe(32)
    expires = time.time() + _SESSION_TTL
    _sessions[token] = expires
    return token, expires


def revoke_session(token: str) -> None:
    """Delete a session."""
    _sessions.pop(token, None)


def validate_session(token: str) -> bool:
    """Check whether *token* is a live (non-expired) session."""
    expires = _sessions.get(token)
    if expires is None:
        return False
    if time.time() > expires:
        _sessions.pop(token, None)
        return False
    return True


def _purge_expired() -> None:
    """Housekeeping — evict expired tokens."""
    now = time.time()
    stale = [t for t, exp in _sessions.items() if now > exp]
    for t in stale:
        _sessions.pop(t, None)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

class AdminGuard:
    """Use with ``Depends(admin_guard)`` on protected routes.

    When auth is disabled (no hash configured), all requests pass through.
    """

    def __call__(self, authorization: str = Header("")) -> None:
        if not auth_enabled():
            return
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        token = authorization[7:]
        _purge_expired()
        if not validate_session(token):
            raise HTTPException(status_code=401, detail="Invalid or expired session")


admin_guard = AdminGuard()
