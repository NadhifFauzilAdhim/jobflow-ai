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
