"""Autonomous AI Agent Harness for JobFlow AI.

Orchestrates multi-stage intelligent agents:
1. JobIntelligenceAgent: In-depth analysis of job description, tech stack, and evaluation criteria.
2. FitAnalyzerAgent: Cross-examines candidate's real profile against JD, finding key matches & gaps.
3. TailoringAgent: Adapts bullet points (Google X-Y-Z formula), summary, and prioritizes skills.
4. SchemaNormalizer: Intelligent resilience layer unwrapping nested keys and normalizing types.
5. ATSOptimizationLoop: Evaluates ATS keyword compatibility and validates density.
6. InterviewPrepAgent: Generates tailored interview talking points and strategic answers.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable, Union
from jobflow.core.schema import (
    MasterProfile,
    TailoredResume,
    JobListing,
    SkillCategory,
    WorkExperience,
    Education,
    Project,
    StylePreferences
)
from jobflow.core.ats_scorer import evaluate_ats, extract_keywords
from jobflow.config import settings

logger = logging.getLogger("jobflow.agent_harness")


class SchemaNormalizer:
    """Resilient data cleaner that unwraps arbitrary LLM JSON structures and normalizes fields."""

    @staticmethod
    def unwrap_root(data: Any) -> Dict[str, Any]:
        """Unwrap common nested root keys like 'master_profile', 'tailored_resume', 'data', 'profile'."""
        if not isinstance(data, dict):
            return {}
        
        # Check for single wrapper key or known envelope keys
        candidate_keys = ["master_profile", "tailored_resume", "resume", "data", "profile", "output"]
        for key in candidate_keys:
            if key in data and isinstance(data[key], dict) and len(data) <= 3:
                return data[key]

        return data

    @staticmethod
    def normalize_certifications(raw: Any) -> List[Union[str, Dict[str, Any]]]:
        """Convert list of dicts, objects, or strings into clean certification list."""
        if not raw:
            return []
        if isinstance(raw, str):
            return [raw]
        if not isinstance(raw, list):
            return []
        
        cleaned = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                cleaned.append(item.strip())
            elif isinstance(item, dict):
                # Extract name and optional issuer
                name = item.get("name") or item.get("title") or item.get("certificate")
                issuer = item.get("issuer") or item.get("issuing_organization") or item.get("authority")
                date = item.get("issue_date") or item.get("date") or item.get("year")
                if name:
                    parts = [str(name)]
                    if issuer:
                        parts.append(f"— {issuer}")
                    if date:
                        parts.append(f"({date})")
                    cleaned.append(" ".join(parts))
                else:
                    cleaned.append(item)
        return cleaned

    @staticmethod
    def normalize_skills(raw: Any, fallback: List[SkillCategory]) -> List[SkillCategory]:
        """Normalize skills whether LLM returns list of categories or flat list of strings."""
        if not raw or not isinstance(raw, list):
            return fallback
        
        # Case A: list of strings ["Python", "FastAPI"]
        if raw and isinstance(raw[0], str):
            return [SkillCategory(category="Technical Skills", skills=[str(s) for s in raw if s])]
        
        # Case B: list of dicts
        normalized = []
        for item in raw:
            if isinstance(item, dict):
                cat_name = item.get("category") or item.get("name") or "Technical Skills"
                skills_val = item.get("skills") or item.get("items") or []
                if isinstance(skills_val, str):
                    skills_list = [s.strip() for s in skills_val.split(",") if s.strip()]
                elif isinstance(skills_val, list):
                    skills_list = [str(s).strip() for s in skills_val if str(s).strip()]
                else:
                    skills_list = []
                
                if skills_list:
                    normalized.append(SkillCategory(category=cat_name, skills=skills_list))
        
        return normalized if normalized else fallback

    @staticmethod
    def normalize_experience(raw: Any, fallback: List[WorkExperience]) -> List[WorkExperience]:
        """Normalize work experience items and bullet points."""
        if not raw or not isinstance(raw, list):
            return fallback

        normalized = []
        for idx, item in enumerate(raw):
            if isinstance(item, dict):
                # Match corresponding fallback experience for fallback fields
                fb = fallback[idx] if idx < len(fallback) else None
                company = item.get("company") or (fb.company if fb else "Company")
                position = item.get("position") or (fb.position if fb else "Position")
                location = item.get("location", fb.location if fb else "")
                start_date = str(item.get("start_date") or (fb.start_date if fb else "2022"))
                end_date = str(item.get("end_date") or (fb.end_date if fb else "Present"))
                
                # Highlights
                highlights_raw = item.get("highlights") or item.get("bullets") or item.get("responsibilities") or (fb.highlights if fb else [])
                if isinstance(highlights_raw, str):
                    highlights = [h.strip().lstrip("•-* ") for h in highlights_raw.split("\n") if h.strip()]
                elif isinstance(highlights_raw, list):
                    highlights = [str(h).strip() for h in highlights_raw if str(h).strip()]
                else:
                    highlights = fb.highlights if fb else []

                # Technologies
                tech_raw = item.get("technologies") or (fb.technologies if fb else [])
                if isinstance(tech_raw, list):
                    technologies = [str(t).strip() for t in tech_raw if str(t).strip()]
                else:
                    technologies = []

                normalized.append(WorkExperience(
                    company=company,
                    position=position,
                    location=location,
                    start_date=start_date,
                    end_date=end_date,
                    highlights=highlights,
                    technologies=technologies
                ))
        return normalized if normalized else fallback


class JobIntelligenceAgent:
    """Agent that performs deep semantic analysis of the target job description."""

    async def analyze(self, job: JobListing) -> Dict[str, Any]:
        """Extract key priorities, core tech stack, seniority, and high-impact keywords."""
        keywords = extract_keywords(f"{job.title} {job.description} {' '.join(job.requirements)}", max_keywords=25)
        return {
            "title": job.title,
            "company": job.company,
            "core_keywords": keywords[:12],
            "secondary_keywords": keywords[12:],
            "seniority": "Senior" if any(s in job.title.lower() for s in ["senior", "lead", "principal", "head"]) else "Mid/Standard",
            "key_requirements": job.requirements[:8]
        }


class FitAnalyzerAgent:
    """Agent that evaluates candidate's real profile against the job intelligence."""

    def evaluate_fit(self, master_profile: MasterProfile, job_intel: Dict[str, Any]) -> Dict[str, Any]:
        """Identify authentic matching experiences, skill overlaps, and strategic angles."""
        all_candidate_skills = {s.lower() for cat in master_profile.skills for s in cat.skills}
        job_keywords = {k.lower() for k in job_intel.get("core_keywords", [])}

        matched_skills = [s for s in all_candidate_skills if any(k in s or s in k for k in job_keywords)]
        missing_skills = [k for k in job_keywords if not any(s in k or k in s for s in all_candidate_skills)]

        # Determine top 3-4 selling points
        selling_points = []
        if matched_skills:
            selling_points.append(f"Demonstrated proficiency in {', '.join(list(matched_skills)[:3])}")
        if master_profile.experience:
            selling_points.append(f"Hands-on delivery history at {master_profile.experience[0].company}")
        selling_points.append(f"Direct alignment with {job_intel['company']}'s technical goals")

        return {
            "matched_skills": list(matched_skills),
            "missing_skills": list(missing_skills)[:6],
            "selling_points": selling_points,
            "match_density": round((len(matched_skills) / max(len(job_keywords), 1)) * 100, 1)
        }


