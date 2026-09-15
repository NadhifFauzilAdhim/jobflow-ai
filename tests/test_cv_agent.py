import io
import pytest
from httpx import AsyncClient, ASGITransport
from jobflow.api.app import app
from jobflow.db.database import init_db
from jobflow.core.cv_parser import extract_text_from_file, CVParserAgent
from jobflow.core.schema import MasterProfile, ContactInfo, SkillCategory, WorkExperience, Education, StylePreferences, JobListing
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator


SAMPLE_CV_TEXT = """
Nadhif Fauzil Adhim
Email: nadhiffauzil@gmail.com
Phone: +62 812-3456-7890
Location: Indonesia
LinkedIn: linkedin.com/in/nadhiffauziladhim
GitHub: github.com/NadhifFauzilAdhim

SUMMARY
Lead AI and Full-Stack Software Engineer with 4+ years of experience designing scalable web architectures, automated AI pipelines, and computer vision systems.

TECHNICAL SKILLS
Python, FastAPI, TypeScript, React, Next.js, Docker, PostgreSQL, Redis, Playwright

WORK EXPERIENCE
Lead AI & Full Stack Engineer
NDF Project & AI Labs - Remote / Indonesia
2023 - Present
• Architected and deployed distributed AI pipelines and microservices serving 20k+ monthly active requests with 99.9% uptime.
• Engineered autonomous browser automation bots utilizing Playwright, cutting manual data entry workflows by 80%.

EDUCATION
Universitas Pembangunan Nasional Veteran Jawa Timur
Bachelor of Computer Science
2019 - 2023

PROJECTS
JobFlow AI
Autonomous Job Application Engine & ATS CV Generator built with Python and FastAPI.
• Implemented intelligent CV tailoring and automated job submission.
"""


def test_text_extraction_plain():
    content = SAMPLE_CV_TEXT.encode("utf-8")
    extracted = extract_text_from_file("my_resume.txt", content)
    assert "Nadhif Fauzil Adhim" in extracted
    assert "nadhiffauzil@gmail.com" in extracted


@pytest.mark.asyncio
async def test_cv_parser_agent_heuristic():
    agent = CVParserAgent()
    # Test heuristic fallback directly
    profile = agent._parse_heuristically(SAMPLE_CV_TEXT)
    assert profile.contact.full_name == "Nadhif Fauzil Adhim"
    assert profile.contact.email == "nadhiffauzil@gmail.com"
    assert len(profile.skills) > 0
    assert any("Python" in s for cat in profile.skills for s in cat.skills)
    assert len(profile.experience) > 0
    assert profile.style_preferences is not None
    assert "summary" in profile.style_preferences.section_order


@pytest.mark.asyncio
async def test_format_conforming_resume_engine():
    custom_profile = MasterProfile(
        contact=ContactInfo(
            full_name="Nadhif Fauzil Adhim",
            email="nadhiffauzil@gmail.com",
            phone="+62 812-3456-7890",
            location="Indonesia"
        ),
        summary="Experienced AI & Web Architect.",
        skills=[
            SkillCategory(category="Languages & Frameworks", skills=["Python", "FastAPI", "Docker", "Playwright"])
        ],
        experience=[
            WorkExperience(
                company="NDF Project",
                position="Lead AI Engineer",
                start_date="2023",
                end_date="Present",
                highlights=["Engineered autonomous agents cutting manual workflows by 80%"],
                technologies=["Python", "FastAPI"]
            )
        ],
        education=[
            Education(
                institution="UPN Veteran Jatim",
                degree="B.Sc. in CS",
                field_of_study="Computer Science",
                start_date="2019",
                end_date="2023"
            )
        ],
        style_preferences=StylePreferences(
            section_order=["skills", "experience", "education", "summary"],
            accent_color="#059669"
        )
    )

    job = JobListing(
        title="Senior Python Automation Engineer",
        company="Global Tech Corp",
        description="Looking for an engineer proficient in Python, FastAPI, and Playwright.",
        requirements=["Python", "FastAPI", "Playwright"]
    )

    engine = ResumeEngine(master_profile=custom_profile)
    tailored = await engine.tailor_resume(job)

    assert tailored.contact.full_name == "Nadhif Fauzil Adhim"
    assert tailored.ats_score > 0
    assert tailored.style_preferences.accent_color == "#059669"
    assert tailored.style_preferences.section_order[0] == "skills"
    assert tailored.agent_reasoning is not None

    # Test HTML rendering respects section ordering
    generator = PDFGenerator()
    html = generator.render_html(tailored)
    assert "Nadhif Fauzil Adhim" in html
    assert "#059669" in html
    # In section order, Technical Skills should come before Work Experience
    skills_idx = html.find("Technical Skills")
    exp_idx = html.find("Work Experience")
    assert skills_idx != -1
    assert exp_idx != -1
    assert skills_idx < exp_idx


