"""Resume Tailoring Engine powered by the AI Agent Harness."""

import json
import logging
from typing import Optional, Callable, Awaitable
from jobflow.core.schema import (
    MasterProfile,
    TailoredResume,
    JobListing,
    SkillCategory,
    WorkExperience,
    Education,
    ContactInfo,
    StylePreferences
)
from jobflow.core.agent_harness import AIAgentHarness
from jobflow.config import settings

logger = logging.getLogger("jobflow.resume_engine")


class ResumeEngine:
    """High-level facade connecting callers to the AIAgentHarness."""

    def __init__(self, master_profile: Optional[MasterProfile] = None):
        self.master_profile = master_profile or self._load_default_profile()
        self.harness = AIAgentHarness(self.master_profile)

    def _load_default_profile(self) -> MasterProfile:
        import os
        if os.path.exists(settings.MASTER_PROFILE_PATH):
            try:
                with open(settings.MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return MasterProfile(**data)
            except Exception as e:
                logger.warning(f"Could not load master profile from {settings.MASTER_PROFILE_PATH}: {e}")

        # Fallback default profile
        return MasterProfile(
            contact=ContactInfo(
                full_name="Candidate Name",
                email="candidate@example.com",
                phone="+62 812 3456 7890",
                location="Jakarta, Indonesia",
                github_url="https://github.com/candidate",
                linkedin_url="https://linkedin.com/in/candidate"
            ),
            summary="Experienced Full Stack & AI Software Engineer specializing in modern web applications and automated workflows.",
            skills=[
                SkillCategory(category="Languages & Frameworks", skills=["Python", "TypeScript", "React", "Next.js", "FastAPI"]),
                SkillCategory(category="DevOps & Tools", skills=["Docker", "PostgreSQL", "Redis", "Git", "Playwright"])
            ],
            experience=[
                WorkExperience(
                    company="Tech Innovators",
                    position="Software Engineer",
                    start_date="2023",
                    end_date="Present",
                    highlights=[
                        "Architected full-stack automation pipelines reducing manual processing time by 65%",
                        "Built resilient backend microservices with FastAPI and PostgreSQL serving 10k+ daily users"
                    ],
                    technologies=["Python", "FastAPI", "Docker", "PostgreSQL"]
                )
            ],
            education=[
                Education(
                    institution="State University",
                    degree="Bachelor of Science",
                    field_of_study="Computer Science",
                    start_date="2019",
                    end_date="2023"
                )
            ],
            style_preferences=StylePreferences()
        )

    async def tailor_resume(
        self,
        job: JobListing,
        on_progress: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> TailoredResume:
        """Generate a tailored ATS-optimized resume using the full AI Agent Harness."""
        return await self.harness.execute_tailoring(job, on_progress=on_progress)
