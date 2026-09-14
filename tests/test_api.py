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
        assert "Senior AI Systems Architect" in res_prev.text or "WORK EXPERIENCE" in res_prev.text

        # 5. Check download endpoint
        res_pdf = await ac.get(f"/api/resume/download/{job_id}")
        assert res_pdf.status_code == 200
        assert res_pdf.headers["content-type"] == "application/pdf"