@pytest.mark.asyncio
async def test_upload_cv_api_endpoint():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        files = {
            "file": ("test_resume.txt", io.BytesIO(SAMPLE_CV_TEXT.encode("utf-8")), "text/plain")
        }
        res = await ac.post("/api/profile/upload-cv", files=files)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "Nadhif Fauzil Adhim" in data["profile"]["contact"]["full_name"]

        # Check status endpoint
        status_res = await ac.get("/api/profile/status")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["loaded"] is True
        assert "Nadhif" in status_data["name"]


def test_schema_normalizer_resilience():
    from jobflow.core.agent_harness import SchemaNormalizer

    # Test nested envelope unwrap
    wrapped_data = {"master_profile": {"summary": "AI Engineer", "skills": []}}
    unwrapped = SchemaNormalizer.unwrap_root(wrapped_data)
    assert unwrapped["summary"] == "AI Engineer"

    # Test certification dictionary conversion
    dict_certs = [
        {"name": "Samsung Innovation Campus AI", "credential_id": "SIC-1234"},
        "AWS Certified Solutions Architect"
    ]
    normalized_certs = SchemaNormalizer.normalize_certifications(dict_certs)
    assert len(normalized_certs) == 2
    assert "Samsung Innovation Campus AI" in normalized_certs[0]
    assert normalized_certs[1] == "AWS Certified Solutions Architect"

    # Test flat skills normalization
    flat_skills = ["Python", "Docker", "FastAPI"]
    norm_skills = SchemaNormalizer.normalize_skills(flat_skills, [])
    assert len(norm_skills) == 1
    assert norm_skills[0].skills == ["Python", "Docker", "FastAPI"]


