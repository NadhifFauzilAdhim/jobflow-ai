"""Resume generation and ATS evaluation API routes."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from jobflow.db.database import get_db
from jobflow.db.models import JobApplicationRecord
from jobflow.core.schema import JobListing, TailoredResume, ATSAnalysisResult, PlatformType
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.core.ats_scorer import evaluate_ats

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

    engine = ResumeEngine()
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
async def download_resume_pdf(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.resume_pdf_path:
        raise HTTPException(status_code=404, detail="Resume PDF not found for this job")
    
    file_path = Path(record.resume_pdf_path)
    if not file_path.exists():
        # Re-generate on the fly
        if record.tailored_resume_data:
            tailored = TailoredResume(**record.tailored_resume_data)
            generator = PDFGenerator()
            file_path = await generator.generate_pdf(tailored, output_filename=file_path.name)
        else:
            raise HTTPException(status_code=404, detail="PDF file does not exist on disk")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/pdf"
    )


@router.get("/preview/{job_id}", response_class=HTMLResponse)
async def preview_resume_html(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.tailored_resume_data:
        raise HTTPException(status_code=404, detail="Tailored resume data not found")
    
    tailored = TailoredResume(**record.tailored_resume_data)
    generator = PDFGenerator()
    return generator.render_html(tailored)
