import io
import pytest
from httpx import AsyncClient, ASGITransport
from jobflow.api.app import app
from jobflow.db.database import init_db
from jobflow.core.cv_parser import extract_text_from_file, CVParserAgent
from jobflow.core.schema import MasterProfile, ContactInfo, SkillCategory, WorkExperience, Education, StylePreferences, JobListing
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.config import settings
from jobflow.core.security import create_session_token


def get_auth_client():
    token = create_session_token("admin")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {token}"},
        cookies={settings.SESSION_COOKIE_NAME: token}
    )



SAMPLE_CV_TEXT = """
Alex Morgan
Email: alex.morgan@example.com
Phone: +1 (555) 019-2834
Location: San Francisco, CA
LinkedIn: linkedin.com/in/alexmorgan-dev
GitHub: github.com/alexmorgan-dev

SUMMARY
Lead AI and Full-Stack Software Engineer with 4+ years of experience designing scalable web architectures, automated AI pipelines, and computer vision systems.

TECHNICAL SKILLS
Python, FastAPI, TypeScript, React, Next.js, Docker, PostgreSQL, Redis, Playwright

WORK EXPERIENCE
Lead AI & Full Stack Engineer
TechNova Solutions - San Francisco, CA
2023 - Present
• Architected and deployed distributed AI pipelines and microservices serving 20k+ monthly active requests with 99.9% uptime.
• Engineered autonomous browser automation bots utilizing Playwright, cutting manual data entry workflows by 80%.

EDUCATION
State University of Technology
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
    assert "Alex Morgan" in extracted
    assert "alex.morgan@example.com" in extracted


@pytest.mark.asyncio
async def test_cv_parser_agent_heuristic():
    agent = CVParserAgent()
    # Test heuristic fallback directly
    profile = agent._parse_heuristically(SAMPLE_CV_TEXT)
    assert profile.contact.full_name == "Alex Morgan"
    assert profile.contact.email == "alex.morgan@example.com"
    assert len(profile.skills) > 0
    assert any("Python" in s for cat in profile.skills for s in cat.skills)
    assert len(profile.experience) > 0
    assert profile.style_preferences is not None
    assert "summary" in profile.style_preferences.section_order


@pytest.mark.asyncio
async def test_format_conforming_resume_engine():
    custom_profile = MasterProfile(
        contact=ContactInfo(
            full_name="Alex Morgan",
            email="alex.morgan@example.com",
            phone="+1 (555) 019-2834",
            location="San Francisco, CA"
        ),
        summary="Experienced AI & Web Architect.",
        skills=[
            SkillCategory(category="Languages & Frameworks", skills=["Python", "FastAPI", "Docker", "Playwright"])
        ],
        experience=[
            WorkExperience(
                company="TechNova Solutions",
                position="Lead AI Engineer",
                start_date="2023",
                end_date="Present",
                highlights=["Engineered autonomous agents cutting manual workflows by 80%"],
                technologies=["Python", "FastAPI"]
            )
        ],
        education=[
            Education(
                institution="State University of Technology",
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

    assert tailored.contact.full_name == "Alex Morgan"
    assert tailored.ats_score > 0
    assert tailored.style_preferences.accent_color == "#059669"
    assert tailored.style_preferences.section_order[0] == "skills"
    assert tailored.agent_reasoning is not None

    # Test HTML rendering respects section ordering
    generator = PDFGenerator()
    html = generator.render_html(tailored)
    assert "Alex Morgan" in html
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
    async with get_auth_client() as ac:
        files = {
            "file": ("test_resume.txt", io.BytesIO(SAMPLE_CV_TEXT.encode("utf-8")), "text/plain")
        }
        res = await ac.post("/api/profile/upload-cv", files=files)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "Alex Morgan" in data["profile"]["contact"]["full_name"]

        # Check status endpoint
        status_res = await ac.get("/api/profile/status")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["loaded"] is True
        assert "Alex" in status_data["name"]


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
    async with get_auth_client() as ac:
        payload = {"raw_text": SAMPLE_CV_TEXT}
        res = await ac.post("/api/profile/parse-text", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        prof = data["profile"]
        assert "Alex" in prof["contact"]["full_name"]
        assert len(prof["education"]) >= 1
        assert "University" in prof["education"][0]["institution"] or prof["education"][0]["degree"] != ""
        assert len(prof["projects"]) >= 1
        assert prof["projects"][0]["name"] != ""


@pytest.mark.asyncio
async def test_tailoring_preserves_candidate_education_and_projects():
    from jobflow.core.agent_harness import AIAgentHarness
    from jobflow.core.schema import Project

    custom_profile = MasterProfile(
        contact=ContactInfo(
            full_name="Alex Morgan",
            email="alex.morgan@example.com",
            phone="+1 (555) 019-2834",
            location="San Francisco, CA"
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
                institution="State University of Technology",
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
    assert tailored.education[0].institution == "State University of Technology"
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
    assert tailored.contact.full_name == "Alex Morgan"
    assert tailored.contact.email == "alex.morgan@example.com"


@pytest.mark.asyncio
async def test_adaptive_section_discovery_and_rendering():
    from jobflow.core.cv_parser import CVParserAgent
    from jobflow.core.agent_harness import AIAgentHarness
    from jobflow.core.pdf_generator import PDFGenerator

    sample_with_custom_sections = """
