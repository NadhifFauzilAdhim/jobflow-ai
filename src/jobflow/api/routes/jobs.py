"""Job listings API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from pydantic import BaseModel
from jobflow.db.database import get_db
from jobflow.db.models import JobApplicationRecord
from jobflow.db.profile_repo import get_active_profile
from jobflow.core.schema import JobListing, PlatformType
from jobflow.core.job_discovery_harness import JobDiscoveryHarness, ProfileQuerySynthesizer
from jobflow.extractors.platform_extractors import get_job_extractor
from jobflow.core.storage_cleaner import (
    delete_job_files,
    cleanup_orphaned_output_files,
    purge_all_output_files,
    get_output_storage_stats
)

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


@router.get("/{job_id}", response_model=dict)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
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
        "applied_at": record.applied_at.isoformat() if record.applied_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "has_resume": bool(record.resume_pdf_path)
    }


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


class AutoDiscoverRequest(BaseModel):
    platforms: Optional[List[str]] = None
    min_relevance: float = 60.0
    max_jobs: int = 8
    custom_queries: Optional[List[str]] = None
    location: Optional[str] = None


@router.get("/auto-discover/preview-queries")
async def preview_discovery_queries(db: AsyncSession = Depends(get_db)):
    """Preview search criteria automatically synthesized from candidate CV."""
    profile = await get_active_profile(db)
    if not profile:
        raise HTTPException(status_code=404, detail="No active candidate profile found in database. Please upload CV first.")
    
    criteria = ProfileQuerySynthesizer.extract_search_criteria(profile)
    return {
        "status": "ok",
        "criteria": criteria
    }


@router.post("/auto-discover")
async def auto_discover_jobs(req: AutoDiscoverRequest, db: AsyncSession = Depends(get_db)):
    """Autonomous multi-platform job scraper and AI relevance evaluation harness."""
    profile = await get_active_profile(db)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Candidate CV profile not found. Please upload your CV first to establish ground truth."
        )

    harness = JobDiscoveryHarness(master_profile=profile, db=db)
    results = await harness.execute_discovery(
        platforms=req.platforms,
        min_relevance=req.min_relevance,
        max_jobs_to_save=req.max_jobs,
        custom_queries=req.custom_queries,
        location=req.location
    )
    return results


class StorageCleanupRequest(BaseModel):
    mode: str = "orphaned"  # "orphaned" or "all"


@router.get("/storage/stats")
async def get_storage_stats(db: AsyncSession = Depends(get_db)):
    """Get storage statistics for generated resumes, screenshots, and output directory."""
    result = await db.execute(select(JobApplicationRecord.id))
    active_ids = set(result.scalars().all())
    stats = get_output_storage_stats(active_ids)
    stats["active_jobs_count"] = len(active_ids)
    return stats


@router.post("/storage/cleanup")
async def cleanup_storage(req: StorageCleanupRequest, db: AsyncSession = Depends(get_db)):
    """Clean up output files (orphaned files only or complete purge)."""
    result = await db.execute(select(JobApplicationRecord.id))
    active_ids = set(result.scalars().all())

    if req.mode == "orphaned":
        res = cleanup_orphaned_output_files(active_ids)
        return {
            "status": "ok",
            "mode": "orphaned",
            "message": f"Cleaned up {res['deleted_count']} orphaned files ({res['bytes_freed_mb']} MB freed).",
            **res
        }
    elif req.mode == "all":
        res = purge_all_output_files()
        # Reset resume_pdf_path and status on all job records
        all_jobs_res = await db.execute(select(JobApplicationRecord))
        for j in all_jobs_res.scalars().all():
            j.resume_pdf_path = None
            j.status = "saved"
        await db.commit()
        return {
            "status": "ok",
            "mode": "all",
            "message": f"Purged all {res['deleted_count']} output files ({res['bytes_freed_mb']} MB freed).",
            **res
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid mode. Choose 'orphaned' or 'all'.")


@router.delete("/clear-all")
async def clear_all_jobs(delete_files: bool = True, db: AsyncSession = Depends(get_db)):
    """Clear all job applications and purge associated output files."""
    result = await db.execute(select(JobApplicationRecord))
    jobs = result.scalars().all()
    job_count = len(jobs)

    for j in jobs:
        await db.delete(j)
    await db.commit()

    deleted_files_count = 0
    if delete_files:
        res = purge_all_output_files()
        deleted_files_count = res["deleted_count"]

    return {
        "status": "ok",
        "deleted_jobs_count": job_count,
        "deleted_files_count": deleted_files_count,
        "message": f"Cleared {job_count} jobs and {deleted_files_count} output files."
    }


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    record = await db.get(JobApplicationRecord, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    deleted_files = delete_job_files(job_id, record.resume_pdf_path)
    await db.delete(record)
    await db.commit()
    return {
        "message": "Job deleted successfully",
        "deleted_files": deleted_files
    }
