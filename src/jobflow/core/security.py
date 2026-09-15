"""Security and session management utilities for JobFlow AI."""

import hmac
import hashlib
import base64
import json
import time
import logging
from typing import Optional
from fastapi import Request
from jobflow.config import settings

logger = logging.getLogger("jobflow.security")


def _b64_encode(data: bytes) -> str:
    """Encode bytes to url-safe base64 without trailing '=' padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_decode(data_str: str) -> bytes:
    """Decode url-safe base64 with flexible padding."""
    padding = 4 - (len(data_str) % 4)
    if padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str.encode("utf-8"))


def create_session_token(username: str, expires_hours: Optional[int] = None) -> str:
    """Create a tamper-proof HMAC-SHA256 signed session token."""
    ttl = (expires_hours or settings.SESSION_EXPIRE_HOURS) * 3600
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + ttl
    }
    payload_json = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    payload_b64 = _b64_encode(payload_json)

    secret = settings.SECRET_KEY.encode("utf-8")
    sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str) -> Optional[str]:
    """Verify session token signature and expiration. Returns username if valid, else None."""
    if not token or "." not in token:
        return None

    parts = token.split(".")
    if len(parts) != 2:
        return None

    payload_b64, sig = parts
    secret = settings.SECRET_KEY.encode("utf-8")
    expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload_bytes = _b64_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = payload.get("exp", 0)
        if time.time() > exp:
            return None
        return payload.get("sub")
    except Exception as e:
        logger.debug(f"Token decoding error: {e}")
        return None


def verify_credentials(username: str, password: str) -> bool:
    """Verify credentials using constant-time string comparison."""
    if not username or not password:
        return False
    user_ok = hmac.compare_digest(username.strip(), settings.AUTH_USERNAME.strip())
    pass_ok = hmac.compare_digest(password.strip(), settings.AUTH_PASSWORD.strip())
    return user_ok and pass_ok


def get_authenticated_user(request: Request) -> Optional[str]:
    """Extract and verify authenticated username from session cookie or Bearer authorization header."""
    if not settings.AUTH_ENABLED:
        return "admin"

    # 1. Check HTTP-only session cookie
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)

    # 2. Check Authorization Bearer header fallback
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        return verify_session_token(token)

    return None
