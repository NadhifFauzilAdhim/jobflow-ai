import pytest
import asyncio
from pathlib import Path
from jobflow.core.schema import JobListing, MasterProfile, ContactInfo, SkillCategory, WorkExperience, Education, PlatformType
from jobflow.core.ats_scorer import evaluate_ats, extract_keywords
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.extractors.platform_extractors import get_job_extractor, GenericJobExtractor
from jobflow.automations.form_solver import FormSolver


@pytest.fixture
def sample_profile():
    return MasterProfile(
        contact=ContactInfo(
            full_name="Alex Morgan",
            email="alex.morgan@example.com",
            phone="+1 (555) 019-2834",
            location="San Francisco, CA",
            github_url="https://github.com/alexmorgan-demo",
            linkedin_url="https://linkedin.com/in/alexmorgan-demo"
        ),
        summary="AI & Full-Stack Engineer with experience in Python, FastAPI, and Docker microservices.",
        skills=[
            SkillCategory(category="Languages", skills=["Python", "TypeScript", "SQL"]),
            SkillCategory(category="Frameworks & Tools", skills=["FastAPI", "Docker", "Next.js", "Playwright", "PostgreSQL"])
        ],
        experience=[
            WorkExperience(
                company="Tech Studio",
                position="AI Software Engineer",
                start_date="2023",
                end_date="Present",
                highlights=["Engineered automated workflows and scalable microservices."],
                technologies=["Python", "FastAPI", "Docker"]
            )
        ],
        education=[
            Education(
                institution="University of Technology",
                degree="Bachelor of Computer Science",
                field_of_study="Informatics",
                start_date="2020",
                end_date="2024"
            )
        ]
    )


@pytest.fixture
def sample_job():
    return JobListing(
        title="Senior Python Backend Engineer",
        company="Global Cloud Corp",
        description="Looking for an experienced Python developer skilled in FastAPI, Docker, and PostgreSQL pipelines.",
        requirements=[
            "Proficiency in Python and FastAPI",
            "Experience with Docker and PostgreSQL",
            "Familiarity with Playwright browser automation"
        ]
    )


def test_keyword_extraction():
    text = "We are hiring a Python Engineer with FastAPI and Docker skills."
    kw = extract_keywords(text)
    assert "python" in kw or "fastapi" in kw or "docker" in kw


def test_ats_scorer(sample_profile, sample_job):
    result = evaluate_ats(sample_profile, sample_job)
    assert result.score > 0
    assert len(result.matched_keywords) > 0
    assert isinstance(result.suggestions, list)


@pytest.mark.asyncio
async def test_resume_tailoring_and_pdf_generation(sample_profile, sample_job, tmp_path):
    engine = ResumeEngine(master_profile=sample_profile)
    tailored = await engine.tailor_resume(sample_job)
    
    assert tailored.job_title_target == sample_job.title
    assert tailored.target_company == sample_job.company
    assert tailored.ats_score > 0

    generator = PDFGenerator()
    html = generator.render_html(tailored)
    assert sample_profile.contact.full_name in html
    assert "WORK EXPERIENCE" in html or "Work Experience" in html

    # Test PDF generation (ReportLab / WeasyPrint)
    pdf_path = await generator.generate_pdf(tailored, output_filename="test_tailored.pdf")
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 500


def test_form_solver(sample_profile):
    solver = FormSolver(sample_profile)
    assert solver.answer_question("What is your full name?") == "Alex Morgan"
    assert solver.answer_question("Enter your email address") == "alex.morgan@example.com"
    assert solver.answer_question("Expected salary in IDR") != ""


def test_job_extractor_parsing():
    raw_job = """
    Lead AI Engineer
    Anthropic Partners
    Requirements:
    - 3+ years experience with Python
    - Strong background in LLM fine-tuning
    - Experience in Docker containerization
    """
    extractor = GenericJobExtractor()
    listing = extractor.extract_from_raw_text(raw_job, title="Lead AI Engineer", company="Anthropic Partners")
    assert listing.title == "Lead AI Engineer"
    assert listing.company == "Anthropic Partners"
    assert len(listing.requirements) > 0
