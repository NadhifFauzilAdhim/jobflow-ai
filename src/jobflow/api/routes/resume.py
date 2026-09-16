"""Resume generation and ATS evaluation API routes."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from jobflow.db.database import get_db
from jobflow.db.models import JobApplicationRecord
from jobflow.core.schema import (
    JobListing,
    TailoredResume,
    ATSAnalysisResult,
    PlatformType,
    ATSDiagnosticReport,
    ResumeImprovementRequest,
)
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.core.ats_scorer import evaluate_ats
from jobflow.core.ats_diagnostic import ATSResumeDiagnostic
from jobflow.core.agent_harness import AIAgentHarness
from jobflow.db.profile_repo import get_active_profile

router = APIRouter(prefix="/api/resume", tags=["Resume"])


@router.post("/tailor/{job_id}", response_model=TailoredResume)
async def tailor_resume_for_job(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job record not found")

    job = JobListing(
        id=str(record.id),
        title=record.title,
        company=record.company,
        location=record.location,
        url=record.url,
        platform=PlatformType(record.platform) if record.platform in PlatformType._value2member_map_ else PlatformType.GENERIC,
        description=record.description or "",
        requirements=record.requirements or []
    )

    active_profile = await get_active_profile(db)
    engine = ResumeEngine(master_profile=active_profile)
    tailored = await engine.tailor_resume(job)

    # Generate PDF
    generator = PDFGenerator()
    pdf_name = f"resume_{record.id}_{record.company.lower().replace(' ', '_')}.pdf"
    pdf_path = await generator.generate_pdf(tailored, output_filename=pdf_name)

    # Update DB record
    record.ats_score = tailored.ats_score
    record.matched_keywords = tailored.matching_keywords
    record.missing_keywords = tailored.missing_keywords
    record.tailored_resume_data = tailored.model_dump()
    record.resume_pdf_path = str(pdf_path)
    record.status = "ready_to_apply"

    await db.commit()
    await db.refresh(record)

    return tailored


@router.get("/download/{job_id}")
async def download_resume_pdf(job_id: int, highlight: bool = False, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.tailored_resume_data:
        raise HTTPException(status_code=404, detail="Tailored resume data not found for this job")
    
    tailored = TailoredResume(**record.tailored_resume_data)
    generator = PDFGenerator()

    if highlight:
        highlighted_filename = f"resume_{record.id}_{record.company.lower().replace(' ', '_')}_highlighted.pdf"
        file_path = await generator.generate_pdf(tailored, output_filename=highlighted_filename, show_highlights=True)
    else:
        file_path = Path(record.resume_pdf_path) if record.resume_pdf_path else None
        if not file_path or not file_path.exists():
            clean_filename = f"resume_{record.id}_{record.company.lower().replace(' ', '_')}.pdf"
            file_path = await generator.generate_pdf(tailored, output_filename=clean_filename, show_highlights=False)
            record.resume_pdf_path = str(file_path)
            await db.commit()

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/pdf"
    )


@router.get("/preview/{job_id}", response_class=HTMLResponse)
async def preview_resume_html(job_id: int, highlight: bool = False, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.tailored_resume_data:
        raise HTTPException(status_code=404, detail="Tailored resume data not found")
    
    tailored = TailoredResume(**record.tailored_resume_data)
    generator = PDFGenerator()
    return generator.render_html(tailored, show_highlights=highlight)


@router.get("/details/{job_id}", response_model=TailoredResume)
async def get_tailored_resume_details(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.tailored_resume_data:
        raise HTTPException(status_code=404, detail="Tailored resume data not found")
    return TailoredResume(**record.tailored_resume_data)


@router.get("/audit/{job_id}", response_model=ATSDiagnosticReport)
async def audit_resume_ats(job_id: int, db: AsyncSession = Depends(get_db)):
    """Run in-depth ATS diagnostic checking Quantifying Impact, Repetition, Grammar, Consistency, and Sections."""
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.tailored_resume_data:
        raise HTTPException(status_code=404, detail="Tailored resume data not found for this job")

    tailored = TailoredResume(**record.tailored_resume_data)
    job = JobListing(
        id=str(record.id),
        title=record.title,
        company=record.company,
        location=record.location,
        url=record.url,
        platform=PlatformType(record.platform) if record.platform in PlatformType._value2member_map_ else PlatformType.GENERIC,
        description=record.description or "",
        requirements=record.requirements or []
    )

    diagnostic = ATSResumeDiagnostic()
    report = diagnostic.analyze_resume(tailored, job)
    return report


@router.post("/improve/{job_id}")
async def improve_resume_with_context(
    job_id: int,
    req: ResumeImprovementRequest,
    db: AsyncSession = Depends(get_db)
):
    """Improve resume by resolving ATS deficiencies and integrating candidate context answers."""
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.tailored_resume_data:
        raise HTTPException(status_code=404, detail="Tailored resume data not found for this job")

    tailored = TailoredResume(**record.tailored_resume_data)
    job = JobListing(
        id=str(record.id),
        title=record.title,
        company=record.company,
        location=record.location,
        url=record.url,
        platform=PlatformType(record.platform) if record.platform in PlatformType._value2member_map_ else PlatformType.GENERIC,
        description=record.description or "",
        requirements=record.requirements or []
    )

    active_profile = await get_active_profile(db)
    harness = AIAgentHarness(master_profile=active_profile)
    improved = await harness.improve_resume_with_context(
        tailored=tailored,
        job=job,
        user_context=req.user_context,
        auto_estimate_missing=req.auto_estimate_missing
    )

    # Regenerate PDF
    generator = PDFGenerator()
    pdf_name = f"resume_{record.id}_{record.company.lower().replace(' ', '_')}.pdf"
    pdf_path = await generator.generate_pdf(improved, output_filename=pdf_name)

    # Also generate highlighted PDF for preview toggle
    highlighted_pdf_name = f"resume_{record.id}_{record.company.lower().replace(' ', '_')}_highlighted.pdf"
    await generator.generate_pdf(improved, output_filename=highlighted_pdf_name, show_highlights=True)

    # Run fresh diagnostic on improved resume
    diagnostic = ATSResumeDiagnostic()
    report = diagnostic.analyze_resume(improved, job)

    # Update DB record
    record.ats_score = improved.ats_score
    record.matched_keywords = improved.matching_keywords
    record.missing_keywords = improved.missing_keywords
    record.tailored_resume_data = improved.model_dump()
    record.resume_pdf_path = str(pdf_path)

    await db.commit()
    await db.refresh(record)

    return {
        "tailored_resume": improved.model_dump(),
        "diagnostic_report": report.model_dump(),
        "ats_score": improved.ats_score,
        "content_score": report.content_score
    }

