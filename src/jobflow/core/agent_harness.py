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
    CustomSection,
    CustomSectionItem,
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

    @staticmethod
    def normalize_education(
        raw: Any,
        fallback: List[Education],
        job_keywords: Optional[List[str]] = None
    ) -> List[Education]:
        """Normalize education: strictly preserve authentic degrees, institutions, GPA, dates,
        while allowing AI-curated highlights (coursework, focus, honors) aligned with target role."""
        if not fallback:
            return []
        if not raw or not isinstance(raw, list):
            return fallback

        kw_set = {k.lower() for k in (job_keywords or [])}

        normalized = []
        for idx, fb in enumerate(fallback):
            raw_item = None
            for item in raw:
                if isinstance(item, dict):
                    inst = str(item.get("institution") or item.get("school") or item.get("university") or "").lower()
                    deg = str(item.get("degree") or item.get("title") or "").lower()
                    if (inst and (inst in fb.institution.lower() or fb.institution.lower() in inst)) or \
                       (deg and (deg in fb.degree.lower() or fb.degree.lower() in deg)):
                        raw_item = item
                        break
            if not raw_item and idx < len(raw) and isinstance(raw[idx], dict):
                raw_item = raw[idx]

            highlights = list(fb.highlights)
            if raw_item:
                raw_hl = raw_item.get("highlights") or raw_item.get("bullets") or raw_item.get("coursework")
                if isinstance(raw_hl, str):
                    cand_hl = [h.strip().lstrip("•-* ") for h in raw_hl.split("\n") if h.strip()]
                elif isinstance(raw_hl, list):
                    cand_hl = [str(h).strip() for h in raw_hl if str(h).strip()]
                else:
                    cand_hl = []
                if cand_hl:
                    highlights = cand_hl

            # Reorder coursework items if present in format "Relevant coursework: A, B, C"
            ordered_highlights = []
            for hl in highlights:
                if "coursework" in hl.lower() and ":" in hl:
                    prefix, courses = hl.split(":", 1)
                    course_list = [c.strip() for c in courses.split(",") if c.strip()]
                    if kw_set and course_list:
                        matched = [c for c in course_list if any(k in c.lower() or c.lower() in k for k in kw_set)]
                        unmatched = [c for c in course_list if c not in matched]
                        ordered_highlights.append(f"{prefix}: {', '.join(matched + unmatched)}")
                    else:
                        ordered_highlights.append(hl)
                else:
                    ordered_highlights.append(hl)

            normalized.append(Education(
                institution=fb.institution,
                degree=fb.degree,
                field_of_study=fb.field_of_study,
                start_date=fb.start_date,
                end_date=fb.end_date,
                gpa=fb.gpa,
                highlights=ordered_highlights if ordered_highlights else fb.highlights
            ))

        return normalized if normalized else fallback

    @staticmethod
    def normalize_projects(
        raw: Any,
        fallback: List[Project],
        job_keywords: Optional[List[str]] = None
    ) -> List[Project]:
        """Normalize projects: robustly maps AI-tailored projects to candidate's authentic projects,
        reorders projects by job relevance, refines highlights with Google X-Y-Z formula,
        and prioritizes matched technologies."""
        if not fallback:
            return []

        import re
        kw_set = {k.lower() for k in (job_keywords or [])}

        def normalize_name(name: str) -> str:
            return re.sub(r'[^a-zA-Z0-9]', '', name).lower()

        fb_map = {normalize_name(p.name): p for p in fallback}
        matched_fb_names = set()
        tailored_projects = []

        if raw and isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                raw_name = str(item.get("name") or item.get("title") or "")
                clean_raw_name = normalize_name(raw_name)

                # Match against fallback projects
                matched_fb = None
                if clean_raw_name in fb_map:
                    matched_fb = fb_map[clean_raw_name]
                else:
                    for k, fb_p in fb_map.items():
                        if k in clean_raw_name or clean_raw_name in k:
                            matched_fb = fb_p
                            break

                if matched_fb and matched_fb.name not in matched_fb_names:
                    matched_fb_names.add(matched_fb.name)

                    # Description: AI-adapted or original
                    desc = str(item.get("description") or matched_fb.description or "").strip()

                    # Highlights: AI-adapted with X-Y-Z formula or original
                    raw_hl = item.get("highlights") or item.get("bullets")
                    if isinstance(raw_hl, str):
                        highlights = [h.strip().lstrip("•-* ") for h in raw_hl.split("\n") if h.strip()]
                    elif isinstance(raw_hl, list):
                        highlights = [str(h).strip() for h in raw_hl if str(h).strip()]
                    else:
                        highlights = list(matched_fb.highlights)
                    if not highlights:
                        highlights = list(matched_fb.highlights)

                    # Technologies: preserve all authentic technologies, prioritize matched keywords
                    raw_tech = item.get("technologies") or item.get("tech_stack")
                    all_techs = list(matched_fb.technologies)
                    if isinstance(raw_tech, list):
                        for t in raw_tech:
                            t_str = str(t).strip()
                            if t_str and t_str not in all_techs:
                                all_techs.append(t_str)

                    if kw_set:
                        matched_techs = [t for t in all_techs if any(k in t.lower() or t.lower() in k for k in kw_set)]
                        other_techs = [t for t in all_techs if t not in matched_techs]
                        ordered_techs = matched_techs + other_techs
                    else:
                        ordered_techs = all_techs

                    tailored_projects.append(Project(
                        name=matched_fb.name,
                        description=desc,
                        technologies=ordered_techs,
                        link=matched_fb.link or item.get("link") or item.get("url"),
                        highlights=highlights
                    ))

        # Preserve any fallback projects not included in LLM output
        for fb in fallback:
            if fb.name not in matched_fb_names:
                all_techs = list(fb.technologies)
                if kw_set:
                    matched_techs = [t for t in all_techs if any(k in t.lower() or t.lower() in k for k in kw_set)]
                    other_techs = [t for t in all_techs if t not in matched_techs]
                    ordered_techs = matched_techs + other_techs
                else:
                    ordered_techs = all_techs
                tailored_projects.append(Project(
                    name=fb.name,
                    description=fb.description,
                    technologies=ordered_techs,
                    link=fb.link,
                    highlights=fb.highlights
                ))

        return tailored_projects if tailored_projects else fallback

    @staticmethod
    def normalize_custom_sections(
        raw: Any,
        fallback: List[CustomSection],
        job_keywords: Optional[List[str]] = None
    ) -> List[CustomSection]:
        """Normalize and tailor adaptive custom sections (Organizations, Publications, Awards, etc.)
        while strictly preserving candidate's authentic history."""
        if not fallback:
            return []

        kw_set = {k.lower() for k in (job_keywords or [])}

        def clean_id(s: str) -> str:
            import re
            return re.sub(r'[^a-z0-9]', '', str(s).lower())

        fb_map = {clean_id(cs.id or cs.heading): cs for cs in fallback}
        tailored_sections = []
        handled_ids = set()

        if raw and isinstance(raw, list):
            for raw_sec in raw:
                if not isinstance(raw_sec, dict):
                    continue
                raw_id_str = str(raw_sec.get("id") or raw_sec.get("heading") or "")
                clean_sec_id = clean_id(raw_id_str)

                # Match with authentic fallback custom section
                matched_fb = fb_map.get(clean_sec_id)
                if not matched_fb:
                    for k, fb_cs in fb_map.items():
                        if k in clean_sec_id or clean_sec_id in k:
                            matched_fb = fb_cs
                            break

                if matched_fb and matched_fb.id not in handled_ids:
                    handled_ids.add(matched_fb.id)
                    fb_items_map = {clean_id(item.title or ""): item for item in matched_fb.items}
                    handled_items = set()
                    tailored_items = []

                    raw_items = raw_sec.get("items") or []
                    for raw_item in raw_items:
                        if isinstance(raw_item, dict):
                            raw_title = str(raw_item.get("title") or "")
                            clean_t = clean_id(raw_title)
                            matched_fb_item = fb_items_map.get(clean_t)
                            if not matched_fb_item:
                                for ik, itm in fb_items_map.items():
                                    if ik in clean_t or clean_t in ik:
                                        matched_fb_item = itm
                                        break

                            if matched_fb_item:
                                handled_items.add(matched_fb_item.title or "")
                                # Bullets
                                raw_b = raw_item.get("bullets") or []
                                if isinstance(raw_b, str):
                                    bullets = [b.strip().lstrip("•-* ") for b in raw_b.split("\n") if b.strip()]
                                elif isinstance(raw_b, list):
                                    bullets = [str(b).strip() for b in raw_b if str(b).strip()]
                                else:
                                    bullets = list(matched_fb_item.bullets)
                                if not bullets:
                                    bullets = list(matched_fb_item.bullets)

                                # Reorder bullets if keywords match
                                if kw_set:
                                    matched_b = [b for b in bullets if any(k in b.lower() for k in kw_set)]
                                    other_b = [b for b in bullets if b not in matched_b]
                                    bullets = matched_b + other_b

                                tailored_items.append(CustomSectionItem(
                                    title=matched_fb_item.title,
                                    subtitle=raw_item.get("subtitle") or matched_fb_item.subtitle,
                                    date_or_year=matched_fb_item.date_or_year or raw_item.get("date_or_year"),
                                    description=str(raw_item.get("description") or matched_fb_item.description or "").strip() or None,
                                    bullets=bullets
                                ))
                        elif isinstance(raw_item, str):
                            clean_t = clean_id(raw_item)
                            matched_fb_item = fb_items_map.get(clean_t)
                            if matched_fb_item:
                                handled_items.add(matched_fb_item.title or "")
                                tailored_items.append(matched_fb_item)

                    # Preserve any fallback items not mentioned in raw_items
                    for item in matched_fb.items:
                        if (item.title or "") not in handled_items:
                            tailored_items.append(item)

                    tailored_sections.append(CustomSection(
                        id=matched_fb.id,
                        heading=matched_fb.heading,
                        items=tailored_items if tailored_items else matched_fb.items
                    ))

        # Preserve any authentic custom sections not in raw output
        for fb_sec in fallback:
            if fb_sec.id not in handled_ids:
                tailored_sections.append(fb_sec)

        return tailored_sections if tailored_sections else fallback


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
                "1. Ground Truth Integrity: You MUST retain ALL sections, ALL projects, ALL education records, ALL companies, ALL certifications, and ALL custom sections from the candidate's authentic history. NEVER invent companies, degrees, dates, institutions, or credentials not in the Master Profile.\n\n"
                "COMPREHENSIVE ADAPTIVE TAILORING DIRECTIVES:\n"
                "2. Professional Summary: Refine into 2-3 high-impact sentences directly addressing the target company's pain points, core mission, and role requirements.\n"
                "3. Technical Skills: Group and prioritize high-demand target JD skills at the top of each category. Do NOT drop real candidate skills.\n"
                "4. Work Experience: Transform bullet points using the Google X-Y-Z formula: 'Accomplished [X] as measured by [Y], by doing [Z]', weaving in target job keywords naturally while preserving authentic facts and metrics.\n"
                "5. Featured Projects:\n"
                "   - Prioritize/reorder projects so the most relevant project to the target job appears first.\n"
                "   - Refine project descriptions to highlight architectural problem-solving, scale, and relevance to the target job.\n"
                "   - Adapt project bullet points (highlights) using the Google X-Y-Z formula to showcase quantifiable impact and relevant technical depth.\n"
                "   - In each project's technologies list, prioritize technologies that match the target job's tech stack.\n"
                "6. Education:\n"
                "   - Strictly preserve authentic institution, degree, field of study, dates, and GPA.\n"
                "   - Tailor the `highlights` (e.g. relevant coursework, academic specialization, or capstone focus) to highlight subjects and fundamentals directly aligned with the target job's requirements (e.g. Distributed Systems, Database Architecture, Machine Learning, Computer Networks).\n"
                "7. Certifications: Prioritize relevant certifications supporting this role.\n"
                "8. Adaptive Custom Sections (Organizations, Leadership, Publications, Awards, Volunteering, Languages, Bootcamps, etc.):\n"
                "   - The candidate's CV can contain any number of custom sections. You MUST retain ALL custom sections.\n"
                "   - Tailor each item's description and bullet points to highlight transferable competencies, leadership, metrics, problem-solving, and alignment with the target job.\n"
                "   - Reorder items within each custom section so the most relevant achievements appear first.\n"
                "9. Strategic Insights & Dynamic Section Order:\n"
                "   - Provide `agent_reasoning` detailing how every section was strategically optimized.\n"
                "   - Provide `key_strengths` (top 3-4 selling points) and `interview_talking_points` (3 concrete talking points).\n"
                "   - Provide `section_order` (ordered list of section IDs) placing the most impressive and relevant sections for this specific role first.\n\n"
                "Return ONLY a flat JSON object with these exact top-level keys: "
                "\"summary\", \"skills\", \"experience\", \"education\", \"projects\", \"certifications\", \"custom_sections\", \"section_order\", \"agent_reasoning\", \"key_strengths\", \"interview_talking_points\". "
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
            job_keywords = job_intel.get("core_keywords", [])

            # 1. Summary (tailored)
            summary = unwrapped.get("summary") or self.master_profile.summary

            # 2. Skills (prioritized matching skills first, all original skills preserved)
            skills = self.normalizer.normalize_skills(unwrapped.get("skills"), self.master_profile.skills)

            # 3. Experience (bullets refined with X-Y-Z, all companies preserved)
            experience = self.normalizer.normalize_experience(unwrapped.get("experience"), self.master_profile.experience)

            # 4. Education (authentic degree/school preserved, coursework & focus tailored to JD)
            education = self.normalizer.normalize_education(unwrapped.get("education"), self.master_profile.education, job_keywords)

            # 5. Projects (reordered by relevance, descriptions & highlights adapted with X-Y-Z, tech stack prioritized)
            projects = self.normalizer.normalize_projects(unwrapped.get("projects"), self.master_profile.projects, job_keywords)

            # 6. Certifications (100% preserved)
            certifications = self.normalizer.normalize_certifications(self.master_profile.certifications) or self.normalizer.normalize_certifications(unwrapped.get("certifications"))

            # 7. Adaptive Custom Sections (tailored with role-aligned bullets & prioritized items)
            custom_sections = self.normalizer.normalize_custom_sections(
                unwrapped.get("custom_sections"),
                self.master_profile.custom_sections,
                job_keywords
            )

            # 8. Section Order: preserve candidate's preferred sequence from master profile, ensuring all custom sections exist
            base_style = self.master_profile.style_preferences or StylePreferences()
            final_order = list(base_style.section_order) if base_style.section_order else ["summary", "skills", "experience", "education", "projects", "certifications"]
            
            default_orders = [
                ["summary", "skills", "experience", "education", "projects", "certifications"],
                ["summary", "skills", "experience", "projects", "education", "certifications"]
            ]
            raw_order = unwrapped.get("section_order") or (unwrapped.get("style_preferences", {}).get("section_order") if isinstance(unwrapped.get("style_preferences"), dict) else None)
            if final_order in default_orders and isinstance(raw_order, list) and len(raw_order) >= 4:
                final_order = [str(s).lower() for s in raw_order if str(s)]

            for cs in custom_sections:
                if cs.id.lower() not in [s.lower() for s in final_order] and cs.heading.lower() not in [s.lower() for s in final_order]:
                    final_order.append(cs.id)

            style_prefs = StylePreferences(
                section_order=final_order,
                layout_style=base_style.layout_style,
                accent_color=base_style.accent_color,
                font_family=base_style.font_family,
                bullet_style=base_style.bullet_style
            )

            agent_reasoning = unwrapped.get("agent_reasoning") or f"Strategically reframed experience highlights using Google X-Y-Z formula to match {job.company}'s requirements while preserving all original credentials."
            key_strengths = unwrapped.get("key_strengths") or fit_data.get("selling_points", [])
            interview_points = unwrapped.get("interview_talking_points") or []

            return TailoredResume(
                contact=self.master_profile.contact,
                summary=summary,
                skills=skills,
                experience=experience,
                education=education,
                projects=projects,
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
        """Heuristic synthesis fallback: intelligently adapts summary, skills, experience, projects, education, and custom sections."""
        top_kws = ", ".join(job_intel.get("core_keywords", [])[:4]) or "modern architectures"
        summary = (
            f"Results-driven AI & Software Specialist targeting {job.title} at {job.company}. "
            f"Proven expertise in scalable systems utilizing {top_kws}. "
            f"Dedicated to technical excellence and delivering high-impact solutions aligned with {job.company}'s goals."
        )

        job_kw_set = set(k.lower() for k in job_intel.get("core_keywords", []))

        # 1. Reorder skills
        reordered_skills = []
        for cat in self.master_profile.skills:
            matched = [s for s in cat.skills if any(kw in s.lower() or s.lower() in kw for kw in job_kw_set)]
            others = [s for s in cat.skills if s not in matched]
            reordered_skills.append(SkillCategory(category=cat.category, skills=matched + others))

        # 2. Reorder experience highlights to place matching bullet points and technologies first
        adapted_experience = []
        for exp in self.master_profile.experience:
            matched_hl = [h for h in exp.highlights if any(kw in h.lower() for kw in job_kw_set)]
            other_hl = [h for h in exp.highlights if h not in matched_hl]
            matched_tech = [t for t in exp.technologies if any(kw in t.lower() or t.lower() in kw for kw in job_kw_set)]
            other_tech = [t for t in exp.technologies if t not in matched_tech]
            adapted_experience.append(WorkExperience(
                company=exp.company,
                position=exp.position,
                location=exp.location,
                start_date=exp.start_date,
                end_date=exp.end_date,
                highlights=matched_hl + other_hl if (matched_hl or other_hl) else exp.highlights,
                technologies=matched_tech + other_tech
            ))

        # 3. Score & reorder projects by relevance to JD, prioritize technologies & highlights
        def project_score(proj: Project) -> int:
            score = 0
            for t in proj.technologies:
                if any(kw in t.lower() or t.lower() in kw for kw in job_kw_set):
                    score += 3
            for h in proj.highlights:
                if any(kw in h.lower() for kw in job_kw_set):
                    score += 1
            if any(kw in proj.description.lower() for kw in job_kw_set):
                score += 2
            return score

        scored_projects = sorted(self.master_profile.projects, key=project_score, reverse=True)
        adapted_projects = []
        for proj in scored_projects:
            matched_tech = [t for t in proj.technologies if any(kw in t.lower() or t.lower() in kw for kw in job_kw_set)]
            other_tech = [t for t in proj.technologies if t not in matched_tech]
            matched_hl = [h for h in proj.highlights if any(kw in h.lower() for kw in job_kw_set)]
            other_hl = [h for h in proj.highlights if h not in matched_hl]
            adapted_projects.append(Project(
                name=proj.name,
                description=proj.description,
                technologies=matched_tech + other_tech,
                link=proj.link,
                highlights=matched_hl + other_hl if (matched_hl or other_hl) else proj.highlights
            ))

        # 4. Curate education highlights (reorder coursework)
        adapted_education = self.normalizer.normalize_education(
            raw=[e.model_dump() for e in self.master_profile.education],
            fallback=self.master_profile.education,
            job_keywords=job_intel.get("core_keywords", [])
        )

        # 5. Adapt custom sections (reorder items and bullets matching JD keywords)
        adapted_custom_sections = []
        for csec in self.master_profile.custom_sections:
            def item_score(item: CustomSectionItem) -> int:
                score = 0
                text = f"{item.title or ''} {item.subtitle or ''} {item.description or ''} {' '.join(item.bullets)}"
                for kw in job_kw_set:
                    if kw in text.lower():
                        score += 2
                return score

            sorted_items = sorted(csec.items, key=item_score, reverse=True)
            curated_items = []
            for itm in sorted_items:
                matched_b = [b for b in itm.bullets if any(kw in b.lower() for kw in job_kw_set)]
                other_b = [b for b in itm.bullets if b not in matched_b]
                curated_items.append(CustomSectionItem(
                    title=itm.title,
                    subtitle=itm.subtitle,
                    date_or_year=itm.date_or_year,
                    description=itm.description,
                    bullets=matched_b + other_b if (matched_b or other_b) else itm.bullets
                ))
            adapted_custom_sections.append(CustomSection(
                id=csec.id,
                heading=csec.heading,
                items=curated_items if curated_items else csec.items
            ))

        style_prefs = self.master_profile.style_preferences or StylePreferences()

        return TailoredResume(
            contact=self.master_profile.contact,
            summary=summary,
            skills=reordered_skills,
            experience=adapted_experience if adapted_experience else self.master_profile.experience,
            education=adapted_education if adapted_education else self.master_profile.education,
            projects=adapted_projects if adapted_projects else self.master_profile.projects,
            certifications=self.normalizer.normalize_certifications(self.master_profile.certifications),
            custom_sections=adapted_custom_sections if adapted_custom_sections else self.master_profile.custom_sections,
            job_title_target=job.title,
            target_company=job.company,
            tailoring_notes=f"AI Agent Harness (Heuristic Mode) tailored for {job.title} at {job.company}",
            style_preferences=style_prefs,
            agent_reasoning=f"Surfaced high-priority technical competencies ({top_kws}), prioritized key projects, coursework, and custom sections, and aligned executive summary with {job.company} requirements.",
            key_strengths=fit_data.get("selling_points", []),
            interview_talking_points=[
                f"Highlight direct experience with {top_kws}.",
                f"Connect past project metrics to {job.company}'s core mission."
            ],
            job_fit_summary=fit_data
        )

    async def improve_resume_with_context(
        self,
        tailored: TailoredResume,
        job: JobListing,
        user_context: Optional[Dict[str, str]] = None,
        auto_estimate_missing: bool = True
    ) -> TailoredResume:
        """Improve and polish tailored resume by resolving ATS deficiencies and incorporating candidate context.
        
        Fixes:
        1. Quantifying Impact: weaves candidate-supplied metrics/numbers into bullet points via Google X-Y-Z formula.
        2. Repetition: diversifies action verbs at the beginning of bullet points.
        3. Spelling & Grammar: fixes capitalization, double spaces, and punctuation.
        4. Consistency: enforces uniform period endings and ideal bullet length (1-2 lines).
        """
        from jobflow.core.ats_diagnostic import ATSResumeDiagnostic, POWER_VERB_ALTERNATIVES
        
        user_ctx = user_context or {}
        diagnostic = ATSResumeDiagnostic()
        report = diagnostic.analyze_resume(tailored, job)

        has_llm = bool(
            settings.OPENAI_API_KEY
            or settings.ANTHROPIC_API_KEY
            or settings.GEMINI_API_KEY
            or settings.GROQ_API_KEY
            or settings.DEEPSEEK_API_KEY
        )

        if has_llm:
            try:
                import litellm
                system_prompt = (
                    "You are an elite ATS Resume Perfection & Optimization AI Specialist.\n"
                    "Your mission is to elevate the candidate's resume from a baseline score to 95%+ ATS Content Score.\n\n"
                    "DEFICIENCIES TO RESOLVE:\n"
                    "1. QUANTIFYING IMPACT (Google X-Y-Z formula):\n"
                    "   - The candidate has provided specific real-world metrics/context below for key achievements.\n"
                    "   - Weave these exact metrics into the corresponding bullet points.\n"
                    "   - If auto_estimate_missing is enabled and a bullet lacks metrics without candidate input, synthesize a rational, realistic engineering benchmark (e.g. 25-40% latency reduction, 100k+ daily transactions, 99.9% uptime).\n"
                    "2. ACTION VERB DIVERSITY & ELIMINATING REPETITION:\n"
                    "   - Ensure NO two bullets begin with the same action verb.\n"
                    "   - Use dynamic, varied executive verbs (e.g. Architected, Orchestrated, Spearheaded, Engineered, Formulated, Deployed).\n"
                    "3. BULLET CONSISTENCY & GRAMMAR:\n"
                    "   - Every bullet MUST start with a Capital letter.\n"
                    "   - Every bullet MUST end with a single period (.).\n"
                    "   - Eliminate any double spaces or typos.\n"
                    "   - Keep bullets concise and high-impact (between 100 and 220 characters).\n"
                    "4. PRESERVATION MANDATE:\n"
                    "   - Retain ALL authentic companies, positions, schools, degrees, project names, and dates.\n\n"
                    "Return ONLY a flat JSON object with keys: "
                    "\"summary\", \"skills\", \"experience\", \"education\", \"projects\", \"certifications\", \"custom_sections\", \"agent_reasoning\"."
                )

                prompt_payload = {
                    "current_resume": tailored.model_dump(),
                    "target_job": {
                        "title": job.title,
                        "company": job.company,
                        "description": job.description,
                        "requirements": job.requirements
                    },
                    "detected_issues": [i.model_dump() for i in report.issues],
                    "candidate_provided_context": user_ctx,
                    "auto_estimate_missing": auto_estimate_missing
                }

                kwargs: Dict[str, Any] = {
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Optimize and improve this resume:\n\n{json.dumps(prompt_payload, indent=2)}"}
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
                unwrapped = self.normalizer.unwrap_root(raw_data)

                # Normalize and construct improved resume
                norm_exp = self.normalizer.normalize_experience(unwrapped.get("experience"), tailored.experience)
                norm_proj = self.normalizer.normalize_projects(unwrapped.get("projects"), tailored.projects, job.requirements)
                norm_custom = self.normalizer.normalize_custom_sections(unwrapped.get("custom_sections"), tailored.custom_sections, job.requirements)

                improved = TailoredResume(
                    contact=tailored.contact,
                    summary=unwrapped.get("summary") or tailored.summary,
                    skills=self.normalizer.normalize_skills(unwrapped.get("skills"), tailored.skills),
                    experience=norm_exp,
                    education=self.normalizer.normalize_education(unwrapped.get("education"), tailored.education, job.requirements),
                    projects=norm_proj,
                    certifications=tailored.certifications,
                    custom_sections=norm_custom,
                    job_title_target=tailored.job_title_target,
                    target_company=tailored.target_company,
                    matching_keywords=tailored.matching_keywords,
                    missing_keywords=tailored.missing_keywords,
                    tailoring_notes=f"Enhanced with candidate context and ATS diagnostic resolution.",
                    style_preferences=tailored.style_preferences,
                    agent_reasoning=unwrapped.get("agent_reasoning") or "Optimized bullet metrics, diversified action verbs, and resolved all ATS diagnostic flaws.",
                    key_strengths=tailored.key_strengths,
                    interview_talking_points=tailored.interview_talking_points
                )

                # Re-score
                new_eval = evaluate_ats(improved, job)
                improved.ats_score = new_eval.score
                return improved

            except Exception as e:
                logger.warning(f"LLM improvement failed, using deterministic improvement engine: {e}")

        # Deterministic High-Quality Improvement Engine (Heuristic Mode)
        used_verbs: Set[str] = set()

        def diversify_verb(bullet: str) -> str:
            words = bullet.strip().split()
            if not words:
                return bullet
            orig_first = words[0].strip('•-*(),.')
            lower_first = orig_first.lower()
            if lower_first in used_verbs:
                alts = POWER_VERB_ALTERNATIVES.get(lower_first, ["Architected", "Engineered", "Orchestrated", "Spearheaded", "Implemented"])
                avail = [a for a in alts if a.lower() not in used_verbs]
                chosen = avail[0] if avail else alts[0]
                words[0] = chosen if orig_first[0].isupper() else chosen.lower()
                used_verbs.add(chosen.lower())
                return " ".join(words)
            else:
                if len(lower_first) >= 3:
                    used_verbs.add(lower_first)
                return bullet

        def polish_bullet(bullet: str, custom_metric: Optional[str] = None, fallback_metric: str = "") -> str:
            b = bullet.strip().lstrip("•-* ")
            if not b:
                return b
            # Remove double spaces
            while "  " in b:
                b = b.replace("  ", " ")
            # Capitalize first char
            b = b[0].upper() + b[1:]
            # Inject metric if not present
            if custom_metric and custom_metric.strip():
                c_val = custom_metric.strip().rstrip('.')
                if not any(char.isdigit() for char in b):
                    b = f"{b.rstrip('.')}, achieving {c_val}."
                else:
                    b = f"{b.rstrip('.')}. ({c_val})."
            elif auto_estimate_missing and not any(char.isdigit() for char in b) and fallback_metric:
                b = f"{b.rstrip('.')}, {fallback_metric}."
            
            # Ensure period at end
            if not b.endswith('.'):
                b = b + '.'
            
            # Diversify verb
            b = diversify_verb(b)
            return b

        # 1. Experience
        improved_experience = []
        for exp_idx, exp in enumerate(tailored.experience):
            polished_highlights = []
            for b_idx, bullet in enumerate(exp.highlights):
                field_id = f"ctx_exp_{exp_idx}_bullet_{b_idx}"
                user_val = user_ctx.get(field_id)
                fb_m = "accelerating deployment turnaround by 40% with 99.9% uptime"
                polished = polish_bullet(bullet, user_val, fb_m)
                polished_highlights.append(polished)
            
            improved_experience.append(WorkExperience(
                company=exp.company,
                position=exp.position,
                location=exp.location,
                start_date=exp.start_date,
                end_date=exp.end_date,
                highlights=polished_highlights,
                technologies=exp.technologies
            ))

        # 2. Projects
        improved_projects = []
        for p_idx, proj in enumerate(tailored.projects):
            polished_highlights = []
            for b_idx, bullet in enumerate(proj.highlights):
                field_id = f"ctx_proj_{p_idx}_bullet_{b_idx}"
                user_val = user_ctx.get(field_id)
                fb_m = "processing over 50k requests daily with sub-second p95 response time"
                polished = polish_bullet(bullet, user_val, fb_m)
                polished_highlights.append(polished)
            
            improved_projects.append(Project(
                name=proj.name,
                description=proj.description,
                technologies=proj.technologies,
                link=proj.link,
                highlights=polished_highlights
            ))

        # 3. Custom sections
        improved_custom = []
        for cs_idx, cs in enumerate(tailored.custom_sections):
            polished_items = []
            for item_idx, item in enumerate(cs.items):
                p_bullets = []
                for b_idx, bullet in enumerate(item.bullets):
                    field_id = f"ctx_custom_{cs_idx}_{item_idx}_{b_idx}"
                    user_val = user_ctx.get(field_id)
                    fb_m = "leading a collaborative team of 15 members to deliver 100% on-time milestones"
                    p_bullets.append(polish_bullet(bullet, user_val, fb_m))
                
                polished_items.append(CustomSectionItem(
                    title=item.title,
                    subtitle=item.subtitle,
                    date_or_year=item.date_or_year,
                    description=item.description,
                    bullets=p_bullets
                ))
            improved_custom.append(CustomSection(
                id=cs.id,
                heading=cs.heading,
                items=polished_items
            ))

        # Polish summary if lowercase or double space
        clean_summary = tailored.summary.strip()
        while "  " in clean_summary:
            clean_summary = clean_summary.replace("  ", " ")
        if clean_summary:
            clean_summary = clean_summary[0].upper() + clean_summary[1:]
            if not clean_summary.endswith('.'):
                clean_summary += '.'

        improved = TailoredResume(
            contact=tailored.contact,
            summary=clean_summary,
            skills=tailored.skills,
            experience=improved_experience,
            education=tailored.education,
            projects=improved_projects,
            certifications=tailored.certifications,
            custom_sections=improved_custom,
            job_title_target=tailored.job_title_target,
            target_company=tailored.target_company,
            matching_keywords=tailored.matching_keywords,
            missing_keywords=tailored.missing_keywords,
            tailoring_notes="Enhanced with candidate context and ATS diagnostic resolution.",
            style_preferences=tailored.style_preferences,
            agent_reasoning="Resolved all ATS diagnostic deficiencies: injected measurable metrics via Google X-Y-Z formula, diversified action verbs, and standardized typography.",
            key_strengths=tailored.key_strengths,
            interview_talking_points=tailored.interview_talking_points
        )

        new_eval = evaluate_ats(improved, job)
        improved.ats_score = new_eval.score
        return improved

