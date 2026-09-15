"""Repository for managing candidate master profile persistence in the database."""

import os
import json
import logging
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from jobflow.db.models import CandidateProfileRecord, utc_now
from jobflow.core.schema import MasterProfile
from jobflow.config import settings

logger = logging.getLogger("jobflow.db.profile_repo")


async def get_active_profile(session: AsyncSession) -> Optional[MasterProfile]:
    """Retrieve the active candidate master profile from the database.
    
    If the database table has no profile yet but the fallback master_profile.json
    file exists on disk, it automatically seeds the database with that profile.
    """
    try:
        stmt = (
            select(CandidateProfileRecord)
            .where(CandidateProfileRecord.is_active == 1)
            .order_by(CandidateProfileRecord.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        record = result.scalars().first()

        if record:
            return record.to_master_profile()

        # Auto-seed from master_profile.json if database table is empty
        if os.path.exists(settings.MASTER_PROFILE_PATH):
            try:
                with open(settings.MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    profile = MasterProfile(**data)
                    logger.info("Auto-seeding candidate profile into database from master_profile.json...")
                    await save_active_profile(session, profile)
                    return profile
            except Exception as seed_err:
                logger.warning(f"Could not auto-seed profile from disk: {seed_err}")

        return None
    except Exception as e:
        logger.error(f"Error querying active profile from database: {e}", exc_info=True)
        # Fallback to disk if DB query fails
        if os.path.exists(settings.MASTER_PROFILE_PATH):
            try:
                with open(settings.MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
                    return MasterProfile(**json.load(f))
            except Exception:
                pass
        return None


async def save_active_profile(session: AsyncSession, profile: MasterProfile) -> CandidateProfileRecord:
    """Save or update the active candidate profile in the database.
    
    Also synchronizes the disk master_profile.json cache for fallback compatibility.
    """
    stmt = (
        select(CandidateProfileRecord)
        .where(CandidateProfileRecord.is_active == 1)
        .order_by(CandidateProfileRecord.updated_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    record = result.scalars().first()

    profile_dict = profile.model_dump()

    if record:
        record.full_name = profile.contact.full_name
        record.email = profile.contact.email
        record.phone = profile.contact.phone
        record.location = profile.contact.location
        record.linkedin_url = profile.contact.linkedin_url
        record.github_url = profile.contact.github_url
        record.portfolio_url = profile.contact.portfolio_url
        record.summary = profile.summary
        record.skills = [s.model_dump() for s in profile.skills]
        record.experience = [e.model_dump() for e in profile.experience]
        record.education = [ed.model_dump() for ed in profile.education]
        record.projects = [p.model_dump() for p in profile.projects]
        record.certifications = profile.certifications
        record.custom_sections = [cs.model_dump() for cs in profile.custom_sections]
        record.common_answers = profile.common_answers
        record.style_preferences = profile.style_preferences.model_dump() if profile.style_preferences else {}
        record.raw_cv_text = profile.raw_cv_text
        record.profile_data = profile_dict
        record.updated_at = utc_now()
    else:
        record = CandidateProfileRecord(
            is_active=1,
            full_name=profile.contact.full_name,
            email=profile.contact.email,
            phone=profile.contact.phone,
            location=profile.contact.location,
            linkedin_url=profile.contact.linkedin_url,
            github_url=profile.contact.github_url,
            portfolio_url=profile.contact.portfolio_url,
            summary=profile.summary,
            skills=[s.model_dump() for s in profile.skills],
            experience=[e.model_dump() for e in profile.experience],
            education=[ed.model_dump() for ed in profile.education],
            projects=[p.model_dump() for p in profile.projects],
            certifications=profile.certifications,
            custom_sections=[cs.model_dump() for cs in profile.custom_sections],
            common_answers=profile.common_answers,
            style_preferences=profile.style_preferences.model_dump() if profile.style_preferences else {},
            raw_cv_text=profile.raw_cv_text,
            profile_data=profile_dict,
            created_at=utc_now(),
            updated_at=utc_now()
        )
        session.add(record)

    await session.commit()
    await session.refresh(record)

    # Sync disk cache for fallback compatibility
    try:
        with open(settings.MASTER_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(profile_dict, f, indent=2)
    except Exception as disk_err:
        logger.warning(f"Could not update disk cache master_profile.json: {disk_err}")

    return record
