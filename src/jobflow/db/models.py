"""Database Models for JobFlow AI."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Enum as SQLEnum, JSON
from sqlalchemy.orm import declarative_base
from jobflow.core.schema import ApplicationStatus, PlatformType

Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc)


class JobApplicationRecord(Base):
    __tablename__ = "job_applications"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    location = Column(String(255), default="Remote / Hybrid")
    platform = Column(String(50), default="generic")
    url = Column(String(1024), nullable=True)
    description = Column(Text, nullable=True)
    requirements = Column(JSON, default=list)
    
    # Resume & ATS data
    ats_score = Column(Float, default=0.0)
    matched_keywords = Column(JSON, default=list)
    missing_keywords = Column(JSON, default=list)
    tailored_resume_data = Column(JSON, nullable=True)
    resume_pdf_path = Column(String(512), nullable=True)
    
    # Status & Application flow
    status = Column(String(50), default=ApplicationStatus.SAVED.value)
    logs = Column(JSON, default=list)
    screenshot_path = Column(String(512), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class CandidateProfileRecord(Base):
    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True, index=True)
    is_active = Column(Integer, default=1, index=True)
    full_name = Column(String(255), nullable=False, default="")
    email = Column(String(255), nullable=True, default="")
    phone = Column(String(100), nullable=True, default="")
    location = Column(String(255), nullable=True, default="")
    linkedin_url = Column(String(512), nullable=True, default="")
    github_url = Column(String(512), nullable=True, default="")
    portfolio_url = Column(String(512), nullable=True, default="")
    summary = Column(Text, nullable=True, default="")
    
    # Structured CV Sections (JSON)
    skills = Column(JSON, default=list)
    experience = Column(JSON, default=list)
    education = Column(JSON, default=list)
    projects = Column(JSON, default=list)
    certifications = Column(JSON, default=list)
    custom_sections = Column(JSON, default=list)
    common_answers = Column(JSON, default=dict)
    style_preferences = Column(JSON, default=dict)
    raw_cv_text = Column(Text, nullable=True, default="")
    
    # Full MasterProfile JSON snapshot
    profile_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def to_master_profile(self):
        from jobflow.core.schema import MasterProfile
        if self.profile_data and isinstance(self.profile_data, dict):
            try:
                return MasterProfile(**self.profile_data)
            except Exception:
                pass
        
        # Fallback reconstruction from column values
        from jobflow.core.schema import (
            ContactInfo, SkillCategory, WorkExperience, Education, Project,
            CustomSection, StylePreferences
        )
        return MasterProfile(
            contact=ContactInfo(
                full_name=self.full_name or "Candidate",
                email=self.email or "",
                phone=self.phone or "",
                location=self.location or "",
                linkedin_url=self.linkedin_url or "",
                github_url=self.github_url or "",
                portfolio_url=self.portfolio_url or ""
            ),
            summary=self.summary or "",
            skills=[SkillCategory(**s) if isinstance(s, dict) else s for s in (self.skills or [])],
            experience=[WorkExperience(**e) if isinstance(e, dict) else e for e in (self.experience or [])],
            education=[Education(**ed) if isinstance(ed, dict) else ed for ed in (self.education or [])],
            projects=[Project(**p) if isinstance(p, dict) else p for p in (self.projects or [])],
            certifications=self.certifications or [],
            custom_sections=[CustomSection(**cs) if isinstance(cs, dict) else cs for cs in (self.custom_sections or [])],
            common_answers=self.common_answers or {},
            style_preferences=StylePreferences(**self.style_preferences) if isinstance(self.style_preferences, dict) else StylePreferences(),
            raw_cv_text=self.raw_cv_text or ""
        )


class ApiKeyRecord(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    key_prefix = Column(String(32), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False, index=True)
    scopes = Column(JSON, default=lambda: ["*"])
    is_active = Column(Integer, default=1, index=True)
    created_at = Column(DateTime, default=utc_now)
    last_used_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "scopes": self.scopes or ["*"],
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }


