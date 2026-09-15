"""Master profile and CV upload API routes with database persistence."""

import os
import json
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from jobflow.core.schema import MasterProfile
from jobflow.core.cv_parser import CVParserAgent, extract_text_from_file
from jobflow.config import settings
from jobflow.db.database import get_db
from jobflow.db.profile_repo import get_active_profile, save_active_profile

logger = logging.getLogger("jobflow.api.profile")
router = APIRouter(prefix="/api/profile", tags=["Profile"])


@router.get("", response_model=MasterProfile)
async def get_profile(db: AsyncSession = Depends(get_db)):
    """Retrieve currently active Master Profile from database."""
    profile = await get_active_profile(db)
    if not profile:
        raise HTTPException(status_code=404, detail="Master profile not found in database or disk cache")
    return profile


@router.post("", response_model=MasterProfile)
async def save_profile(profile: MasterProfile, db: AsyncSession = Depends(get_db)):
    """Update Master Profile directly and persist to database."""
    await save_active_profile(db, profile)
    return profile


@router.get("/status")
async def get_profile_status(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Get high-level summary of active candidate profile from database."""
    try:
        profile = await get_active_profile(db)
        if not profile:
            return {
                "loaded": False,
                "name": "None",
                "email": "",
                "experience_count": 0,
                "education_count": 0,
                "projects_count": 0,
                "skills_count": 0,
                "custom_sections_count": 0,
                "has_raw_cv": False,
                "persisted_in_db": False
            }

        all_skills = [s for cat in profile.skills for s in cat.skills]
        return {
            "loaded": True,
            "name": profile.contact.full_name,
            "email": profile.contact.email,
            "phone": profile.contact.phone,
            "location": profile.contact.location,
            "experience_count": len(profile.experience),
            "education_count": len(profile.education),
            "projects_count": len(profile.projects),
            "skills_count": len(all_skills),
            "custom_sections_count": len(profile.custom_sections),
            "has_raw_cv": bool(profile.raw_cv_text),
            "section_order": profile.style_preferences.section_order if profile.style_preferences else [],
            "persisted_in_db": True
        }
    except Exception as e:
        logger.error(f"Error fetching profile status: {e}", exc_info=True)
        return {"loaded": False, "error": str(e), "persisted_in_db": False}


@router.post("/upload-cv")
async def upload_cv(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload CV document (PDF, DOCX, TXT), extract content with AI Agent, and persist to database."""
    filename = file.filename or "uploaded_cv.pdf"
    lower_ext = os.path.splitext(filename)[1].lower()
    allowed_exts = [".pdf", ".docx", ".doc", ".txt", ".md"]

    if lower_ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{lower_ext}'. Please upload a PDF, DOCX, or TXT file."
        )

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Extract text
        raw_text = extract_text_from_file(filename, content)
        if not raw_text or not raw_text.strip():
            raise HTTPException(
                status_code=422,
                detail="Could not extract readable text from document. Ensure file is not password protected or corrupted."
            )

        # Parse with AI Agent
        agent = CVParserAgent()
        profile = await agent.parse_cv(raw_text)

        # Persist to Database & disk cache
        await save_active_profile(db, profile)

        return {
            "status": "success",
            "message": f"Successfully extracted, parsed, and persisted CV for {profile.contact.full_name}",
            "filename": filename,
            "profile": profile
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process uploaded CV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI Agent parsing failed: {str(e)}")


from pydantic import BaseModel

class RawTextPayload(BaseModel):
    raw_text: Optional[str] = None
    text: Optional[str] = None

    def get_content(self) -> str:
        return (self.raw_text or self.text or "").strip()


@router.post("/parse-text")
async def parse_raw_cv_text(payload: RawTextPayload, db: AsyncSession = Depends(get_db)):
    """Parse raw text directly with AI Agent and persist to database."""
    content = payload.get_content()
    if not content:
        raise HTTPException(status_code=400, detail="Raw CV text cannot be empty.")
    try:
        agent = CVParserAgent()
        profile = await agent.parse_cv(content)
        await save_active_profile(db, profile)
        return {
            "status": "success",
            "message": f"Successfully parsed and persisted CV text for {profile.contact.full_name}",
            "profile": profile
        }
    except Exception as e:
        logger.error(f"Error parsing raw text CV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

