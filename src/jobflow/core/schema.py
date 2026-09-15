"""Pydantic schemas for JobFlow AI core data structures."""

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, HttpUrl
from enum import Enum


class PlatformType(str, Enum):
    LINKEDIN = "linkedin"
    JOBSTREET = "jobstreet"
    GLINTS = "glints"
    INDEED = "indeed"
    GENERIC = "generic"


class ApplicationStatus(str, Enum):
    SAVED = "saved"
    TAILORING_RESUME = "tailoring_resume"
    READY_TO_APPLY = "ready_to_apply"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"


class ContactInfo(BaseModel):
    full_name: str
    email: str
    phone: str
    location: str
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None


class WorkExperience(BaseModel):
    company: str
    position: str
    location: Optional[str] = ""
    start_date: str
    end_date: Optional[str] = "Present"
    highlights: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str
    field_of_study: str
    start_date: str
    end_date: str
    gpa: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str
    technologies: List[str] = Field(default_factory=list)
    link: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class SkillCategory(BaseModel):
    category: str
    skills: List[str]


class QAPair(BaseModel):
    """Pre-configured answers for common application questions."""
    question_pattern: str  # regex or keyword, e.g. "salary", "notice period", "citizenship"
    answer: str


class StylePreferences(BaseModel):
    section_order: List[str] = Field(
        default_factory=lambda: ["summary", "skills", "experience", "education", "projects", "certifications"]
    )
    layout_style: str = "modern_clean"  # modern_clean, classic_executive, compact_tech
    accent_color: str = "#111827"
    font_family: str = "Helvetica Neue, Helvetica, Arial, sans-serif"
    bullet_style: str = "bullet"


class CustomSectionItem(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    date_or_year: Optional[str] = None
    description: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)


class CustomSection(BaseModel):
    id: str
    heading: str
    items: List[CustomSectionItem] = Field(default_factory=list)


class MasterProfile(BaseModel):
    contact: ContactInfo
    summary: str
    skills: List[SkillCategory]
    experience: List[WorkExperience]
    education: List[Education]
    projects: List[Project] = Field(default_factory=list)
    certifications: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    custom_sections: List[CustomSection] = Field(default_factory=list)
    common_answers: List[QAPair] = Field(default_factory=list)
    style_preferences: Optional[StylePreferences] = Field(default_factory=StylePreferences)
    raw_cv_text: Optional[str] = None


class JobListing(BaseModel):
    id: Optional[str] = None
    title: str
    company: str
    location: Optional[str] = "Remote / Hybrid"
    url: Optional[str] = None
    platform: PlatformType = PlatformType.GENERIC
    description: str
    requirements: List[str] = Field(default_factory=list)
    salary_range: Optional[str] = None
    posted_date: Optional[str] = None


class TailoredResume(BaseModel):
    contact: ContactInfo
    summary: str
    skills: List[SkillCategory]
    experience: List[WorkExperience]
    education: List[Education]
    projects: List[Project] = Field(default_factory=list)
    certifications: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    custom_sections: List[CustomSection] = Field(default_factory=list)
    job_title_target: str
    target_company: str
    ats_score: float = 0.0
    matching_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    tailoring_notes: Optional[str] = None
    style_preferences: Optional[StylePreferences] = Field(default_factory=StylePreferences)
    agent_reasoning: Optional[str] = None
    key_strengths: List[str] = Field(default_factory=list)
    interview_talking_points: List[str] = Field(default_factory=list)
    job_fit_summary: Optional[Dict[str, Any]] = None


class ATSAnalysisResult(BaseModel):
    score: float
    matched_keywords: List[str]
    missing_keywords: List[str]
    suggestions: List[str]
