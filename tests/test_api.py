import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from jobflow.api.app import app
from jobflow.config import settings
from jobflow.core.security import create_session_token
from jobflow.db.database import init_db


def get_auth_client(follow_redirects: bool = True):
    token = create_session_token("admin")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {token}"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        follow_redirects=follow_redirects
    )


@pytest.mark.asyncio
async def test_health_and_dashboard_endpoints():
    await init_db()
    async with get_auth_client() as ac:
        res = await ac.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "healthy", "service": "jobflow-ai"}

        res_dash = await ac.get("/")
        assert res_dash.status_code == 200
        assert "JobFlow AI" in res_dash.text


@pytest.mark.asyncio
async def test_job_and_resume_flow():
    await init_db()
    async with get_auth_client() as ac:
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
        assert "AI-Tailored & ATS-Optimized Document" in res_prev_hl.text
        assert "Role-Adapted" in res_prev_hl.text or "Google X-Y-Z" in res_prev_hl.text

        # 7. Check highlighted PDF download endpoint
        res_pdf_hl = await ac.get(f"/api/resume/download/{job_id}?highlight=true")
        assert res_pdf_hl.status_code == 200
        assert res_pdf_hl.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_candidate_profile_persistence_in_db():
    await init_db()
    async with get_auth_client() as ac:
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


@pytest.mark.asyncio
async def test_get_job_by_id_endpoint():
    await init_db()
    async with get_auth_client() as ac:
        job_data = {
            "title": "Staff Cloud Engineer",
            "company": "CloudScape Global",
            "location": "Jakarta, Indonesia",
            "url": "https://www.linkedin.com/jobs/view/9988776655",
            "platform": "linkedin",
            "description": "Architecting resilient Kubernetes microservices.",
            "requirements": ["Kubernetes", "AWS", "Terraform", "Go"]
        }
        res_create = await ac.post("/api/jobs", json=job_data)
        assert res_create.status_code == 200
        job_id = res_create.json()["id"]

        # 1. Fetch valid job details
        res_get = await ac.get(f"/api/jobs/{job_id}")
        assert res_get.status_code == 200
        data = res_get.json()
        assert data["id"] == job_id
        assert data["title"] == "Staff Cloud Engineer"
        assert data["company"] == "CloudScape Global"
        assert data["url"] == "https://www.linkedin.com/jobs/view/9988776655"
        assert data["platform"] == "linkedin"
        assert "Kubernetes" in data["requirements"]
        assert data["has_resume"] is False

        # 2. Fetch nonexistent job ID returns 404
        res_404 = await ac.get("/api/jobs/9999999")
        assert res_404.status_code == 404
        assert res_404.json()["detail"] == "Job not found"

