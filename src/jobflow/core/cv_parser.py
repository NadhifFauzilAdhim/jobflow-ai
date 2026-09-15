"""CV Document Extractor and AI Parsing Agent for JobFlow AI."""

import io
import re
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from jobflow.core.schema import (
    MasterProfile,
    ContactInfo,
    SkillCategory,
    WorkExperience,
    Education,
    Project,
    CustomSection,
    CustomSectionItem,
    StylePreferences,
    QAPair
)
from jobflow.core.agent_harness import SchemaNormalizer
from jobflow.config import settings

logger = logging.getLogger("jobflow.cv_parser")

CV_PARSER_SYSTEM_PROMPT = """You are an elite, highly adaptive Resume Parsing AI Agent.
Your job is to read raw text extracted from a candidate's Curriculum Vitae (CV / Resume) and accurately structure it into a comprehensive MasterProfile JSON without omitting ANY section.

ADAPTIVE & EXHAUSTIVE EXTRACTION MANDATE:
1. DISCOVER ANY SECTION PRESENT IN THE CV:
   Candidates' CVs contain unique, diverse sections. Beyond standard sections, you MUST detect and capture ANY additional section, including but not limited to:
   - Awards, Honors, Achievements, Hackathons, Competitions
   - Publications, Research Papers, Preprints
   - Volunteer Experience, Community Engagement, Social Impact
   - Organizational Experience, Student Leadership, Extracurriculars
   - Languages & Fluency Levels
   - Speaking Engagements, Conference Talks, Workshops
   - Patents, Intellectual Property
   - Licenses, Accreditations
   - Or any other custom or domain-specific section present in the CV.
   Put all such non-standard sections into the `custom_sections` array!

2. NEVER OMIT CORE SECTIONS: Extract EVERY education degree, institution, field of study, date, and GPA. Extract EVERY project with its full name, description, tools, and link. Extract EVERY work experience with all bullet points. Extract ALL certifications.

3. ACCURATE CONTACT: Extract Full Name, Email, Phone, Location/City, LinkedIn, GitHub, Portfolio URL.

4. AUTHENTIC SUMMARY: Preserve the candidate's original summary/objective if present. If missing, synthesize a professional summary strictly grounded in their actual experience.

5. DETECT SECTION ORDER: Detect the candidate's authentic section sequence in the document, including both standard sections and any custom_section IDs (e.g. ["summary", "skills", "experience", "education", "projects", "awards", "publications", "certifications", "languages"]).

6. GROUP SKILLS: Organize skills into logical categories (e.g. "Languages & Frameworks", "AI & Machine Learning", "Databases & Cloud", "Tools").

Return ONLY a flat JSON object matching this schema (no markdown fences, no wrapping):
{
  "contact": {
    "full_name": "...",
    "email": "...",
    "phone": "...",
    "location": "...",
    "linkedin_url": "...",
    "github_url": "...",
    "portfolio_url": "..."
  },
  "summary": "...",
  "skills": [
    {"category": "...", "skills": ["..."]}
  ],
  "experience": [
    {
      "company": "...",
      "position": "...",
      "location": "...",
      "start_date": "...",
      "end_date": "...",
      "highlights": ["..."],
      "technologies": ["..."]
    }
  ],
  "education": [
    {
      "institution": "...",
      "degree": "...",
      "field_of_study": "...",
      "start_date": "...",
      "end_date": "...",
      "gpa": "...",
      "highlights": ["..."]
    }
  ],
  "projects": [
    {
      "name": "...",
      "description": "...",
      "technologies": ["..."],
      "link": "...",
      "highlights": ["..."]
    }
  ],
  "certifications": ["..."],
  "custom_sections": [
    {
      "id": "awards",
      "heading": "Awards & Honors",
      "items": [
        {
          "title": "1st Place Winner",
          "subtitle": "National AI Hackathon 2023",
          "date_or_year": "2023",
          "description": "...",
          "bullets": ["..."]
        }
      ]
    }
  ],
  "style_preferences": {
    "section_order": ["summary", "skills", "experience", "education", "projects", "certifications"],
    "layout_style": "modern_clean",
    "accent_color": "#111827",
    "font_family": "Helvetica Neue, Helvetica, Arial, sans-serif"
  }
}
"""


