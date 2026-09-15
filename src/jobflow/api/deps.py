"""Reusable authentication & database dependencies for FastAPI routes."""

import logging
from typing import Optional
from fastapi import Request, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobflow.config import settings
from jobflow.db.database import get_db
from jobflow.db.models import ApiKeyRecord, utc_now
from jobflow.core.security import (
    get_authenticated_user,
    extract_api_key_from_request,
    hash_api_key
)

logger = logging.getLogger("jobflow.api.deps")

# OpenAPI Security Schemes for Swagger UI
api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, description="JobFlow AI API Key (jf_live_...)")
bearer_scheme = HTTPBearer(auto_error=False, description="Session Bearer token or API Key")


async def get_valid_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[ApiKeyRecord]:
    """Verify API Key if present in request and update last_used_at timestamp."""
    raw_key = extract_api_key_from_request(request)
    if not raw_key:
        return None

    key_hash = hash_api_key(raw_key)
    stmt = select(ApiKeyRecord).where(
        ApiKeyRecord.key_hash == key_hash,
        ApiKeyRecord.is_active == 1
    )
    result = await db.execute(stmt)
    record = result.scalars().first()

    if record:
        try:
            record.last_used_at = utc_now()
            await db.commit()
        except Exception as e:
            logger.debug(f"Could not update last_used_at for API key #{record.id}: {e}")
        return record

    return None


async def require_developer_auth(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Authentication dependency for Developer API (/api/v1/).
    
    Accepts:
    1. Valid API Key (X-API-Key or Bearer jf_live_...)
    2. Active Web Session (Cookie / Bearer Token from dashboard)
    3. If AUTH_ENABLED is False, permits access automatically.
    """
    if not settings.AUTH_ENABLED:
        return {"auth_type": "disabled", "user": "admin"}

    # 1. Check API Key
    api_key = await get_valid_api_key(request, db)
    if api_key:
        return {
            "auth_type": "api_key",
            "key_id": api_key.id,
            "key_name": api_key.name,
            "scopes": api_key.scopes or ["*"]
        }

    # 2. Check Dashboard Session / Bearer user
    user = get_authenticated_user(request)
    if user:
        return {
            "auth_type": "session",
            "user": user,
            "scopes": ["*"]
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Valid API Key (header X-API-Key: jf_live_...) or active session required.",
        headers={"WWW-Authenticate": "ApiKey"}
    )