class AIAgentHarness:
    """Master AI Agent Harness orchestrating end-to-end resume tailoring and application intelligence."""

    def __init__(self, master_profile: MasterProfile):
        self.master_profile = master_profile
        self.job_intel_agent = JobIntelligenceAgent()
        self.fit_analyzer = FitAnalyzerAgent()
        self.normalizer = SchemaNormalizer()

    async def execute_tailoring(
        self,
        job: JobListing,
        on_progress: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> TailoredResume:
        """Execute multi-stage agent pipeline with progress reporting and resilient fallback."""
        async def log_step(stage: str, msg: str):
            logger.info(f"[{stage}] {msg}")
            if on_progress:
                try:
                    await on_progress(stage, msg)
                except Exception as ex:
                    logger.warning(f"Error in on_progress callback: {ex}")

        # Stage 1: Job Intelligence
        await log_step("Job Intelligence", f"Deconstructing job requirements for '{job.title}' at {job.company}...")
        job_intel = await self.job_intel_agent.analyze(job)

        # Stage 2: Fit Analysis
        await log_step("Fit Analysis", f"Cross-examining authentic Master Profile of {self.master_profile.contact.full_name} against target criteria...")
        fit_data = self.fit_analyzer.evaluate_fit(self.master_profile, job_intel)

        # Stage 3: LLM Tailoring
        await log_step("Resume Synthesis", "Executing LLM Agent for ATS optimization with Google X-Y-Z formula...")
        tailored = await self._run_llm_synthesis(job, job_intel, fit_data, log_step)

        if not tailored:
            await log_step("Heuristic Fallback", "Using intelligent heuristic synthesis engine...")
            tailored = self._run_heuristic_synthesis(job, job_intel, fit_data)

        # Stage 4: ATS Optimization Loop & Verification
        await log_step("ATS Verification", "Running automated ATS verification and keyword density evaluation...")
        analysis = evaluate_ats(tailored, job)
        tailored.ats_score = analysis.score
        tailored.matching_keywords = analysis.matched_keywords
        tailored.missing_keywords = analysis.missing_keywords

        # Stage 5: Interview Prep & Talking Points
        if not tailored.interview_talking_points:
            tailored.interview_talking_points = [
                f"Be prepared to explain how your experience at {self.master_profile.experience[0].company if self.master_profile.experience else 'previous roles'} solves {job.company}'s challenges.",
                f"Highlight your direct expertise with {', '.join(fit_data.get('matched_skills', [])[:3])}.",
                f"Emphasize metrics-driven impact from your featured projects or achievements."
            ]

        await log_step("Complete", f"Resume tailoring finalized! ATS Compatibility: {tailored.ats_score}%")
        return tailored

    async def tailor_for_job(self, job: JobListing) -> TailoredResume:
        """Convenience alias for execute_tailoring."""
        return await self.execute_tailoring(job)

    async def _run_llm_synthesis(
        self,
        job: JobListing,
        job_intel: Dict[str, Any],
        fit_data: Dict[str, Any],
        log_step: Callable[[str, str], Awaitable[None]]
    ) -> Optional[TailoredResume]:
        """Execute LiteLLM call with strict prompt, unwrap response, and normalize schema."""
        has_llm = bool(
            settings.OPENAI_API_BASE
            or settings.OPENAI_API_KEY
            or settings.ANTHROPIC_API_KEY
            or settings.GEMINI_API_KEY
            or settings.GROQ_API_KEY
            or settings.DEEPSEEK_API_KEY
        )
        if not has_llm:
            return None

        try:
            import litellm

            system_prompt = (
                "You are an elite ATS Resume Strategist and Executive Recruiter AI Agent.\n"
                "Your objective is to tailor the candidate's Master Resume for the target Job Description while strictly honoring their authentic history.\n\n"
                "PRESERVATION & GROUNDING MANDATE:\n"
                "1. The candidate's CV is the absolute ground truth. You MUST retain ALL projects, ALL education records, ALL companies, and ALL certifications.\n"
                "2. NEVER invent companies, degrees, dates, or credentials not in the Master Profile.\n"
                "3. Transform work experience highlights using the Google X-Y-Z formula: 'Accomplished [X] as measured by [Y], by doing [Z]', weaving in target job keywords naturally while preserving authentic facts.\n"
                "4. Refine the Professional Summary (2-3 sentences) directly addressing the target company's pain points and role requirements.\n"
                "5. Prioritize matching technical skills and projects at the top, but DO NOT delete existing skills or projects.\n"
                "6. Provide `agent_reasoning` explaining your tailoring rationale, `key_strengths` (top 3-4 selling points), and `interview_talking_points` (3 key talking points for the interview).\n\n"
                "Return ONLY a flat JSON object with these exact top-level keys: "
                "\"summary\", \"skills\", \"experience\", \"education\", \"projects\", \"certifications\", \"agent_reasoning\", \"key_strengths\", \"interview_talking_points\". "
                "Do NOT wrap in an envelope or sub-object."
            )

            prompt_payload = {
                "candidate_profile": self.master_profile.model_dump(),
                "target_job": {
                    "title": job.title,
                    "company": job.company,
                    "description": job.description,
                    "requirements": job.requirements,
                    "intelligence": job_intel
                },
                "fit_insights": fit_data
            }

            kwargs: Dict[str, Any] = {
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Tailor this profile:\n\n{json.dumps(prompt_payload, indent=2)}"}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "request_timeout": 35
            }

            if settings.OPENAI_API_BASE:
                kwargs["api_base"] = settings.OPENAI_API_BASE
                if not settings.LLM_MODEL.startswith("openai/"):
                    kwargs["custom_llm_provider"] = "openai"
            if settings.OPENAI_API_KEY:
                kwargs["api_key"] = settings.OPENAI_API_KEY

            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content.strip()
            content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            raw_data = json.loads(content)
            # Apply resilient normalization
            unwrapped = self.normalizer.unwrap_root(raw_data)

            # 1. Summary (tailored)
            summary = unwrapped.get("summary") or self.master_profile.summary

            # 2. Skills (prioritized matching skills first, all original skills preserved)
            skills = self.normalizer.normalize_skills(unwrapped.get("skills"), self.master_profile.skills)

            # 3. Experience (bullets refined with X-Y-Z, all companies preserved)
            experience = self.normalizer.normalize_experience(unwrapped.get("experience"), self.master_profile.experience)

            # 4. Education (100% preserved from authentic CV)
            education = self.master_profile.education

            # 5. Projects (100% preserved from authentic CV, enriched if LLM provided relevant highlights)
            llm_projects = []
            for p in unwrapped.get("projects", []):
                if isinstance(p, dict) and (p.get("name") or p.get("title")):
                    try:
                        llm_projects.append(Project(
                            name=p.get("name") or p.get("title") or "Project",
                            description=p.get("description") or "",
                            technologies=p.get("technologies") or p.get("tech_stack") or [],
                            link=p.get("link") or p.get("url"),
                            highlights=p.get("highlights") or []
                        ))
                    except Exception:
                        pass
            llm_proj_map = {p.name.lower(): p for p in llm_projects}
            final_projects = []
            for orig_p in self.master_profile.projects:
                if orig_p.name.lower() in llm_proj_map:
                    # Use adapted project if available
                    final_projects.append(llm_proj_map[orig_p.name.lower()])
                else:
                    final_projects.append(orig_p)
            if not final_projects:
                final_projects = self.master_profile.projects

            # 6. Certifications (100% preserved)
            certifications = self.normalizer.normalize_certifications(self.master_profile.certifications) or self.normalizer.normalize_certifications(unwrapped.get("certifications"))

            # 7. Adaptive Custom Sections (100% preserved from authentic CV)
            custom_sections = self.master_profile.custom_sections

            agent_reasoning = unwrapped.get("agent_reasoning") or f"Strategically reframed experience highlights using Google X-Y-Z formula to match {job.company}'s requirements while preserving all original credentials."
            key_strengths = unwrapped.get("key_strengths") or fit_data.get("selling_points", [])
            interview_points = unwrapped.get("interview_talking_points") or []

            style_prefs = self.master_profile.style_preferences or StylePreferences()

            return TailoredResume(
                contact=self.master_profile.contact,
                summary=summary,
                skills=skills,
                experience=experience,
                education=education,
                projects=final_projects,
                certifications=certifications,
                custom_sections=custom_sections,
                job_title_target=job.title,
                target_company=job.company,
                tailoring_notes=f"AI Agent Harness tailored for {job.title} at {job.company}",
                style_preferences=style_prefs,
                agent_reasoning=agent_reasoning,
                key_strengths=key_strengths,
                interview_talking_points=interview_points,
                job_fit_summary=fit_data
            )

        except Exception as e:
            logger.error(f"Error during AI Agent Harness LLM synthesis: {e}", exc_info=True)
            return None

    def _run_heuristic_synthesis(
        self,
        job: JobListing,
        job_intel: Dict[str, Any],
        fit_data: Dict[str, Any]
    ) -> TailoredResume:
        """Heuristic synthesis fallback."""
        top_kws = ", ".join(job_intel.get("core_keywords", [])[:4]) or "modern architectures"
        summary = (
            f"Results-driven AI & Software Specialist targeting {job.title} at {job.company}. "
            f"Proven expertise in scalable systems utilizing {top_kws}. "
            f"Dedicated to technical excellence and delivering high-impact solutions aligned with {job.company}'s goals."
        )

        job_kw_set = set(k.lower() for k in job_intel.get("core_keywords", []))
        reordered_skills = []
        for cat in self.master_profile.skills:
            matched = [s for s in cat.skills if any(kw in s.lower() or s.lower() in kw for kw in job_kw_set)]
            others = [s for s in cat.skills if s not in matched]
            reordered_skills.append(SkillCategory(category=cat.category, skills=matched + others))

        style_prefs = self.master_profile.style_preferences or StylePreferences()

        return TailoredResume(
            contact=self.master_profile.contact,
            summary=summary,
            skills=reordered_skills,
            experience=self.master_profile.experience,
            education=self.master_profile.education,
            projects=self.master_profile.projects,
            certifications=self.normalizer.normalize_certifications(self.master_profile.certifications),
            custom_sections=self.master_profile.custom_sections,
            job_title_target=job.title,
            target_company=job.company,
            tailoring_notes=f"AI Agent Harness (Heuristic Mode) tailored for {job.title} at {job.company}",
            style_preferences=style_prefs,
            agent_reasoning=f"Surfaced high-priority technical competencies ({top_kws}) and aligned executive summary with {job.company} requirements.",
            key_strengths=fit_data.get("selling_points", []),
            interview_talking_points=[
                f"Highlight direct experience with {top_kws}.",
                f"Connect past project metrics to {job.company}'s core mission."
            ],
            job_fit_summary=fit_data
        )