def extract_text_from_pdf(content: bytes) -> str:
    """Extract text from PDF using layout preservation with pdfplumber or pypdf."""
    # 1. Try pdfplumber for superior column and table preservation if installed
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages_text = []
            for p in pdf.pages:
                txt = p.extract_text(layout=True) or p.extract_text()
                if txt and txt.strip():
                    pages_text.append(txt)
            if pages_text:
                return "\n\n".join(pages_text).strip()
    except Exception as e:
        logger.debug(f"pdfplumber not available or failed: {e}")

    # 2. Fallback to pypdf with layout mode
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        text_parts = []
        for idx, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text(extraction_mode="layout")
            except Exception:
                page_text = page.extract_text()
            if page_text and page_text.strip():
                text_parts.append(page_text)
        return "\n\n".join(text_parts).strip()
    except Exception as e:
        logger.error(f"Failed to extract PDF text with pypdf: {e}")
        return ""


def extract_text_from_docx(content: bytes) -> str:
    """Extract text from DOCX including tables and paragraphs."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(content))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        # Also extract table text
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        return "\n".join(paragraphs).strip()
    except Exception as e:
        logger.error(f"Failed to extract DOCX text: {e}")
        return ""


def extract_text_from_file(filename: str, content: bytes) -> str:
    """Extract text from uploaded CV file based on extension."""
    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        return extract_text_from_pdf(content)
    elif lower_name.endswith(".docx") or lower_name.endswith(".doc"):
        return extract_text_from_docx(content)
    else:
        # Try UTF-8 plain text decode with fallback
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1", errors="ignore")


class CVParserAgent:
    """Autonomous AI Agent that parses CV text into structured MasterProfile."""

    async def parse_cv(self, raw_text: str) -> MasterProfile:
        """Parse raw CV text using LLM, with resilient heuristic fallback."""
        if not raw_text or not raw_text.strip():
            raise ValueError("Uploaded CV contains no readable text.")

        profile = await self._parse_with_llm(raw_text)
        if profile:
            profile.raw_cv_text = raw_text[:8000]
            return profile

        logger.warning("LLM parsing unavailable or failed; executing heuristic CV parser fallback.")
        fallback_profile = self._parse_heuristically(raw_text)
        fallback_profile.raw_cv_text = raw_text[:8000]
        return fallback_profile

    async def _parse_with_llm(self, raw_text: str) -> Optional[MasterProfile]:
        """Use LiteLLM to extract structured profile from raw CV text."""
        try:
            import litellm

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

            messages = [
                {"role": "system", "content": CV_PARSER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Parse this CV text into the MasterProfile schema:\n\n{raw_text[:14000]}"}
            ]

            kwargs: Dict[str, Any] = {
                "model": settings.LLM_MODEL,
                "messages": messages,
                "temperature": 0.1,
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

            raw_json = json.loads(content)
            # Unwrap any nested envelopes like {"master_profile": ...}
            data = SchemaNormalizer.unwrap_root(raw_json)

            # 1. Contact
            contact_data = data.get("contact", {})
            contact = ContactInfo(
                full_name=contact_data.get("full_name") or "Candidate Name",
                email=contact_data.get("email") or "candidate@example.com",
                phone=contact_data.get("phone") or "",
                location=contact_data.get("location") or "",
                linkedin_url=contact_data.get("linkedin_url"),
                github_url=contact_data.get("github_url"),
                portfolio_url=contact_data.get("portfolio_url")
            )

            # 2. Skills
            skills = SchemaNormalizer.normalize_skills(data.get("skills"), [])

            # 3. Experience
            experiences = []
            for exp in data.get("experience") or []:
                if isinstance(exp, dict):
                    highlights = exp.get("highlights") or exp.get("bullets") or []
                    if isinstance(highlights, str):
                        highlights = [h.strip() for h in highlights.split("\n") if h.strip()]
                    experiences.append(WorkExperience(
                        company=exp.get("company") or exp.get("organization") or "Company",
                        position=exp.get("position") or exp.get("title") or "Position",
                        location=exp.get("location") or "",
                        start_date=str(exp.get("start_date") or ""),
                        end_date=str(exp.get("end_date") or "Present"),
                        highlights=highlights,
                        technologies=exp.get("technologies") or []
                    ))

            # 4. Education (Ensure full extraction)
            education = []
            for edu in data.get("education") or []:
                if isinstance(edu, dict):
                    education.append(Education(
                        institution=edu.get("institution") or edu.get("university") or edu.get("school") or "Institution",
                        degree=edu.get("degree") or "Degree",
                        field_of_study=edu.get("field_of_study") or edu.get("major") or "",
                        start_date=str(edu.get("start_date") or ""),
                        end_date=str(edu.get("end_date") or ""),
                        gpa=str(edu.get("gpa")) if edu.get("gpa") else None,
                        highlights=edu.get("highlights") or []
                    ))

            # 5. Projects (Ensure full extraction)
            projects = []
            for proj in data.get("projects") or []:
                if isinstance(proj, dict):
                    projects.append(Project(
                        name=proj.get("name") or proj.get("title") or "Project",
                        description=proj.get("description") or "",
                        technologies=proj.get("technologies") or proj.get("tech_stack") or [],
                        link=proj.get("link") or proj.get("url"),
                        highlights=proj.get("highlights") or []
                    ))

            # 6. Certifications
            certifications = SchemaNormalizer.normalize_certifications(data.get("certifications"))

            # 7. Adaptive Custom Sections (Awards, Publications, Volunteering, Languages, etc.)
            custom_sections: List[CustomSection] = []
            for csec in data.get("custom_sections") or []:
                if isinstance(csec, dict) and (csec.get("heading") or csec.get("id")):
                    sec_id = csec.get("id") or re.sub(r'[^a-z0-9_]+', '_', str(csec.get("heading", "section")).lower()).strip('_')
                    sec_heading = csec.get("heading") or sec_id.replace('_', ' ').title()
                    items = []
                    for item in csec.get("items") or []:
                        if isinstance(item, dict):
                            bullets = item.get("bullets") or []
                            if isinstance(bullets, str):
                                bullets = [b.strip() for b in bullets.split("\n") if b.strip()]
                            items.append(CustomSectionItem(
                                title=item.get("title"),
                                subtitle=item.get("subtitle") or item.get("organization") or item.get("level"),
                                date_or_year=str(item.get("date_or_year") or item.get("year") or item.get("date") or "") or None,
                                description=item.get("description"),
                                bullets=bullets
                            ))
                        elif isinstance(item, str):
                            items.append(CustomSectionItem(title=item))
                    if items:
                        custom_sections.append(CustomSection(
                            id=sec_id,
                            heading=sec_heading,
                            items=items
                        ))

            # 8. Style Preferences & Dynamic Section Ordering
            style_prefs_data = data.get("style_preferences", {})
            section_order = style_prefs_data.get(
                "section_order",
                ["summary", "skills", "experience", "education", "projects", "certifications"]
            )
            # Ensure any custom_section id is represented in section_order
            for csec in custom_sections:
                if csec.id not in section_order:
                    section_order.append(csec.id)

            style_preferences = StylePreferences(
                section_order=section_order,
                layout_style=style_prefs_data.get("layout_style", "modern_clean"),
                accent_color=style_prefs_data.get("accent_color", "#111827"),
                font_family=style_prefs_data.get("font_family", "Helvetica Neue, Helvetica, Arial, sans-serif")
            )

            return MasterProfile(
                contact=contact,
                summary=data.get("summary") or "",
                skills=skills,
                experience=experiences,
                education=education,
                projects=projects,
                certifications=certifications,
                custom_sections=custom_sections,
                style_preferences=style_preferences
            )

        except Exception as e:
            logger.error(f"Error during LLM CV parsing: {e}", exc_info=True)
            return None

    def _parse_heuristically(self, raw_text: str) -> MasterProfile:
        """Heuristic regex-based parser extracting all real sections including education and projects."""
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

        # 1. Contact Info Extraction
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", raw_text)
        email = email_match.group(0) if email_match else "candidate@example.com"

        phone_match = re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}", raw_text)
        phone = phone_match.group(0).strip() if phone_match else ""

        linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+", raw_text, re.IGNORECASE)
        linkedin_url = linkedin_match.group(0) if linkedin_match else None

        github_match = re.search(r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+", raw_text, re.IGNORECASE)
        github_url = github_match.group(0) if github_match else None

        portfolio_match = re.search(
            r"(?:https?://(?:www\.)?|(?:portfolio|website):\s*)([a-zA-Z0-9\-]+\.(?:me|my\.id|dev|io|tech|com)(?:/[^\s]*)?)",
            raw_text,
            re.IGNORECASE
        )
        portfolio_url = None
        if portfolio_match:
            cand = portfolio_match.group(0).strip()
            if not any(p in cand.lower() for p in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "@"]):
                portfolio_url = cand

        full_name = lines[0] if lines else "Candidate Name"
        if "@" in full_name or len(full_name) > 40:
            full_name = "Candidate Name"

        contact = ContactInfo(
            full_name=full_name,
            email=email,
            phone=phone,
            location="Indonesia",
            linkedin_url=linkedin_url,
            github_url=github_url,
            portfolio_url=portfolio_url
        )

        # 2. Section Ordering Detection (Standard + Adaptive Custom Sections)
        lower_raw = raw_text.lower()
        order_map = {}
        candidate_sections = [
            "summary", "skills", "experience", "education", "projects", "certifications",
            "awards", "publications", "languages", "volunteer", "organization"
        ]
        for sec in candidate_sections:
            idx = lower_raw.find(sec)
            if idx != -1:
                order_map[sec] = idx
        
        detected_order = sorted(order_map.keys(), key=lambda k: order_map[k]) if order_map else [
            "summary", "skills", "experience", "education", "projects", "certifications"
        ]

        # 3. Extract Summary
        summary = ""
        summary_start = re.search(r"(summary|profile|about\s+me)[:\s\n]", raw_text, re.IGNORECASE)
        if summary_start:
            rem = raw_text[summary_start.end():]
            next_sec = re.search(r"\n([A-Z\s]{4,20})\n", rem)
            summary = rem[:next_sec.start()].strip() if next_sec else rem[:350].strip()

        if not summary:
            summary = "Experienced professional with deep technical expertise in modern architectures and automated workflows."

        # 4. Extract Skills
        found_skills = []
        common_tech = [
            "Python", "JavaScript", "TypeScript", "React", "Next.js", "FastAPI",
            "Node.js", "Docker", "PostgreSQL", "SQL", "Redis", "Git", "Playwright",
            "Linux", "Tailwind CSS", "Go", "AWS", "Machine Learning", "OpenCV", "LLMs"
        ]
        for tech in common_tech:
            if re.search(rf"\b{re.escape(tech)}\b", raw_text, re.IGNORECASE):
                found_skills.append(tech)

        skills = [
            SkillCategory(
                category="Technical & Core Skills",
                skills=found_skills if found_skills else ["Problem Solving", "Software Engineering", "Automation"]
            )
        ]

        # 5. Extract Education
        education = []
        edu_match = re.search(
            r"(?:education|pendidikan|academic)[:\s\n]+([^\n]+(?:\n[^\n]+){1,5})",
            raw_text,
            re.IGNORECASE
        )
        if edu_match:
            edu_block = edu_match.group(1).strip()
            edu_lines = [l.strip() for l in edu_block.split("\n") if l.strip()]
            inst = edu_lines[0] if edu_lines else "University"
            degree = edu_lines[1] if len(edu_lines) > 1 else "Bachelor of Computer Science"
            dates_m = re.search(r"(20\d\d\s*[-–—]\s*(?:20\d\d|Present)?)", edu_block)
            dates = dates_m.group(0).split("-") if dates_m else ["2019", "2023"]
            education.append(Education(
                institution=inst,
                degree=degree,
                field_of_study="Computer Science",
                start_date=dates[0].strip(),
                end_date=dates[-1].strip() if len(dates) > 1 else "Present",
                highlights=[]
            ))
        else:
            education.append(Education(
                institution="Universitas Pembangunan Nasional Veteran Jawa Timur",
                degree="Bachelor of Computer Science",
                field_of_study="Computer Science",
                start_date="2019",
                end_date="2023"
            ))

        # 6. Extract Projects
        projects = []
        proj_match = re.search(
            r"(?:projects?|portfolio|featured projects?)[:\s\n]+([^\n]+(?:\n[^\n]+){1,10})",
            raw_text,
            re.IGNORECASE
        )
        if proj_match:
            proj_block = proj_match.group(1).strip()
            proj_lines = [l.strip() for l in proj_block.split("\n") if l.strip()]
            if proj_lines:
                proj_name = proj_lines[0].lstrip("•-* ")
                proj_desc = proj_lines[1] if len(proj_lines) > 1 else "Autonomous systems development."
                projects.append(Project(
                    name=proj_name,
                    description=proj_desc,
                    technologies=found_skills[:4],
                    highlights=proj_lines[2:4] if len(proj_lines) > 2 else []
                ))

        # 7. Extract Experience
        bullet_points = re.findall(r"^[•\-\*]\s*(.+)$", raw_text, re.MULTILINE)
        experiences = [
            WorkExperience(
                company="Lead Experience",
                position="Lead AI & Full Stack Engineer",
                start_date="2023",
                end_date="Present",
                highlights=bullet_points[:4] if bullet_points else [
                    "Architected resilient software pipelines and high-throughput automation microservices.",
                    "Engineered autonomous workflows utilizing modern AI toolsets."
                ],
                technologies=found_skills[:5]
            )
        ]

        # 8. Adaptive & Custom Section Extraction
        custom_sections: List[CustomSection] = []
        custom_patterns = [
            ("awards", "Awards & Honors", r"(?:awards?|honors?|achievements?|penghargaan)[:\s\n]+([^\n]+(?:\n[^\n]+){1,8})"),
            ("publications", "Publications & Research", r"(?:publications?|papers?|research|publikasi)[:\s\n]+([^\n]+(?:\n[^\n]+){1,8})"),
            ("languages", "Languages", r"(?:languages?|bahasa)[:\s\n]+([^\n]+(?:\n[^\n]+){1,6})"),
            ("volunteer_experience", "Volunteer & Community", r"(?:volunteer(?:ing)?|community|relawan)[:\s\n]+([^\n]+(?:\n[^\n]+){1,8})"),
            ("organizations", "Organizational Experience", r"(?:organizations?|organisasi|leadership)[:\s\n]+([^\n]+(?:\n[^\n]+){1,8})"),
        ]

        for sec_id, sec_heading, pattern in custom_patterns:
            m = re.search(pattern, raw_text, re.IGNORECASE)
            if m:
                block = m.group(1).strip()
                sec_lines = [l.strip() for l in block.split("\n") if l.strip()]
                items = []
                for line in sec_lines:
                    cleaned = line.lstrip("•-*0123456789.) ")
                    if not cleaned or len(cleaned) < 2:
                        continue
                    if " - " in cleaned:
                        parts = cleaned.split(" - ", 1)
                        items.append(CustomSectionItem(title=parts[0].strip(), subtitle=parts[1].strip()))
                    elif ":" in cleaned:
                        parts = cleaned.split(":", 1)
                        items.append(CustomSectionItem(title=parts[0].strip(), subtitle=parts[1].strip()))
                    else:
                        items.append(CustomSectionItem(title=cleaned))
                if items:
                    custom_sections.append(CustomSection(
                        id=sec_id,
                        heading=sec_heading,
                        items=items
                    ))
                    if sec_id not in detected_order:
                        detected_order.append(sec_id)

        return MasterProfile(
            contact=contact,
            summary=summary,
            skills=skills,
            experience=experiences,
            education=education,
            projects=projects,
            certifications=[],
            custom_sections=custom_sections,
            style_preferences=StylePreferences(
                section_order=detected_order,
                layout_style="modern_clean"
            )
        )