@pytest.mark.asyncio
async def test_parse_raw_text_api_endpoint():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {"raw_text": SAMPLE_CV_TEXT}
        res = await ac.post("/api/profile/parse-text", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        prof = data["profile"]
        assert "Nadhif" in prof["contact"]["full_name"]
        assert len(prof["education"]) >= 1
        assert "Universitas" in prof["education"][0]["institution"] or "UPN" in prof["education"][0]["institution"] or prof["education"][0]["degree"] != ""
        assert len(prof["projects"]) >= 1
        assert prof["projects"][0]["name"] != ""


@pytest.mark.asyncio
async def test_tailoring_preserves_candidate_education_and_projects():
    from jobflow.core.agent_harness import AIAgentHarness
    from jobflow.core.schema import Project

    custom_profile = MasterProfile(
        contact=ContactInfo(
            full_name="Nadhif Fauzil Adhim",
            email="nadhiffauzil@gmail.com",
            phone="+62 812-3456-7890",
            location="Surabaya, Indonesia"
        ),
        summary="Experienced AI Systems Developer",
        skills=[SkillCategory(category="Languages", skills=["Python", "Go", "TypeScript"])],
        experience=[
            WorkExperience(
                company="Tech Studio",
                position="Backend Engineer",
                start_date="2022",
                end_date="Present",
                highlights=["Engineered APIs"]
            )
        ],
        education=[
            Education(
                institution="Universitas Pembangunan Nasional Veteran Jawa Timur",
                degree="Bachelor of Computer Science",
                field_of_study="Informatics",
                start_date="2019",
                end_date="2023",
                gpa="3.85"
            )
        ],
        projects=[
            Project(
                name="JobFlow AI Engine",
                description="Autonomous application engine",
                technologies=["FastAPI", "Playwright"],
                highlights=["Cut manual application effort by 90%"]
            )
        ],
        certifications=["TensorFlow Developer Certificate"]
    )

    harness = AIAgentHarness(master_profile=custom_profile)
    job = JobListing(
        title="Full Stack AI Engineer",
        company="Innovative Tech Corp",
        description="Seeking an engineer skilled in Python and React to build AI agent workflows.",
        requirements=["Python", "React", "AI Agents"]
    )

    tailored = await harness.tailor_for_job(job)

    # Verify 100% preservation of authentic education
    assert len(tailored.education) == 1
    assert tailored.education[0].institution == "Universitas Pembangunan Nasional Veteran Jawa Timur"
    assert tailored.education[0].degree == "Bachelor of Computer Science"
    assert tailored.education[0].gpa == "3.85"

    # Verify 100% preservation of authentic projects
    assert len(tailored.projects) >= 1
    proj_names = [p.name for p in tailored.projects]
    assert "JobFlow AI Engine" in proj_names

    # Verify certifications preserved
    assert len(tailored.certifications) >= 1
    assert any("TensorFlow" in str(c) for c in tailored.certifications)

    # Verify contact preserved
    assert tailored.contact.full_name == "Nadhif Fauzil Adhim"
    assert tailored.contact.email == "nadhiffauzil@gmail.com"


@pytest.mark.asyncio
async def test_adaptive_section_discovery_and_rendering():
    from jobflow.core.cv_parser import CVParserAgent
    from jobflow.core.agent_harness import AIAgentHarness
    from jobflow.core.pdf_generator import PDFGenerator

    sample_with_custom_sections = """
Nadhif Fauzil Adhim
Email: nadhiffauzil@gmail.com
Phone: +62 812-3456-7890
Location: Surabaya, Indonesia

SUMMARY
Senior AI Engineer and Full Stack Developer.

TECHNICAL SKILLS
Python, FastAPI, TypeScript, Docker

WORK EXPERIENCE
Senior AI Engineer
Tech Innovations Ltd
2023 - Present
• Designed autonomous AI workflows and resilient data pipelines.

EDUCATION
Universitas Pembangunan Nasional Veteran Jawa Timur
Bachelor of Computer Science
2019 - 2023

PROJECTS
JobFlow AI
Autonomous ATS CV generator.

AWARDS & HONORS
• 1st Place Winner - National AI Innovation Hackathon 2023
• Best Engineering Thesis - UPN Veteran Jatim 2023

PUBLICATIONS
• High-Throughput Autonomous Agents in Enterprise Automation - IEEE Conference 2024

LANGUAGES
• Indonesian: Native
• English: Professional Working Proficiency
"""

    agent = CVParserAgent()
    profile = await agent.parse_cv(sample_with_custom_sections)

    # 1. Verify adaptive discovery of custom sections
    assert len(profile.custom_sections) >= 2
    csec_ids = [cs.id for cs in profile.custom_sections]
    assert any(x in csec_ids for x in ["awards", "languages", "publications"])

    awards_sec = next((cs for cs in profile.custom_sections if "award" in cs.id or "award" in cs.heading.lower()), None)
    if awards_sec:
        assert len(awards_sec.items) >= 1
        assert any("Hackathon" in (item.title or "") or "Hackathon" in (item.subtitle or "") for item in awards_sec.items)

    # 2. Verify tailoring preservation of all custom sections
    harness = AIAgentHarness(master_profile=profile)
    job = JobListing(
        title="Staff AI Platform Engineer",
        company="Global Enterprise AI",
        description="Looking for an engineer to architect scalable AI tools.",
        requirements=["Python", "FastAPI"]
    )
    tailored = await harness.tailor_for_job(job)

    assert len(tailored.custom_sections) == len(profile.custom_sections)
    tailored_csec_ids = [cs.id for cs in tailored.custom_sections]
    for cid in csec_ids:
        assert cid in tailored_csec_ids

    # 3. Verify HTML and PDF rendering includes the custom sections
    pdf_gen = PDFGenerator()
    html = pdf_gen.render_html(tailored)
    assert "Nadhif Fauzil Adhim" in html
    assert any(heading in html for heading in ["Awards & Honors", "Languages", "Publications & Research", "Publications"])
    assert any(term in html for term in ["Hackathon", "English", "IEEE"])


