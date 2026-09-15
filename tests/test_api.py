import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from jobflow.api.app import app
from jobflow.db.database import init_db


@pytest.mark.asyncio
async def test_health_and_dashboard_endpoints():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "healthy", "service": "jobflow-ai"}

        res_dash = await ac.get("/")
        assert res_dash.status_code == 200
        assert "JobFlow AI" in res_dash.text


@pytest.mark.asyncio
async def test_job_and_resume_flow():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create a job
        job_data = {
            "title": "Senior AI Systems Architect",
            "company": "NextGen AI Labs",
            "description": "Building high-performance Python FastAPI and Playwright automation engines.",
            "requirements": ["Python", "FastAPI", "Docker", "Playwright", "LLMs"],
            "platform": "generic"
        }
        res = await ac.post("/api/jobs", json=job_data)
        assert res.status_code == 200
        job_id = res.json()["id"]

        # 2. List jobs
        res_list = await ac.get("/api/jobs")
        assert res_list.status_code == 200
        jobs = res_list.json()
        assert any(j["id"] == job_id for j in jobs)

        # 3. Tailor resume for the job
        res_tailor = await ac.post(f"/api/resume/tailor/{job_id}")
        assert res_tailor.status_code == 200
        tailored_data = res_tailor.json()
        assert tailored_data["ats_score"] > 0
        assert len(tailored_data["matching_keywords"]) > 0

        # 4. Preview HTML
        res_prev = await ac.get(f"/api/resume/preview/{job_id}")
        assert res_prev.status_code == 200
        assert "Work Experience" in res_prev.text or "WORK EXPERIENCE" in res_prev.text.upper()

        # 5. Check download endpoint
        res_pdf = await ac.get(f"/api/resume/download/{job_id}")
        assert res_pdf.status_code == 200
        assert res_pdf.headers["content-type"] == "application/pdf"

        # 6. Preview HTML with AI Highlights
        res_prev_hl = await ac.get(f"/api/resume/preview/{job_id}?highlight=true")
        assert res_prev_hl.status_code == 200
        assert "AI TAILORING IMPROVEMENTS" in res_prev_hl.text
        assert "AI-Adapted" in res_prev_hl.text or "Google X-Y-Z" in res_prev_hl.text

        # 7. Check highlighted PDF download endpoint
        res_pdf_hl = await ac.get(f"/api/resume/download/{job_id}?highlight=true")
        assert res_pdf_hl.status_code == 200
        assert res_pdf_hl.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_candidate_profile_persistence_in_db():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Check profile status endpoint
        res_status = await ac.get("/api/profile/status")
        assert res_status.status_code == 200
        status_data = res_status.json()
        assert status_data["loaded"] is True
        assert status_data["persisted_in_db"] is True
        assert "name" in status_data

        # 2. Get active profile from database
        res_prof = await ac.get("/api/profile")
        assert res_prof.status_code == 200
        profile_data = res_prof.json()
        assert profile_data["contact"]["full_name"] != ""

        # 3. Modify summary and save
        original_summary = profile_data.get("summary", "")
        profile_data["summary"] = f"{original_summary} (Updated for Persistence Test)"
        res_save = await ac.post("/api/profile", json=profile_data)
        assert res_save.status_code == 200
        assert res_save.json()["summary"] == profile_data["summary"]

        # 4. Verify that fetching again returns the newly persisted summary
        res_verify = await ac.get("/api/profile")
        assert res_verify.status_code == 200
        assert res_verify.json()["summary"] == profile_data["summary"]

        # 5. Restore original summary
        profile_data["summary"] = original_summary
        await ac.post("/api/profile", json=profile_data)

