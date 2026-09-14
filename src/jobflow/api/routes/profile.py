"""Master profile API routes."""

import json
from fastapi import APIRouter, HTTPException
from jobflow.core.schema import MasterProfile
from jobflow.config import settings

router = APIRouter(prefix="/api/profile", tags=["Profile"])


@router.get("", response_model=MasterProfile)
async def get_profile():
    import os
    if not os.path.exists(settings.MASTER_PROFILE_PATH):
        raise HTTPException(status_code=404, detail="Master profile not found")
    with open(settings.MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return MasterProfile(**data)


@router.post("", response_model=MasterProfile)
async def save_profile(profile: MasterProfile):
    with open(settings.MASTER_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile.model_dump(), f, indent=2)
    return profile