Alex Morgan
Email: alex.morgan@example.com
Phone: +1 (555) 019-2834
Location: San Francisco, CA

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
State University of Technology
Bachelor of Computer Science
2019 - 2023

PROJECTS
JobFlow AI
Autonomous ATS CV generator.

AWARDS & HONORS
• 1st Place Winner - National AI Innovation Hackathon 2023
• Best Engineering Thesis - State University 2023

PUBLICATIONS
• High-Throughput Autonomous Agents in Enterprise Automation - IEEE Conference 2024

LANGUAGES
• English: Native
• Spanish: Professional Working Proficiency
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
    assert "Alex Morgan" in html
    assert any(heading in html for heading in ["Awards & Honors", "Languages", "Publications & Research", "Publications"])
    assert any(term in html for term in ["Hackathon", "English", "IEEE"])


def test_schema_normalizer_education_and_projects():
    from jobflow.core.agent_harness import SchemaNormalizer
    from jobflow.core.schema import Education, Project

    # 1. Test normalize_education
    fallback_edu = [
        Education(
            institution="Universitas Amikom",
            degree="Bachelor of Informatics",
            field_of_study="Informatics",
            start_date="2022",
            end_date="2026",
            gpa="3.89",
            highlights=["Relevant coursework: Machine Learning, Database Systems, Computer Networks, Software Engineering"]
        )
    ]
    raw_edu = [
        {
            "institution": "Universitas Amikom",
            "degree": "Bachelor of Informatics",
            "highlights": ["Relevant coursework: Database Systems, Software Engineering, Machine Learning, Computer Networks"]
        }
    ]
    # For a backend job with keywords: ['database', 'software']
    norm_edu = SchemaNormalizer.normalize_education(raw_edu, fallback_edu, job_keywords=["database", "software"])
    assert len(norm_edu) == 1
    assert norm_edu[0].institution == "Universitas Amikom"
    assert norm_edu[0].degree == "Bachelor of Informatics"
    assert norm_edu[0].gpa == "3.89"
    # Coursework should prioritize 'Database Systems' and 'Software Engineering' first
    hl = norm_edu[0].highlights[0]
    assert "Database Systems" in hl
    assert hl.startswith("Relevant coursework: Database Systems, Software Engineering")

    # 2. Test normalize_projects
    fallback_proj = [
        Project(
            name="FlowServe — Smart POS",
            description="POS system for restaurants.",
            technologies=["Vue.js", "Laravel", "PostgreSQL", "Redis"],
            highlights=["Built POS app."]
        ),
        Project(
            name="FocusEye — Attention Detection",
            description="Computer vision detection system.",
            technologies=["Python", "TensorFlow", "YOLO"],
            highlights=["Built CV pipeline."]
        )
    ]
    raw_proj = [
        {
            "name": "FocusEye",
            "description": "Real-time edge attention monitoring system reaching 91% accuracy.",
            "technologies": ["TensorFlow", "Python", "MediaPipe"],
            "highlights": [
                "Engineered real-time computer vision inference reaching 91% accuracy, reducing false positives by 34%."
            ]
        },
        {
            "name": "FlowServe",
            "description": "High-throughput restaurant POS architecture processing 450 orders daily.",
            "technologies": ["PostgreSQL", "Redis", "Laravel"],
            "highlights": [
                "Optimized database indexing and Redis caching, cutting p95 API latency by 30%."
            ]
        }
    ]
    # Target job keywords: ['python', 'tensorflow', 'computervision']
    norm_proj = SchemaNormalizer.normalize_projects(raw_proj, fallback_proj, job_keywords=["python", "tensorflow"])
    assert len(norm_proj) == 2
    # First project should be FocusEye as prioritized by LLM
    assert "FocusEye" in norm_proj[0].name
    assert "91% accuracy" in norm_proj[0].description
    assert "reducing false positives by 34%" in norm_proj[0].highlights[0]
    # Technologies should prioritize python & tensorflow first
    assert norm_proj[0].technologies[0].lower() in ["python", "tensorflow"]

    # Second project FlowServe should also be preserved and tailored
    assert "FlowServe" in norm_proj[1].name
    assert "cutting p95 API latency by 30%" in norm_proj[1].highlights[0]


