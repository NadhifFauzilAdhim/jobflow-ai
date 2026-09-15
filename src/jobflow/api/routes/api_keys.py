"""API Key Management Routes."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobflow.db.database import get_db
from jobflow.db.models import ApiKeyRecord
from jobflow.core.security import generate_api_key

router = APIRouter(prefix="/api/auth/api-keys", tags=["API Keys"])


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Application or integration name")
    scopes: Optional[List[str]] = Field(default=["*"], description="Allowed API scopes")


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class CreatedApiKeyResponse(ApiKeyResponse):
    key: str = Field(..., description="Full secret API Key string (shown only once upon creation)")


@router.get("", response_model=List[ApiKeyResponse])
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    """List all registered API keys (secrets are hidden, only prefixes are displayed)."""
    stmt = select(ApiKeyRecord).order_by(ApiKeyRecord.created_at.desc())
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [r.to_dict() for r in records]


@router.post("", response_model=CreatedApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_new_api_key(
    req: CreateApiKeyRequest,
    db: AsyncSession = Depends(get_db)
):
    """Generate a new secure API key with the given application name."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Key name cannot be empty")

    raw_key, key_prefix, key_hash = generate_api_key()

    record = ApiKeyRecord(
        name=name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=req.scopes or ["*"],
        is_active=1
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    data = record.to_dict()
    data["key"] = raw_key
    return data


@router.delete("/{key_id}", response_model=dict)
async def revoke_api_key(key_id: int, db: AsyncSession = Depends(get_db)):
    """Revoke and permanently deactivate an API key."""
    record = await db.get(ApiKeyRecord, key_id)
    if not record:
        raise HTTPException(status_code=404, detail="API Key not found")

    record.is_active = 0
    await db.commit()
    return {"message": f"API Key '{record.name}' successfully revoked", "id": key_id}
