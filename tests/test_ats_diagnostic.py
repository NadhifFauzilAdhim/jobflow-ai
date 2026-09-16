"""Unit and integration tests for the ATS Resume Diagnostic Engine and Interactive Improvement System."""

import pytest
from httpx import AsyncClient, ASGITransport
from jobflow.api.app import app
from jobflow.core.schema import (
    TailoredResume,
    ContactInfo,
    SkillCategory,
    WorkExperience,
    Education,
    Project,
    CustomSection,
    CustomSectionItem,
    JobListing,
    PlatformType
)
from jobflow.core.ats_diagnostic import ATSResumeDiagnostic
from jobflow.core.agent_harness import AIAgentHarness


def create_sample_unquantified_resume() -> TailoredResume:
    return TailoredResume(
        contact=ContactInfo(
            full_name="Budi Santoso",
            email="budi.santoso@example.com",
            phone="+62 812 3456 7890",
            location="Jakarta, Indonesia"
        ),
        summary="experienced developer specializing in web backend architecture and distributed systems",
        skills=[SkillCategory(category="Technical Skills", skills=["Python", "PostgreSQL", "Docker"])],
        experience=[
            WorkExperience(
                company="PT Inovasi Digital",
                position="Software Engineer",
                start_date="2022",
                end_date="Present",
                highlights=[
                    "built backend payment processing service  for enterprise clients",
                    "built asynchronous notification queue consuming Kafka events",
                    "managed deployment pipelines using Docker"
                ],
                technologies=["Python", "PostgreSQL"]
            )
        ],
        education=[
            Education(
                institution="Universitas Indonesia",
                degree="Sarjana Ilmu Komputer",
                field_of_study="Computer Science",
                start_date="2018",
                end_date="2022",
                highlights=["Relevant coursework: Database Systems, Algorithms"]
            )
        ],
        projects=[
            Project(
                name="PayFlow Gateway",
                description="Financial transaction gateway.",
                technologies=["Python", "FastAPI", "PostgreSQL"],
                highlights=[
                    "developed transactional ledger service",
                    "developed integration with multiple bank APIs"
                ]
            )
        ],
        custom_sections=[
            CustomSection(
                id="organisasi",
                heading="Pengalaman Organisasi",
                items=[
                    CustomSectionItem(
                        title="Ketua Divisi IT",
                        subtitle="Himpunan Mahasiswa",
                        date_or_year="2021",
                        bullets=["memimpin workshop coding untuk mahasiswa baru"]
                    )
                ]
            )
        ],
        job_title_target="Senior Backend Engineer",
        target_company="Global FinTech Corp"
    )


def test_ats_diagnostic_detects_deficiencies():
    resume = create_sample_unquantified_resume()
    job = JobListing(
        title="Senior Backend Engineer",
        company="Global FinTech Corp",
        description="Looking for Senior Backend Engineer with Python, PostgreSQL, and microservices experience.",
        requirements=["Python", "PostgreSQL", "Kafka", "Docker"]
    )

    diagnostic = ATSResumeDiagnostic()
    report = diagnostic.analyze_resume(resume, job)

    # 1. Overall & Content score should reflect unquantified state
    assert report.content_score < 80.0
    assert len(report.issues) > 0

    # 2. Check Quantifying Impact issues
    qi_issues = [i for i in report.issues if i.category == "quantifying_impact"]
    assert len(qi_issues) >= 3  # Experience bullets & project bullets lack numbers
    assert any("PT Inovasi Digital" in (i.section_name or "") for i in qi_issues)
    assert any(i.needs_user_context for i in qi_issues)
    assert any(i.context_field_id.startswith("ctx_exp_") for i in qi_issues)

    # 3. Check Repetition issues (both "built" and "developed" are repeated)
    rep_issues = [i for i in report.issues if i.category == "repetition"]
    assert len(rep_issues) >= 1
    assert any("built" in i.title.lower() or "developed" in i.title.lower() for i in rep_issues)

    # 4. Check Spelling & Grammar / Formatting issues
    sg_issues = [i for i in report.issues if i.category == "spelling_grammar"]
    assert len(sg_issues) >= 1  # summary starts lowercase, double spaces, lowercase bullets

    # 5. Check Categories breakdown
    cat_names = [c.name for c in report.categories]
    assert "ATS Parse Rate" in cat_names
    assert "Quantifying Impact" in cat_names
    assert "Repetition & Action Verbs" in cat_names
    assert "Spelling & Formatting Quality" in cat_names
    assert "Bullets Consistency & Length" in cat_names
    assert "Sections Completeness" in cat_names


