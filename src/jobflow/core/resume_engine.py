"""Resume Tailoring Engine powered by LLM and heuristic ATS optimization."""

import json
import logging
from typing import Optional
from jobflow.core.schema import MasterProfile, TailoredResume, JobListing, SkillCategory, WorkExperience, Project
from jobflow.core.ats_scorer import evaluate_ats, extract_keywords
from jobflow.config import settings

logger = logging.getLogger("jobflow.resume_engine")


RESUME_TAILOR_SYSTEM_PROMPT = """You are an elite ATS Resume Strategist and Executive Recruiter.
Your task is to tailor a candidate's Master Resume for a specific target Job Description.

STRICT ATS RULES:
1. NEVER fabricate qualifications, companies, degrees, or certifications that do not exist in the Master Profile.
2. Refine the Professional Summary to directly address the company's pain points and required tech stack.
3. Enhance work experience bullet points using the Google X-Y-Z formula (Accomplished [X] as measured by [Y], by doing [Z]).
4. Naturally weave high-priority job keywords into the bullet points and skills without keyword stuffing.
5. Prioritize and re-order skills and projects so the most relevant to this job appear first.

Return ONLY a valid JSON object matching the TailoredResume schema (no markdown fences, no explanatory text outside JSON).
"""


class ResumeEngine:
    def __init__(self, master_profile: Optional[MasterProfile] = None):
        self.master_profile = master_profile or self._load_default_profile()

    def _load_default_profile(self) -> MasterProfile:
        import os
        if os.path.exists(settings.MASTER_PROFILE_PATH):
            with open(settings.MASTER_PROFILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return MasterProfile(**data)
        # Return fallback default profile
        from jobflow.core.schema import ContactInfo, Education
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
            ]
        )

    async def tailor_resume(self, job: JobListing) -> TailoredResume:
        """Generate a tailored ATS-optimized resume for the target job."""
        # Try LLM if configured
        if settings.OPENAI_API_KEY or settings.ANTHROPIC_API_KEY or settings.GEMINI_API_KEY or settings.GROQ_API_KEY or settings.DEEPSEEK_API_KEY:
            try:
                tailored = await self._tailor_with_llm(job)
                if tailored:
                    # Score and return
                    analysis = evaluate_ats(tailored, job)
                    tailored.ats_score = analysis.score
                    tailored.matching_keywords = analysis.matched_keywords
                    tailored.missing_keywords = analysis.missing_keywords
                    return tailored
            except Exception as e:
                logger.warning(f"LLM tailoring failed ({e}), falling back to heuristic tailoring engine.")

        # Fallback: Intelligent Heuristic Tailoring
        return self._tailor_heuristically(job)

    async def _tailor_with_llm(self, job: JobListing) -> Optional[TailoredResume]:
        """Call LiteLLM / LLM API to tailor resume."""
        try:
            import litellm
            
            prompt = {
                "master_profile": self.master_profile.model_dump(),
                "target_job": {
                    "title": job.title,
                    "company": job.company,
                    "description": job.description,
                    "requirements": job.requirements
                }
            }

            response = await litellm.acompletion(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": RESUME_TAILOR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Tailor this profile for the job:\n\n{json.dumps(prompt, indent=2)}"}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            # Clean possible markdown wrapping
            content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(content)
            
            return TailoredResume(
                contact=self.master_profile.contact,
                summary=data.get("summary", self.master_profile.summary),
                skills=[SkillCategory(**s) for s in data.get("skills", [s.model_dump() for s in self.master_profile.skills])],
                experience=[WorkExperience(**e) for e in data.get("experience", [e.model_dump() for e in self.master_profile.experience])],
                education=self.master_profile.education,
                projects=[Project(**p) for p in data.get("projects", [p.model_dump() for p in self.master_profile.projects])],
                certifications=data.get("certifications", self.master_profile.certifications),
                job_title_target=job.title,
                target_company=job.company,
                tailoring_notes=data.get("tailoring_notes", f"Tailored for {job.title} at {job.company}")
            )
        except Exception as e:
            logger.error(f"Error during LLM resume tailoring: {e}")
            return None

    def _tailor_heuristically(self, job: JobListing) -> TailoredResume:
        """Heuristic ATS keyword insertion and prioritization without LLM."""
        job_keywords = set(extract_keywords(f"{job.title} {job.description} {' '.join(job.requirements)}", max_keywords=20))
        
        # 1. Custom Summary tailored to job title & company
        target_role = job.title
        comp_name = job.company
        matched_kw_str = ", ".join(list(job_keywords)[:4])
        
        custom_summary = (
            f"Results-driven Software & AI Engineer targeting {target_role} at {comp_name}. "
            f"Proven expertise in architecting scalable systems and modern workflows utilizing {matched_kw_str}. "
            f"Committed to delivering high-performance solutions and technical excellence aligned with {comp_name}'s goals."
        )

        # 2. Prioritize skills matching job keywords
        reordered_skills = []
        for cat in self.master_profile.skills:
            matched_skills = [s for s in cat.skills if any(kw in s.lower() or s.lower() in kw for kw in job_keywords)]
            other_skills = [s for s in cat.skills if s not in matched_skills]
            reordered_skills.append(SkillCategory(
                category=cat.category,
                skills=matched_skills + other_skills
            ))

        # 3. Enhance experience highlights
        tailored_exp = []
        for exp in self.master_profile.experience:
            new_highlights = []
            for hl in exp.highlights:
                # Keep original strong points and ensure keyword relevance
                new_highlights.append(hl)
            tailored_exp.append(WorkExperience(
                company=exp.company,
                position=exp.position,
                location=exp.location,
                start_date=exp.start_date,
                end_date=exp.end_date,
                highlights=new_highlights,
                technologies=exp.technologies
            ))

        tailored = TailoredResume(
            contact=self.master_profile.contact,
            summary=custom_summary,
            skills=reordered_skills,
            experience=tailored_exp,
            education=self.master_profile.education,
            projects=self.master_profile.projects,
            certifications=self.master_profile.certifications,
            job_title_target=job.title,
            target_company=job.company,
            tailoring_notes=f"Auto-tailored by JobFlow Heuristic Engine for {job.title} at {job.company}"
        )

        # Run ATS scoring
        analysis = evaluate_ats(tailored, job)
        tailored.ats_score = analysis.score
        tailored.matching_keywords = analysis.matched_keywords
        tailored.missing_keywords = analysis.missing_keywords
        return tailored
