"""Unit tests for Output Directory Cleanup & Storage Deletion Engine."""

import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from jobflow.api.app import app
from jobflow.config import settings, OUTPUT_DIR
from jobflow.core.security import create_session_token
from jobflow.db.database import init_db, async_session
from jobflow.db.models import JobApplicationRecord
from jobflow.core.storage_cleaner import (
    delete_job_files,
    cleanup_orphaned_output_files,
    purge_all_output_files,
    get_output_storage_stats
)


def get_auth_client():
    token = create_session_token("admin")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {token}"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        follow_redirects=True
    )


def test_delete_job_files():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    job_id = 999123

    # Create dummy artifacts
    pdf_normal = OUTPUT_DIR / f"resume_{job_id}_test_company.pdf"
    pdf_highlight = OUTPUT_DIR / f"resume_{job_id}_test_company_highlighted.pdf"
    screenshot_dir = OUTPUT_DIR / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = screenshot_dir / f"app_{job_id}.png"

    pdf_normal.write_text("dummy normal pdf")
    pdf_highlight.write_text("dummy highlight pdf")
    screenshot_file.write_text("dummy screenshot")

    assert pdf_normal.exists()
    assert pdf_highlight.exists()
    assert screenshot_file.exists()

    deleted = delete_job_files(job_id=job_id, resume_pdf_path=str(pdf_normal))
    assert len(deleted) >= 3
    assert not pdf_normal.exists()
    assert not pdf_highlight.exists()
    assert not screenshot_file.exists()


def test_cleanup_orphaned_output_files():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    active_id = 888123
    orphaned_id = 777123

    active_file = OUTPUT_DIR / f"resume_{active_id}_active.pdf"
    orphan_file = OUTPUT_DIR / f"resume_{orphaned_id}_orphan.pdf"
    test_artifact = OUTPUT_DIR / "test_temp_cleanup.pdf"

    active_file.write_text("active")
    orphan_file.write_text("orphan")
    test_artifact.write_text("temp test")

    res = cleanup_orphaned_output_files(active_job_ids={active_id})
    assert res["deleted_count"] >= 2
    assert not orphan_file.exists()
    assert not test_artifact.exists()
    assert active_file.exists()

    # Clean up active_file
    if active_file.exists():
        active_file.unlink()


def test_get_output_storage_stats():
    stats = get_output_storage_stats(active_job_ids={1, 2, 3})
    assert "total_files" in stats
    assert "total_bytes" in stats
    assert "total_size_mb" in stats
    assert "pdf_count" in stats
    assert "screenshot_count" in stats
    assert "orphaned_count" in stats


@pytest.mark.asyncio
async def test_api_storage_endpoints():
    await init_db()
    async with get_auth_client() as ac:
        # 1. Get stats
        res_stats = await ac.get("/api/jobs/storage/stats")
        assert res_stats.status_code == 200
        stats = res_stats.json()
        assert "total_files" in stats
        assert "active_jobs_count" in stats

        # 2. Cleanup orphaned
        res_cleanup = await ac.post("/api/jobs/storage/cleanup", json={"mode": "orphaned"})
        assert res_cleanup.status_code == 200
        assert res_cleanup.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_delete_job_api_removes_physical_files():
    await init_db()
    async with get_auth_client() as ac:
        # 1. Create a dummy job
        res_create = await ac.post("/api/jobs", json={
            "title": "Temporary Job for Deletion Test",
            "company": "Temp Delete Corp",
            "description": "Short-lived position to test physical file removal.",
            "platform": "generic"
        })
        assert res_create.status_code == 200
        job_id = res_create.json()["id"]

        # 2. Create physical dummy file
        pdf_path = OUTPUT_DIR / f"resume_{job_id}_temp_delete_corp.pdf"
        pdf_path.write_text("dummy resume content")
        assert pdf_path.exists()

        # Update record with resume_pdf_path
        async with async_session() as session:
            record = await session.get(JobApplicationRecord, job_id)
            if record:
                record.resume_pdf_path = str(pdf_path)
                await session.commit()

        # 3. Call DELETE /api/jobs/{job_id}
        res_delete = await ac.delete(f"/api/jobs/{job_id}")
        assert res_delete.status_code == 200
        data = res_delete.json()
        assert "deleted_files" in data
        assert not pdf_path.exists()
