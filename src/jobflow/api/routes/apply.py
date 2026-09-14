"""Job application execution API routes."""

from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from jobflow.db.database import get_db, async_session
from jobflow.db.models import JobApplicationRecord
from jobflow.core.schema import JobListing, MasterProfile, PlatformType, ApplicationStatus
from jobflow.automations.applier import JobApplier
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.config import settings
import json
import logging

logger = logging.getLogger("jobflow.apply_route")
router = APIRouter(prefix="/api/apply", tags=["Application"])


async def run_application_background(job_id: int):
    """Background task runner for executing browser application."""
    async with async_session() as db:
        record = await db.get(JobApplicationRecord, job_id)
        if not record:
            return

        record.status = ApplicationStatus.APPLYING.value
        record.logs = [{"time": datetime.utcnow().isoformat(), "msg": "Starting application automation worker...", "level": "info"}]
        await db.commit()

        def log_cb(msg: str, level: str = "info"):
            current_logs = list(record.logs or [])
            current_logs.append({"time": datetime.utcnow().isoformat(), "msg": msg, "level": level})
            record.logs = current_logs

        try:
            # Ensure resume exists
            if not record.resume_pdf_path or not Path(record.resume_pdf_path).exists():
                log_cb("Generating tailored resume before applying...")
                engine = ResumeEngine()
                job_schema = JobListing(
                    id=str(record.id),
                    title=record.title,
                    company=record.company,
                    url=record.url,
                    description=record.description or "",
                    requirements=record.requirements or []
                )
                tailored = await engine.tailor_resume(job_schema)
                generator = PDFGenerator()
                pdf_name = f"resume_{record.id}_{record.company.lower().replace(' ', '_')}.pdf"
                pdf_path = await generator.generate_pdf(tailored, output_filename=pdf_name)
                record.resume_pdf_path = str(pdf_path)
                record.tailored_resume_data = tailored.model_dump()
                record.ats_score = tailored.ats_score

            with open(settings.MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
                profile = MasterProfile(**json.load(f))

            applier = JobApplier(profile)
            job_listing = JobListing(
                id=str(record.id),
                title=record.title,
                company=record.company,
                url=record.url,
                platform=PlatformType(record.platform) if record.platform in PlatformType._value2member_map_ else PlatformType.GENERIC,
                description=record.description or ""
            )

            result = await applier.apply_to_job(
                job=job_listing,
                resume_pdf_path=Path(record.resume_pdf_path),
                log_callback=log_cb
            )

            record.status = result.get("status", ApplicationStatus.FAILED).value if hasattr(result.get("status"), "value") else str(result.get("status"))
            record.screenshot_path = result.get("screenshot")
            if record.status == ApplicationStatus.APPLIED.value:
                record.applied_at = datetime.utcnow()

        except Exception as e:
            log_cb(f"Fatal application error: {str(e)}", "error")
            record.status = ApplicationStatus.FAILED.value

        await db.commit()


@router.post("/execute/{job_id}")
async def execute_application(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    background_tasks.add_task(run_application_background, job_id)
    return {"message": "Application task queued in background", "job_id": job_id}


@router.get("/status/{job_id}")
async def get_application_status(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": record.id,
        "title": record.title,
        "company": record.company,
        "status": record.status,
        "ats_score": record.ats_score,
        "logs": record.logs or [],
        "has_screenshot": bool(record.screenshot_path and Path(record.screenshot_path).exists()),
        "applied_at": record.applied_at.isoformat() if record.applied_at else None
    }


@router.get("/screenshot/{job_id}")
async def get_screenshot(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record or not record.screenshot_path or not Path(record.screenshot_path).exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(path=record.screenshot_path, media_type="image/png")
