"""Public Developer API Suite (v1).

Exposes core JobFlow AI engines (Resume Tailoring, ATS Scorer, CV Parser,
Job Extractor, Auto-Discovery, Application Pipeline) for external applications.
"""

import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobflow.db.database import get_db
from jobflow.db.models import JobApplicationRecord
from jobflow.db.profile_repo import get_active_profile, save_active_profile
from jobflow.core.schema import (
    MasterProfile, JobListing, TailoredResume, ApplicationStatus
)
from jobflow.core.cv_parser import extract_text_from_file, CVParserAgent
from jobflow.core.ats_scorer import ATSScorer
from jobflow.core.agent_harness import AIAgentHarness
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.core.storage_cleaner import delete_job_files
from jobflow.core.job_discovery_harness import JobDiscoveryHarness
from jobflow.extractors.platform_extractors import PlatformExtractor
from jobflow.automations.applier import apply_worker
from jobflow.api.deps import require_developer_auth

router = APIRouter(
    prefix="/api/v1",
    tags=["Developer API v1"],
    dependencies=[Depends(require_developer_auth)]
)


# ==========================================
# 1. RESUME & ATS TAILORING ENGINE
# ==========================================

class TailorResumeRequest(BaseModel):
    job_title: str = Field(..., description="Target position title")
    company: str = Field(default="Target Company", description="Hiring company name")
    job_description: str = Field(..., description="Job posting description and responsibilities")
    requirements: Optional[List[str]] = Field(default=None, description="Explicit requirement keywords")
    custom_profile: Optional[dict] = Field(default=None, description="Optional profile override instead of active profile")


class AtsScoreRequest(BaseModel):
    job_description: str = Field(..., description="Target job description")
    resume_text: Optional[str] = Field(default=None, description="Raw resume text to evaluate")
    requirements: Optional[List[str]] = Field(default=None, description="Target job keywords")


@router.post("/resume/tailor", response_model=TailoredResume)
async def tailor_resume(req: TailorResumeRequest, db: AsyncSession = Depends(get_db)):
    """Tailor candidate CV for a specific job posting using the AI tailoring harness."""
    if req.custom_profile:
        profile = MasterProfile(**req.custom_profile)
    else:
        profile = await get_active_profile(db)

    if not profile:
        raise HTTPException(
            status_code=400,
            detail="No candidate profile found. Please upload a CV first or pass 'custom_profile'."
        )

    job = JobListing(
        title=req.job_title,
        company=req.company,
        description=req.job_description,
        requirements=req.requirements or []
    )

    harness = AIAgentHarness(master_profile=profile)
    tailored = await harness.tailor_for_job(job)
    return tailored


@router.post("/resume/generate-pdf")
async def generate_resume_pdf(
    tailored_resume: TailoredResume,
    highlight: bool = False
):
    """Generate high-fidelity format-conforming ATS CV PDF bytes directly from tailored data."""
    generator = PDFGenerator()
    html_content = generator.render_html(tailored_resume, highlight=highlight)
    pdf_bytes = generator.render_pdf_from_html(html_content)

    filename = f"ATS_Resume_{tailored_resume.contact.full_name.replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )


@router.post("/ats/score", response_model=dict)
async def calculate_ats_score(req: AtsScoreRequest, db: AsyncSession = Depends(get_db)):
    """Standalone ATS match evaluator between a job description and candidate resume."""
    if req.resume_text:
        res_text = req.resume_text
    else:
        profile = await get_active_profile(db)
        if not profile:
            raise HTTPException(status_code=400, detail="No resume text or active profile provided")
        res_text = profile.raw_cv_text or profile.summary

    scorer = ATSScorer()
    score_result = scorer.calculate_score(
        resume_text=res_text,
        job_description=req.job_description,
        required_keywords=req.requirements
    )
    return score_result


# ==========================================
# 2. JOB INGESTION & PIPELINE
# ==========================================

class ExtractJobRequest(BaseModel):
    url: str = Field(..., description="Web URL of job posting (LinkedIn, JobStreet, Glints, etc.)")


class CreateJobRequest(BaseModel):
    title: str
    company: str
    location: Optional[str] = "Remote / Hybrid"
    platform: Optional[str] = "generic"
    url: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[List[str]] = None


class AutoDiscoverApiRequest(BaseModel):
    platforms: Optional[List[str]] = Field(default=None, description="Platforms to query (jobstreet, linkedin, glints, remoteok)")
    min_relevance: float = Field(default=60.0, ge=0.0, le=100.0)
    max_jobs: int = Field(default=8, ge=1, le=25)
    custom_queries: Optional[List[str]] = None
    location: Optional[str] = None


@router.post("/jobs/extract", response_model=JobListing)
async def extract_job_from_url(req: ExtractJobRequest):
    """Extract clean, structured job metadata from an external job listing URL."""
    try:
        extractor = PlatformExtractor()
        job = await extractor.extract(req.url)
        return job
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract job from URL: {str(e)}")


