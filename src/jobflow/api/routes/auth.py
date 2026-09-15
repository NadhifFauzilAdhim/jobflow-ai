"""Authentication routes for JobFlow AI."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Response, Request, Form
from pydantic import BaseModel
from jobflow.config import settings
from jobflow.core.security import (
    verify_credentials,
    create_session_token,
    get_authenticated_user,
)

logger = logging.getLogger("jobflow.api.auth")
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = True


@router.post("/login")
async def login(request: Request, response: Response):
    """Authenticate user credentials and establish an HTTP-only signed session."""
    content_type = request.headers.get("content-type", "")
    user = ""
    pwd = ""
    remember = True

    if "application/json" in content_type:
        try:
            body = await request.json()
            user = (body.get("username") or "").strip()
            pwd = body.get("password") or ""
            remember = body.get("remember_me", True)
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            user = (form.get("username") or "").strip()
            pwd = form.get("password") or ""
            remember = form.get("remember_me") not in [False, "false", "0", None]
        except Exception:
            pass

    if not verify_credentials(user, pwd):
        logger.warning(f"Failed login attempt for username: {user}")
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password. Please verify your credentials."
        )

    expires_hours = settings.SESSION_EXPIRE_HOURS if remember else 24
    token = create_session_token(user, expires_hours=expires_hours)
    max_age = expires_hours * 3600

    # Set secure HTTP-only cookie
    is_secure = (request.url.scheme == "https")
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/"
    )

    logger.info(f"User '{user}' successfully logged in.")
    return {
        "status": "ok",
        "message": "Login successful",
        "username": user,
        "token": token
    }


@router.get("/logout")
@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie and invalidate active session."""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax"
    )
    return {"status": "ok", "message": "Successfully logged out"}


@router.get("/me")
async def get_current_user(request: Request):
    """Get active session authentication status."""
    username = get_authenticated_user(request)
    return {
        "authenticated": bool(username),
        "username": username,
        "auth_enabled": settings.AUTH_ENABLED
    }
