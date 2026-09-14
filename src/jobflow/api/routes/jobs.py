"""Job listings API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from pydantic import BaseModel
from jobflow.db.database import get_db
from jobflow.db.models import JobApplicationRecord
from jobflow.core.schema import JobListing, PlatformType
from jobflow.extractors.platform_extractors import get_job_extractor

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


class ExtractJobRequest(BaseModel):
    url: Optional[str] = None
    raw_text: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None


@router.post("/extract", response_model=JobListing)
async def extract_job(req: ExtractJobRequest):
    if req.url:
        extractor = get_job_extractor(req.url)
        try:
            return await extractor.extract_from_url(req.url)
        except Exception as e:
            # Fallback to text parsing
            if req.raw_text:
                return extractor.extract_from_raw_text(req.raw_text, title=req.title, company=req.company, url=req.url)
            raise HTTPException(status_code=400, detail=f"Failed to fetch job URL: {str(e)}")
    elif req.raw_text:
        extractor = get_job_extractor("generic")
        return extractor.extract_from_raw_text(req.raw_text, title=req.title, company=req.company)
    else:
        raise HTTPException(status_code=400, detail="Provide either url or raw_text")


@router.get("", response_model=List[dict])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobApplicationRecord).order_by(JobApplicationRecord.id.desc()))
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
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "has_resume": bool(r.resume_pdf_path)
        }
        for r in records
    ]


@router.post("", response_model=dict)
async def create_job(job: JobListing, db: AsyncSession = Depends(get_db)):
    record = JobApplicationRecord(
        title=job.title,
        company=job.company,
        location=job.location or "Remote / Hybrid",
        platform=job.platform.value if hasattr(job.platform, "value") else str(job.platform),
        url=str(job.url) if job.url else None,
        description=job.description,
        requirements=job.requirements
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "message": "Job created successfully"}


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete(record)
    await db.commit()
    return {"message": "Job deleted successfully"}