def test_ats_diagnostic_clean_resume_scores_optimal():
    clean_resume = TailoredResume(
        contact=ContactInfo(
            full_name="Budi Santoso",
            email="budi.santoso@example.com",
            phone="+62 812 3456 7890",
            location="Jakarta, Indonesia"
        ),
        summary="Senior Backend Engineer with 5+ years of experience architecting resilient financial microservices and scalable cloud systems.",
        skills=[SkillCategory(category="Technical Skills", skills=["Python", "PostgreSQL", "Docker", "Kafka"])],
        experience=[
            WorkExperience(
                company="PT Inovasi Digital",
                position="Software Engineer",
                start_date="2022",
                end_date="Present",
                highlights=[
                    "Architected high-throughput payment processing engine handling 120k daily transactions with 99.99% uptime.",
                    "Engineered asynchronous event bus in Kafka cutting end-to-end processing latency by 45%.",
                    "Orchestrated containerized microservices deployments with Docker, boosting deployment frequency by 3x."
                ],
                technologies=["Python", "PostgreSQL", "Docker", "Kafka"]
            )
        ],
        education=[
            Education(
                institution="Universitas Indonesia",
                degree="Sarjana Ilmu Komputer",
                field_of_study="Computer Science",
                start_date="2018",
                end_date="2022",
                highlights=["Relevant coursework: Distributed Systems, Database Architecture (GPA: 3.85)."]
            )
        ],
        projects=[
            Project(
                name="PayFlow Gateway",
                description="Enterprise financial transaction system.",
                technologies=["Python", "FastAPI", "PostgreSQL"],
                highlights=[
                    "Developed double-entry transactional ledger achieving sub-50ms p95 latency under 10k rps.",
                    "Spearheaded direct core banking API integrations reducing transaction settlement time by 60%."
                ]
            )
        ],
        job_title_target="Senior Backend Engineer",
        target_company="Global FinTech Corp"
    )

    job = JobListing(
        title="Senior Backend Engineer",
        company="Global FinTech Corp",
        description="Python, PostgreSQL, and Kafka backend systems.",
        requirements=["Python", "PostgreSQL", "Kafka"]
    )

    diagnostic = ATSResumeDiagnostic()
    report = diagnostic.analyze_resume(clean_resume, job)

    assert report.content_score >= 88.0
    assert report.sections_score >= 95.0
    assert report.parse_rate_score == 100.0
    # No quantifying impact issues
    assert len([i for i in report.issues if i.category == "quantifying_impact"]) == 0


@pytest.mark.asyncio
async def test_improve_resume_with_user_context():
    resume = create_sample_unquantified_resume()
    job = JobListing(
        title="Senior Backend Engineer",
        company="Global FinTech Corp",
        description="Looking for Senior Backend Engineer with Python and PostgreSQL.",
        requirements=["Python", "PostgreSQL"]
    )

    harness = AIAgentHarness(master_profile=resume)

    # Candidate provides context for the first experience bullet and first project bullet
    user_context = {
        "ctx_exp_0_bullet_0": "memproses 150k transaksi harian dengan uptime 99.95%",
        "ctx_proj_0_bullet_0": "mencapai latensi p95 35ms dengan 5k rps"
    }

    improved = await harness.improve_resume_with_context(
        tailored=resume,
        job=job,
        user_context=user_context,
        auto_estimate_missing=True
    )

    # 1. Candidate's exact metrics should be woven into the highlights
    exp_hl = improved.experience[0].highlights[0]
    assert "150k transaksi" in exp_hl or "99.95%" in exp_hl

    proj_hl = improved.projects[0].highlights[0]
    assert "35ms" in proj_hl or "5k rps" in proj_hl

    # 2. Capitalization and period ending
    assert exp_hl[0].isupper()
    assert exp_hl.endswith(".")
    assert proj_hl[0].isupper()
    assert proj_hl.endswith(".")

    # 3. Re-run diagnostic on improved resume: Content score should substantially improve
    diagnostic = ATSResumeDiagnostic()
    report_improved = diagnostic.analyze_resume(improved, job)
    assert report_improved.content_score > 80.0
    assert len(report_improved.context_required_issues) == 0


@pytest.mark.asyncio
async def test_api_audit_and_improve_endpoints():
    from jobflow.db.database import init_db
    from jobflow.config import settings
    from jobflow.core.security import create_session_token

    await init_db()
    token = create_session_token("admin")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {token}"},
        cookies={settings.SESSION_COOKIE_NAME: token}
    ) as ac:
        # Check active jobs first
        jobs_res = await ac.get("/api/jobs")
        assert jobs_res.status_code == 200
        jobs = jobs_res.json()
        if not jobs:
            pytest.skip("No job records in database to test audit endpoint")

        # Select a job that has resume or tailor it
        job_id = jobs[0]["id"]
        if not jobs[0].get("has_resume"):
            tailor_res = await ac.post(f"/api/resume/tailor/{job_id}")
            assert tailor_res.status_code == 200

        # Test Audit Endpoint
        audit_res = await ac.get(f"/api/resume/audit/{job_id}")
        assert audit_res.status_code == 200
        audit_data = audit_res.json()

        assert "overall_score" in audit_data
        assert "content_score" in audit_data
        assert "categories" in audit_data
        assert "issues" in audit_data
        assert len(audit_data["categories"]) >= 5

        # Test Improve Endpoint with user context
        user_context = {}
        if audit_data.get("context_required_issues"):
            first_field = audit_data["context_required_issues"][0].get("context_field_id")
            if first_field:
                user_context[first_field] = "100k transaksi harian, latensi turun 40%"

        improve_res = await ac.post(
            f"/api/resume/improve/{job_id}",
            json={
                "user_context": user_context,
                "auto_estimate_missing": True
            }
        )
        assert improve_res.status_code == 200
        improve_data = improve_res.json()
        assert "tailored_resume" in improve_data
        assert "diagnostic_report" in improve_data
        assert "content_score" in improve_data