@pytest.mark.asyncio
async def test_heuristic_synthesis_tailors_projects_and_education():
    from jobflow.core.agent_harness import AIAgentHarness
    from jobflow.core.schema import MasterProfile, ContactInfo, SkillCategory, WorkExperience, Education, Project, JobListing

    profile = MasterProfile(
        contact=ContactInfo(full_name="Jane Doe", email="jane@example.com", phone="123", location="Jakarta"),
        summary="General Software Developer",
        skills=[SkillCategory(category="Languages", skills=["PHP", "Python", "Go"])],
        experience=[
            WorkExperience(
                company="Acme Corp",
                position="Developer",
                start_date="2022",
                end_date="Present",
                highlights=[
                    "Built PHP websites for clients",
                    "Architected high-scale Python microservices and PostgreSQL database schemas"
                ],
                technologies=["PHP", "Python", "PostgreSQL"]
            )
        ],
        education=[
            Education(
                institution="Tech University",
                degree="B.S. CS",
                field_of_study="Computer Science",
                start_date="2018",
                end_date="2022",
                highlights=["Relevant coursework: Graphic Design, Database Systems, Operating Systems"]
            )
        ],
        projects=[
            Project(
                name="WordPress Blog Theme",
                description="CMS blog template in PHP.",
                technologies=["PHP", "WordPress", "CSS"],
                highlights=["Created themes."]
            ),
            Project(
                name="Cloud Data Pipeline",
                description="Distributed streaming pipeline in Python and PostgreSQL.",
                technologies=["Python", "PostgreSQL", "Kafka"],
                highlights=["Processed 500k messages daily."]
            )
        ]
    )

    harness = AIAgentHarness(master_profile=profile)
    job = JobListing(
        title="Python Data Engineer",
        company="DataFlow Systems",
        description="Seeking Python and PostgreSQL engineer for scalable data infrastructure.",
        requirements=["Python", "PostgreSQL", "Data Pipeline"]
    )

    # Force heuristic fallback
    tailored = harness._run_heuristic_synthesis(job, {"core_keywords": ["python", "postgresql", "data"]}, {})

    # 1. Projects: Cloud Data Pipeline should be ranked #1 because it matches Python + PostgreSQL
    assert tailored.projects[0].name == "Cloud Data Pipeline"
    assert "Python" in tailored.projects[0].technologies[:2]

    # 2. Education: Coursework should prioritize 'Database Systems' & 'Operating Systems' over 'Graphic Design'
    edu_hl = tailored.education[0].highlights[0]
    assert edu_hl.index("Database Systems") < edu_hl.index("Graphic Design")

    # 3. Experience: Highlight mentioning Python/PostgreSQL should be moved to first position
    assert "Python microservices" in tailored.experience[0].highlights[0]


@pytest.mark.asyncio
async def test_html_rendering_highlights_all_sections():
    from jobflow.core.schema import TailoredResume, ContactInfo, SkillCategory, WorkExperience, Education, Project
    from jobflow.core.pdf_generator import PDFGenerator

    tailored = TailoredResume(
        contact=ContactInfo(full_name="Nadhif Adhim", email="nadhif@example.com", phone="123", location="Jakarta"),
        summary="Experienced Full-Stack and AI Engineer.",
        skills=[SkillCategory(category="Backend", skills=["Python", "PostgreSQL", "Redis"])],
        experience=[
            WorkExperience(
                company="Tech Co",
                position="Software Engineer",
                start_date="2023",
                end_date="Present",
                highlights=["Optimized database queries cutting latency by 40%."],
                technologies=["Python", "PostgreSQL"]
            )
        ],
        education=[
            Education(
                institution="Universitas Amikom",
                degree="Bachelor of Informatics",
                field_of_study="Informatics",
                start_date="2022",
                end_date="2026",
                highlights=["Relevant coursework: Database Systems, Computer Vision"]
            )
        ],
        projects=[
            Project(
                name="FocusEye Attention Tracker",
                description="Computer vision student attention system.",
                technologies=["Python", "TensorFlow", "PostgreSQL"],
                highlights=["Built real-time video pipeline achieving 91% accuracy."]
            )
        ],
        job_title_target="Python Backend Engineer",
        target_company="Target Corp",
        matching_keywords=["Python", "PostgreSQL", "Database Systems"]
    )

    pdf_gen = PDFGenerator()
    html = pdf_gen.render_html(tailored, show_highlights=True)

    # Check top banner
    assert "AI-Tailored & ATS-Optimized Document" in html

    # Check Summary badge
    assert "Role-Adapted" in html

    # Check Skills badge & keyword highlight
    assert "JD-Prioritized" in html

    # Check Experience badge & XYZ formula indicator
    assert "Google X-Y-Z Optimized" in html

    # Check Featured Projects badge & highlights
    assert "Target-Aligned" in html
    assert "FocusEye Attention Tracker" in html
    # Python & PostgreSQL should be highlighted in the project tech stack
    assert 'background: #f4f4f5; color: #09090b; font-weight: 700; padding: 0 3px; border-radius: 2px; border-bottom: 1.5px solid #09090b;">Python</span>' in html

    # Check Education badge & highlights
    assert "Curated Coursework" in html
    assert "Universitas Amikom" in html
    assert "Relevant coursework: Database Systems, Computer Vision" in html


