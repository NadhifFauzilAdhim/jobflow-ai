"""Autonomous Job Discovery and Relevance Evaluation Harness.

Orchestrates:
1. ProfileQuerySynthesizer: Analyzes candidate CV to derive target roles, primary tech stack, and location.
2. MultiPlatformJobScraper: Harvests candidate listings across JobStreet, LinkedIn, Glints, and RemoteOK.
3. JobRelevanceEvaluator: Strict compatibility filter scoring domain fit, tech stack overlap, and seniority.
4. PipelinePersister: Deduplicates and commits high-relevance listings into the database.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from jobflow.core.schema import MasterProfile, JobListing, ApplicationStatus
from jobflow.core.ats_scorer import extract_keywords
from jobflow.extractors.platform_scrapers import MultiPlatformJobScraper
from jobflow.db.models import JobApplicationRecord

logger = logging.getLogger("jobflow.discovery_harness")

# Default negative role keywords for tech/engineering candidate baseline
DEFAULT_IRRELEVANT_KEYWORDS = {
    "accountant", "accounting", "auditor", "finance", "tax", "payroll",
    "marketing", "sales", "telemarketing", "seo specialist", "content writer",
    "graphic designer", "ui/ux only", "illustrator", "video editor", "animator",
    "customer service", "call center", "telemarketer", "cashier", "admin operational",
    "nurse", "doctor", "medical", "civil engineer", "mechanical maintenance",
    "legal", "attorney", "lawyer", "human resources", "recruiter", "talent acquisition"
}


@dataclass
class RelevanceResult:
    is_relevant: bool
    relevance_score: float
    rationale: str
    matched_skills: List[str]
    breakdown: Dict[str, float] = field(default_factory=dict)
    disqualification_reasons: List[str] = field(default_factory=list)

    def __iter__(self):
        return iter((self.is_relevant, self.relevance_score, self.rationale, self.matched_skills))

    def __getitem__(self, index):
        return (self.is_relevant, self.relevance_score, self.rationale, self.matched_skills)[index]


class ProfileQuerySynthesizer:
    """Synthesizes targeted search queries, tech terms, and location preferences from candidate CV."""

    @staticmethod
    def extract_search_criteria(profile: MasterProfile) -> Dict[str, Any]:
        """Extract primary target job titles, core skills, and location preferences."""
        detected_titles: List[str] = []
        
        # 1. From experience roles
        for exp in profile.experience:
            pos_val = getattr(exp, "position", None) or getattr(exp, "title", "")
            if not pos_val:
                continue
            clean_title = pos_val.strip()
            # Normalize title e.g. "AI & Full-Stack Developer" -> "AI Engineer", "Full-Stack Developer"
            sub_titles = [t.strip() for t in re.split(r"[/|&•,]+", clean_title) if len(t.strip()) > 3]
            for st in sub_titles:
                # Normalize title variations
                norm = re.sub(r"\b(junior|senior|lead|intern|part-time|full-time)\b", "", st, flags=re.IGNORECASE).strip()
                if norm and norm.lower() not in [d.lower() for d in detected_titles]:
                    detected_titles.append(norm)

        # 2. From summary if few titles found
        if len(detected_titles) < 2 and profile.summary:
            match = re.search(r"([A-Za-z\s]+(?:Engineer|Developer|Architect|Scientist|Specialist))", profile.summary)
            if match:
                t = match.group(1).strip()
                if t.lower() not in [d.lower() for d in detected_titles]:
                    detected_titles.append(t)

        # Fallback default if completely empty
        if not detected_titles:
            detected_titles = ["Software Engineer", "Backend Developer", "Full Stack Developer"]

        # 3. Core Tech Stack (Top 12 skills)
        flat_skills: List[str] = []
        for cat in profile.skills:
            flat_skills.extend(cat.skills)
        if not flat_skills:
            flat_skills = ["Python", "FastAPI", "PostgreSQL", "Docker", "REST API", "Git"]

        # 4. Preferred Location
        loc = "Indonesia"
        if profile.contact and profile.contact.location:
            parts = [p.strip() for p in profile.contact.location.split(",")]
            loc = parts[0] if parts else "Indonesia"

        # Seniority level determination
        seniority = "Mid"
        all_text = f"{profile.summary} {' '.join(getattr(e, 'position', '') for e in profile.experience)}".lower()
        if any(w in all_text for w in ["lead", "principal", "staff", "head of", "director"]):
            seniority = "Lead"
        elif any(w in all_text for w in ["senior", "sr.", "sr "]):
            seniority = "Senior"
        elif any(w in all_text for w in ["junior", "jr.", "intern"]):
            seniority = "Junior"

        return {
            "target_titles": detected_titles[:4],
            "target_roles": detected_titles[:4],
            "primary_skills": flat_skills[:12],
            "core_skills": flat_skills[:12],
            "location": loc,
            "candidate_name": profile.contact.full_name if profile.contact else "Candidate",
            "seniority_level": seniority,
            "search_queries": [f"{t} {loc}".strip() for t in detected_titles[:3]]
        }


class JobRelevanceEvaluator:
    """Strict relevance evaluator scoring job compatibility against candidate ground truth."""

    def __init__(self, profile: MasterProfile, min_relevance_threshold: float = 60.0):
        self.profile = profile
        self.min_relevance_threshold = min_relevance_threshold

        # Pre-extract candidate skill set for O(1) comparison
        self.candidate_skills_lower = set()
        self.canonical_skill_map = {}
        for cat in profile.skills:
            for s in cat.skills:
                s_stripped = s.strip()
                self.candidate_skills_lower.add(s_stripped.lower())
                self.canonical_skill_map[s_stripped.lower()] = s_stripped

        # Collect target title terms
        criteria = ProfileQuerySynthesizer.extract_search_criteria(profile)
        self.target_titles = [t.lower() for t in criteria["target_titles"]]

    def evaluate(self, job: JobListing, min_threshold: Optional[float] = None) -> RelevanceResult:
        """
        Evaluate scraped job listing against candidate profile.
        Returns: RelevanceResult containing score, rationale, breakdown, and matched skills.
        """
        threshold = min_threshold if min_threshold is not None else self.min_relevance_threshold
        title_lower = job.title.lower().strip()
        job_body = f"{job.title} {job.description} {' '.join(job.requirements)}".lower()

        # 1. Negative Keyword Rejection Guard (0% Score)
        for neg in DEFAULT_IRRELEVANT_KEYWORDS:
            if re.search(rf"\b{re.escape(neg)}\b", title_lower):
                if not any(tt in title_lower for tt in ["engineer", "developer", "programmer", "architect", "scientist"]):
                    return RelevanceResult(
                        is_relevant=False,
                        relevance_score=15.0,
                        rationale=f"Discarded: Domain mismatch with candidate engineering profile ('{neg}' role).",
                        matched_skills=[],
                        breakdown={"domain_match": 0.0, "tech_stack_score": 0.0, "work_mode_score": 5.0, "seniority_score": 10.0},
                        disqualification_reasons=[f"Title contains negative keyword '{neg}'"]
                    )

        # 2. Title & Role Compatibility (Max 35 points)
        domain_match = 0.0
        title_matched = False
        for tt in self.target_titles:
            tt_words = set(tt.split())
            if tt in title_lower or len(tt_words.intersection(set(title_lower.split()))) >= 2:
                domain_match = 35.0
                title_matched = True
                break
        if not title_matched:
            if any(term in title_lower for term in ["developer", "engineer", "programmer", "tech lead"]):
                domain_match = 20.0
            else:
                domain_match = 5.0

        # 3. Tech Stack & Skill Overlap (Max 45 points)
        job_keywords = extract_keywords(job_body, max_keywords=30)
        matched_skills: List[str] = []

        for kw in job_keywords:
            kw_lower = kw.lower().strip()
            if kw_lower in self.candidate_skills_lower:
                canonical = self.canonical_skill_map.get(kw_lower, kw.title())
                if canonical not in matched_skills:
                    matched_skills.append(canonical)
            else:
                for cs_lower in self.candidate_skills_lower:
                    if kw_lower in cs_lower or cs_lower in kw_lower:
                        canonical = self.canonical_skill_map.get(cs_lower, kw.title())
                        if canonical not in matched_skills:
                            matched_skills.append(canonical)
                        break

        if matched_skills:
            tech_stack_score = min(45.0, len(matched_skills) * 9.0)
        else:
            tech_stack_score = 5.0

        # 4. Experience & Work Mode Alignment (Max 10 points)
        work_mode_score = 10.0 if any(term in (job.location or "").lower() for term in ["remote", "hybrid", "worldwide", "indonesia"]) else 5.0

        # 5. Seniority penalty check (Max 10 points)
        seniority_score = 10.0
        if any(term in title_lower for term in ["vp", "director", "head of", "principal"]) and not any("lead" in t for t in self.target_titles):
            seniority_score = 0.0

        raw_score = domain_match + tech_stack_score + work_mode_score + seniority_score
        final_score = min(100.0, round(raw_score, 1))
        is_relevant = final_score >= threshold

        disqualifications = []
        if not is_relevant:
            disqualifications.append(f"Score {final_score}% is below threshold {threshold}%")

        if is_relevant:
            top_matches = ", ".join(matched_skills[:4]) if matched_skills else "Domain alignment"
            rationale = f"Accepted: High compatibility ({final_score}%). Matched core competencies: {top_matches}."
        else:
            rationale = f"Discarded: Low profile alignment ({final_score}% vs threshold {threshold}%)."

        return RelevanceResult(
            is_relevant=is_relevant,
            relevance_score=final_score,
            rationale=rationale,
            matched_skills=matched_skills,
            breakdown={
                "domain_match": domain_match,
                "tech_stack_score": tech_stack_score,
                "work_mode_score": work_mode_score,
                "seniority_score": seniority_score
            },
            disqualification_reasons=disqualifications
        )

    def evaluate_job(self, job: JobListing) -> RelevanceResult:
        """Alias for evaluate compatible with unpacking and objects."""
        return self.evaluate(job, min_threshold=self.min_relevance_threshold)


class JobDiscoveryHarness:
    """End-to-End Autonomous Multi-Platform Job Scraping and Relevance Harness."""

    def __init__(self, master_profile: MasterProfile, db: AsyncSession):
        self.profile = master_profile
        self.db = db
        self.scraper = MultiPlatformJobScraper()

    async def execute_discovery(
        self,
        platforms: Optional[List[str]] = None,
        min_relevance: float = 60.0,
        max_jobs_to_save: int = 10,
        custom_queries: Optional[List[str]] = None,
        location: Optional[str] = None,
        log_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        progress_callback: Optional[Callable[[str, str], None]] = None
    ) -> Dict[str, Any]:
        """Execute autonomous discovery, AI relevance evaluation, and database persistence."""
        async def _log(msg: str, level: str = "info"):
            logger.info(f"[{level.upper()}] {msg}")
            if log_callback:
                try:
                    res = log_callback(msg, level)
                    if hasattr(res, "__await__"):
                        await res
                except Exception:
                    pass
            elif progress_callback:
                try:
                    progress_callback(msg, level)
                except Exception:
                    pass

        target_platforms = platforms or ["jobstreet", "linkedin", "glints", "remoteok"]
        await _log("[Discovery] Phase 1/4: Analyzing candidate profile and synthesizing queries...", "info")

        # 1. Synthesize queries from profile
        criteria = ProfileQuerySynthesizer.extract_search_criteria(self.profile)
        search_queries = custom_queries or criteria["target_titles"]
        search_loc = location or criteria["location"]

        await _log(f"[Discovery] Target roles: {', '.join(search_queries)} | Location: {search_loc}", "info")

        # 2. Multi-platform scraping
        await _log(f"[Discovery] Phase 2/4: Harvesting job postings across {', '.join(target_platforms)}...", "info")
        harvested_jobs = await self.scraper.search_across_platforms(
            queries=search_queries[:3],
            platforms=target_platforms,
            location=search_loc,
            limit_per_platform=4
        )

        await _log(f"[Discovery] Harvested {len(harvested_jobs)} unique listings across platforms.", "info")

        # 3. AI Relevance & Compatibility Filter
        await _log(f"[Discovery] Phase 3/4: Running AI Relevance Filter (Threshold: {min_relevance}%)...", "info")
        evaluator = JobRelevanceEvaluator(self.profile, min_relevance_threshold=min_relevance)

        accepted_jobs: List[Tuple[JobListing, float, str, List[str]]] = []
        discarded_count = 0

        for job in harvested_jobs:
            is_relevant, score, rationale, matches = evaluator.evaluate_job(job)
            if is_relevant:
                accepted_jobs.append((job, score, rationale, matches))
                await _log(f"[Accepted {score}%] {job.title} at {job.company} — {rationale}", "success")
            else:
                discarded_count += 1
                await _log(f"[Filtered Out] {job.title} at {job.company} — {rationale}", "warning")

        # Sort accepted by relevance score descending
        accepted_jobs.sort(key=lambda x: x[1], reverse=True)

        # 4. Pipeline Deduplication and Database Persistence
        await _log("[Discovery] Phase 4/4: Deduplicating and persisting relevant jobs to database...", "info")
        persisted_records: List[JobApplicationRecord] = []

        # Retrieve existing jobs for deduplication
        existing_res = await self.db.execute(select(JobApplicationRecord.title, JobApplicationRecord.company, JobApplicationRecord.url))
        existing_set = set()
        for r_title, r_company, r_url in existing_res.all():
            existing_set.add((r_title.lower().strip(), r_company.lower().strip()))
            if r_url:
                existing_set.add(r_url.strip())

        for job, score, rationale, matches in accepted_jobs[:max_jobs_to_save]:
            sig = (job.title.lower().strip(), job.company.lower().strip())
            url_sig = str(job.url).strip() if job.url else None

            if sig in existing_set or (url_sig and url_sig in existing_set):
                await _log(f"[Deduplicated] '{job.title}' at {job.company} already exists in pipeline.", "info")
                continue

            # Commit new job record
            db_record = JobApplicationRecord(
                title=job.title,
                company=job.company,
                location=job.location or "Remote / Hybrid",
                platform=job.platform.value if hasattr(job.platform, "value") else str(job.platform),
                url=str(job.url) if job.url else None,
                description=job.description,
                requirements=job.requirements,
                ats_score=score,
                matched_keywords=matches,
                status=ApplicationStatus.SAVED.value,
                logs=[{"step": "Job Discovery", "message": f"Auto-scraped & verified via AI Relevance Harness ({score}%). {rationale}"}]
            )
            self.db.add(db_record)
            existing_set.add(sig)
            if url_sig:
                existing_set.add(url_sig)
            persisted_records.append(db_record)

        await self.db.commit()
        for r in persisted_records:
            await self.db.refresh(r)

        saved_jobs_info = [
            {
                "id": r.id,
                "title": r.title,
                "company": r.company,
                "location": r.location,
                "platform": r.platform,
                "relevance_score": r.ats_score,
                "url": r.url
            }
            for r in persisted_records
        ]

        await _log(f"[Discovery Complete] Successfully added {len(saved_jobs_info)} verified relevant jobs to Target Applications pipeline! (Filtered {discarded_count} irrelevant).", "success")

        return {
            "status": "ok",
            "search_criteria": criteria,
            "harvested_count": len(harvested_jobs),
            "total_found": len(harvested_jobs),
            "accepted_count": len(accepted_jobs),
            "total_relevant": len(accepted_jobs),
            "discarded_count": discarded_count,
            "total_rejected": discarded_count,
            "persisted_count": len(saved_jobs_info),
            "jobs": saved_jobs_info,
            "saved_jobs": saved_jobs_info
        }