@router.get("/jobs", response_model=List[dict])
async def list_jobs(
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all tracked job applications in the pipeline with optional status filtering."""
    stmt = select(JobApplicationRecord).order_by(JobApplicationRecord.created_at.desc())
    if status_filter:
        stmt = stmt.where(JobApplicationRecord.status == status_filter)

    result = await db.execute(stmt)
    records = result.scalars().all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "company": r.company,
            "location": r.location,
            "platform": r.platform,
            "url": r.url,
            "ats_score": r.ats_score,
            "status": r.status,
            "has_resume": bool(r.resume_pdf_path),
            "created_at": r.created_at.isoformat() if r.created_at else None
        }
        for r in records
    ]


@router.post("/jobs", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_job_target(job: CreateJobRequest, db: AsyncSession = Depends(get_db)):
    """Add a new job application target into the JobFlow pipeline."""
    record = JobApplicationRecord(
        title=job.title,
        company=job.company,
        location=job.location or "Remote / Hybrid",
        platform=job.platform or "generic",
        url=job.url,
        description=job.description,
        requirements=job.requirements or []
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "message": "Job application created successfully"}


@router.get("/jobs/{job_id}", response_model=dict)
async def get_job_details(job_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch complete metadata and requirements for a specific job."""
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": record.id,
        "title": record.title,
        "company": record.company,
        "location": record.location,
        "platform": record.platform,
        "url": record.url,
        "description": record.description,
        "requirements": record.requirements or [],
        "ats_score": record.ats_score,
        "status": record.status,
        "has_resume": bool(record.resume_pdf_path),
        "created_at": record.created_at.isoformat() if record.created_at else None
    }


@router.delete("/jobs/{job_id}", response_model=dict)
async def delete_job_target(job_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a job application and delete its physical output files."""
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    delete_job_files(job_id, record.resume_pdf_path)
    await db.delete(record)
    await db.commit()
    return {"message": "Job and associated artifacts deleted successfully", "id": job_id}


@router.post("/jobs/auto-discover", response_model=dict)
async def auto_discover_jobs(
    req: AutoDiscoverApiRequest,
    db: AsyncSession = Depends(get_db)
):
    """Execute multi-platform job harvesting and AI relevance evaluation."""
    profile = await get_active_profile(db)
    if not profile:
        raise HTTPException(status_code=400, detail="Active candidate profile required for auto-discovery")

    harness = JobDiscoveryHarness(
        master_profile=profile,
        db=db,
        min_relevance_threshold=req.min_relevance
    )

    result = await harness.discover_and_evaluate(
        platforms=req.platforms,
        max_jobs=req.max_jobs,
        custom_queries=req.custom_queries,
        location=req.location
    )
    return result


# ==========================================
# 3. CV PARSING & PROFILE
# ==========================================

class ParseRawTextRequest(BaseModel):
    raw_text: str = Field(..., min_length=20, description="Raw unformatted text of resume")


@router.post("/cv/parse-text", response_model=MasterProfile)
async def parse_cv_text(req: ParseRawTextRequest):
    """Parse unformatted plain text into a structured candidate profile."""
    agent = CVParserAgent()
    profile = await agent.parse_cv(req.raw_text)
    return profile


@router.post("/cv/upload", response_model=MasterProfile)
async def upload_cv_document(file: UploadFile = File(...)):
    """Upload PDF, DOCX, or TXT file and extract structured candidate profile."""
    content = await file.read()
    raw_text = extract_text_from_file(file.filename, content)
    agent = CVParserAgent()
    profile = await agent.parse_cv(raw_text)
    return profile


@router.get("/profile", response_model=MasterProfile)
async def get_candidate_profile(db: AsyncSession = Depends(get_db)):
    """Get the active candidate master profile."""
    profile = await get_active_profile(db)
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found")
    return profile


@router.post("/profile", response_model=MasterProfile)
async def update_candidate_profile(
    profile: MasterProfile,
    db: AsyncSession = Depends(get_db)
):
    """Update or overwrite the active candidate master profile."""
    await save_active_profile(db, profile)
    return profile


# ==========================================
# 4. PLAYWRIGHT AUTOMATION RUNNER
# ==========================================

@router.post("/apply/execute/{job_id}", response_model=dict)
async def execute_automated_application(
    job_id: int,
    headless: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Dispatch background Playwright browser automation to apply for a job."""
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = await get_active_profile(db)
    if not profile:
        raise HTTPException(status_code=400, detail="Active profile required for auto-apply")

    import asyncio
    asyncio.create_task(apply_worker(job_id=job_id, headless=headless))
    return {"status": "dispatched", "job_id": job_id, "message": "Automation worker running in background"}


@router.get("/apply/status/{job_id}", response_model=dict)
async def get_application_status(job_id: int, db: AsyncSession = Depends(get_db)):
    """Poll live execution status, application logs, and screenshot path."""
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": record.id,
        "status": record.status,
        "logs": record.logs or [],
        "has_screenshot": bool(record.screenshot_path),
        "applied_at": record.applied_at.isoformat() if record.applied_at else None
    }