@pytest.mark.asyncio
async def test_adaptive_section_recognition_and_tailoring():
    from jobflow.core.cv_parser import CVParserAgent
    from jobflow.core.agent_harness import AIAgentHarness, SchemaNormalizer
    from jobflow.core.schema import CustomSection, CustomSectionItem, JobListing
    from jobflow.core.pdf_generator import PDFGenerator

    cv_with_arbitrary_sections = """
Budi Santoso
Email: budi@example.com
Phone: +62 812 3456 7890
Location: Jakarta, Indonesia

RINGKASAN PROFESIONAL
Full-Stack Developer dengan spesialisasi arsitektur cloud dan web berskala besar.

KEAHLIAN TEKNIS
Python, Go, PostgreSQL, Docker, Redis

PENGALAMAN KERJA
Software Engineer
PT Inovasi Digital
2022 - Sekarang
• Membangun sistem backend pembayaran terdistribusi.

RIWAYAT PENDIDIKAN
Universitas Indonesia
Sarjana Ilmu Komputer
2018 - 2022

PORTOFOLIO & PROYEK
PayFlow Gateway
Sistem gateway transaksi keuangan.
• Menangani 100k transaksi per hari.

PENGALAMAN ORGANISASI
Ketua Divisi Teknologi - Himpunan Mahasiswa Ilmu Komputer
2020 - 2021
• Memimpin 15 anggota divisi dalam merancang portal akademik fakultas.
• Mengorganisasi pelatihan Git dan web development untuk 120 mahasiswa baru.

PELATIHAN & BOOTCAMP
Google Cloud Certified Data & AI Engineer Bootcamp
2023
• Menyelesaikan 200 jam pelatihan intensif arsitektur big data dan model training.

BEASISWA & PENGHARGAAN
Penerima Beasiswa Prestasi Nasional
Kementerian Pendidikan
2021
• Diberikan atas prestasi akademis dan kepemimpinan terbaik tingkat universitas.
"""

    # 1. Test that the heuristic parser adaptively recognizes ALL non-standard sections
    agent = CVParserAgent()
    profile = agent._parse_heuristically(cv_with_arbitrary_sections)

    assert len(profile.custom_sections) >= 3
    section_headings = [cs.heading.lower() for cs in profile.custom_sections]
    assert any("organisasi" in h for h in section_headings)
    assert any("bootcamp" in h or "pelatihan" in h for h in section_headings)
    assert any("penghargaan" in h or "beasiswa" in h for h in section_headings)

    # 2. Test SchemaNormalizer.normalize_custom_sections adapts and preserves items
    job_kws = ["arsitektur", "portal", "cloud", "pelatihan"]
    raw_custom = [
        {
            "id": profile.custom_sections[0].id,
            "items": [
                {
                    "title": profile.custom_sections[0].items[0].title,
                    "bullets": [
                        "Architected faculty academic portal leading 15 engineers with 99% uptime.",
                        "Organized intensive web architecture and Git workshops for 120 students."
                    ]
                }
            ]
        }
    ]
    norm_custom = SchemaNormalizer.normalize_custom_sections(raw_custom, profile.custom_sections, job_kws)
    assert len(norm_custom) == len(profile.custom_sections)
    # The tailored bullets should be adopted
    first_sec = norm_custom[0]
    assert "99% uptime" in first_sec.items[0].bullets[0] or "portal" in first_sec.items[0].bullets[0]

    # 3. Test AIAgentHarness tailoring adapts custom sections and custom section ordering
    harness = AIAgentHarness(master_profile=profile)
    job = JobListing(
        title="Lead Full-Stack Cloud Architect",
        company="Enterprise Global Tech",
        description="Seeking leader to guide technical teams and architect cloud platforms.",
        requirements=["Python", "Cloud", "Leadership"]
    )
    tailored = await harness.tailor_for_job(job)
    assert len(tailored.custom_sections) >= 3
    tailored_csec_ids = [cs.id for cs in tailored.custom_sections]
    assert profile.custom_sections[0].id in tailored_csec_ids

    # 4. Test HTML rendering includes custom section with AI badge
    pdf_gen = PDFGenerator()
    html = pdf_gen.render_html(tailored, show_highlights=True)
    assert "Role-Aligned" in html
    assert any(term in html for term in ["Organisasi", "Pelatihan", "Bootcamp", "Penghargaan"])


