"""Unit tests for Job Discovery, Multi-Platform Scraping & Relevance Harness."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from jobflow.api.app import app
from jobflow.config import settings
from jobflow.core.schema import MasterProfile, ContactInfo, WorkExperience, Education, SkillCategory, JobListing, PlatformType
from jobflow.core.security import create_session_token
from jobflow.core.job_discovery_harness import (
    ProfileQuerySynthesizer,
    JobRelevanceEvaluator,
    JobDiscoveryHarness
)
from jobflow.db.database import init_db, async_session
from jobflow.db.profile_repo import get_active_profile


def get_auth_client():
    token = create_session_token("admin")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {token}"},
        cookies={settings.SESSION_COOKIE_NAME: token},
        follow_redirects=True
    )


@pytest.fixture
def sample_profile() -> MasterProfile:
    return MasterProfile(
        contact=ContactInfo(
            full_name="Alex Mercer",
            email="alex@example.com",
            phone="+62 812 3456 7890",
            location="Jakarta, Indonesia",
            linkedin_url="https://linkedin.com/in/alexmercer",
            github_url="https://github.com/alexmercer"
        ),
        summary="Senior AI & Machine Learning Engineer with 6+ years specializing in Python, FastAPI, PyTorch, LLMs, and distributed backend architectures.",
        experience=[
            WorkExperience(
                company="Nexus AI Corp",
                position="Lead AI Engineer",
                start_date="2022",
                end_date="Present",
                location="Jakarta, Indonesia",
                technologies=["Python", "FastAPI", "PyTorch", "Docker", "PostgreSQL", "LangChain"],
                highlights=["Designed autonomous agent workflows and high-throughput microservices."]
            ),
            WorkExperience(
                company="DataVibe Inc",
                position="Backend Software Engineer",
                start_date="2019",
                end_date="2022",
                location="Bandung, Indonesia",
                technologies=["Python", "Django", "Redis", "Kafka", "AWS"],
                highlights=["Scaled REST and gRPC services to 50k RPS."]
            )
        ],
        skills=[
            SkillCategory(category="Languages", skills=["Python", "SQL", "Go", "JavaScript"]),
            SkillCategory(category="Frameworks & AI", skills=["FastAPI", "PyTorch", "Docker", "LangChain", "Kubernetes"])
        ],
        education=[
            Education(
                institution="Bandung Institute of Technology",
                degree="B.S.",
                field_of_study="Computer Science",
                start_date="2015",
                end_date="2019"
            )
        ]
    )


def test_profile_query_synthesizer(sample_profile):
    criteria = ProfileQuerySynthesizer.extract_search_criteria(sample_profile)
    assert criteria["candidate_name"] == "Alex Mercer"
    assert "Lead AI Engineer" in criteria["target_roles"] or "AI Engineer" in criteria["target_roles"][0]
    assert "Python" in criteria["core_skills"]
    assert "FastAPI" in criteria["core_skills"]
    assert criteria["seniority_level"] in ["Senior", "Lead", "Principal"]
    assert len(criteria["search_queries"]) > 0


def test_relevance_evaluator_positive(sample_profile):
    evaluator = JobRelevanceEvaluator(sample_profile)
    relevant_job = JobListing(
        title="Senior Python / AI Engineer",
        company="Global Tech Systems",
        location="Remote / Jakarta",
        platform=PlatformType.LINKEDIN,
        url="https://linkedin.com/jobs/view/9991",
        description="We are seeking a Senior AI Engineer skilled in Python, FastAPI, PyTorch, and Docker microservices to lead LLM pipeline architecture.",
        requirements=["Python", "FastAPI", "PyTorch", "Docker", "PostgreSQL"]
    )

    evaluation = evaluator.evaluate(relevant_job, min_threshold=60.0)
    assert evaluation.is_relevant is True
    assert evaluation.relevance_score >= 65.0
    assert evaluation.breakdown["domain_match"] > 0
    assert evaluation.breakdown["tech_stack_score"] > 0
    assert "Python" in evaluation.matched_skills or "FastAPI" in evaluation.matched_skills


def test_relevance_evaluator_negative_guard(sample_profile):
    evaluator = JobRelevanceEvaluator(sample_profile)
    irrelevant_job = JobListing(
        title="Senior Corporate Accountant & Tax Auditor",
        company="Big 4 Advisory",
        location="Jakarta",
        platform=PlatformType.JOBSTREET,
        url="https://jobstreet.com/job/8888",
        description="Manage financial bookkeeping, corporate tax returns, balance sheets, and statutory auditing. CPA preferred.",
        requirements=["Accounting", "Tax", "CPA", "SAP", "Excel"]
    )

    evaluation = evaluator.evaluate(irrelevant_job, min_threshold=60.0)
    assert evaluation.is_relevant is False
    assert evaluation.relevance_score < 40.0
    assert len(evaluation.disqualification_reasons) > 0


def test_relevance_evaluator_sales_role(sample_profile):
    evaluator = JobRelevanceEvaluator(sample_profile)
    sales_job = JobListing(
        title="B2B Enterprise Sales Account Executive",
        company="FastCloud Software",
        location="Remote",
        platform=PlatformType.REMOTEOK,
        url="https://remoteok.com/job/7777",
        description="Drive enterprise software outbound sales quotas, cold calling, and contract closings.",
        requirements=["B2B Sales", "Cold Calling", "CRM", "Pipeline Management"]
    )

    evaluation = evaluator.evaluate(sales_job, min_threshold=60.0)
    assert evaluation.is_relevant is False
    assert evaluation.relevance_score < 40.0


@pytest.mark.asyncio
async def test_job_discovery_harness_end_to_end(sample_profile):
    import uuid
    await init_db()
    uid = uuid.uuid4().hex[:6]
    unique_company = f"MockTech AI Labs {uid}"
    unique_url = f"https://remoteok.com/j/mock-ai-{uid}"

    async with async_session() as session:
        harness = JobDiscoveryHarness(master_profile=sample_profile, db=session)

        # Mock scraped job items
        mock_jobs = [
            JobListing(
                title="Staff AI Backend Engineer",
                company=unique_company,
                location="Remote",
                platform=PlatformType.REMOTEOK,
                url=unique_url,
                description="Looking for an AI engineer proficient with Python, FastAPI, Docker, and LLMs.",
                requirements=["Python", "FastAPI", "Docker"]
            ),
            JobListing(
                title="Senior Graphic Designer",
                company=f"Design Studio {uid}",
                location="Jakarta",
                platform=PlatformType.GLINTS,
                url=f"https://glints.com/j/mock-design-{uid}",
                description="Create Figma illustrations, banners, and vector assets for marketing.",
                requirements=["Figma", "Illustrator", "Photoshop"]
            )
        ]

        logs = []
        def log_cb(msg, level="info"):
            logs.append((level, msg))

        # First run: should persist the relevant job
        with patch("jobflow.extractors.platform_scrapers.MultiPlatformJobScraper.search_across_platforms", new=AsyncMock(return_value=mock_jobs)):
            result = await harness.execute_discovery(
                platforms=["remoteok", "glints"],
                min_relevance=60.0,
                max_jobs_to_save=5,
                progress_callback=log_cb
            )

            assert result["status"] == "ok"
            assert result["total_found"] == 2
            assert result["total_relevant"] >= 1
            assert result["total_rejected"] >= 1
            assert len(result["saved_jobs"]) >= 1
            assert result["saved_jobs"][0]["company"] == unique_company
            assert len(logs) > 0

        # Second run with same jobs: should be deduplicated (saved_jobs is 0)
        with patch("jobflow.extractors.platform_scrapers.MultiPlatformJobScraper.search_across_platforms", new=AsyncMock(return_value=mock_jobs)):
            result_dedup = await harness.execute_discovery(
                platforms=["remoteok", "glints"],
                min_relevance=60.0,
                max_jobs_to_save=5
            )
            assert result_dedup["status"] == "ok"
            assert len(result_dedup["saved_jobs"]) == 0
            assert any("Deduplicated" in l[1] for l in logs) or result_dedup["persisted_count"] == 0


@pytest.mark.asyncio
async def test_discovery_api_preview_endpoint():
    await init_db()
    async with get_auth_client() as ac:
        res = await ac.get("/api/jobs/auto-discover/preview-queries")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "criteria" in data
        criteria = data["criteria"]
        assert "target_roles" in criteria
        assert "core_skills" in criteria


@pytest.mark.asyncio
async def test_discovery_api_auto_discover_endpoint():
    import uuid
    await init_db()
    uid = uuid.uuid4().hex[:6]
    unique_company = f"Autonomous Intelligence {uid}"
    unique_url = f"https://linkedin.com/jobs/view/test-auto-discover-{uid}"

    async with get_auth_client() as ac:
        mock_jobs = [
            JobListing(
                title="Lead Python AI Specialist",
                company=unique_company,
                location="Remote",
                platform=PlatformType.LINKEDIN,
                url=unique_url,
                description="Lead development of autonomous Python FastAPI and Docker AI systems.",
                requirements=["Python", "FastAPI", "Docker"]
            )
        ]

        with patch("jobflow.extractors.platform_scrapers.MultiPlatformJobScraper.search_across_platforms", new=AsyncMock(return_value=mock_jobs)):
            res = await ac.post("/api/jobs/auto-discover", json={
                "platforms": ["linkedin"],
                "min_relevance": 50.0,
                "max_jobs": 3
            })
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "ok"
            assert data["total_found"] == 1
            assert data["total_relevant"] == 1
            assert len(data["saved_jobs"]) == 1
            assert data["saved_jobs"][0]["company"] == unique_company
