"""PDF Resume Generation Engine supporting Playwright, WeasyPrint, Typst, and ReportLab."""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from jobflow.core.schema import TailoredResume, MasterProfile
from jobflow.config import TEMPLATES_DIR, OUTPUT_DIR

logger = logging.getLogger("jobflow.pdf_generator")


class PDFGenerator:
    def __init__(self):
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        self.html_template = self.env.get_template("resume_clean.html")

    def render_html(self, resume: TailoredResume | MasterProfile, show_highlights: bool = False) -> str:
        """Render resume data into HTML with optional AI improvement highlights."""
        return self.html_template.render(resume=resume, show_highlights=show_highlights)

    async def generate_pdf(
        self,
        resume: TailoredResume | MasterProfile,
        output_filename: str = "tailored_resume.pdf",
        method: str = "auto",
        show_highlights: bool = False
    ) -> Path:
        """Generate PDF using best available method (Playwright > WeasyPrint > Typst > ReportLab)."""
        output_path = OUTPUT_DIR / output_filename
        rendered_html = self.render_html(resume, show_highlights=show_highlights)

        if method == "typst" or (method == "auto" and shutil.which("typst")):
            typst_success = await self._render_with_typst(resume, output_path)
            if typst_success:
                return output_path

        # Try Playwright
        if method in ("playwright", "auto"):
            try:
                success = await self._render_with_playwright(rendered_html, output_path)
                if success:
                    return output_path
            except Exception as e:
                logger.warning(f"Playwright PDF generation failed: {e}. Falling back to Weasyprint/Reportlab.")

        # Try WeasyPrint
        if method in ("weasyprint", "auto"):
            try:
                from weasyprint import HTML
                HTML(string=rendered_html).write_pdf(str(output_path))
                return output_path
            except Exception as e:
                logger.warning(f"WeasyPrint PDF generation failed: {e}. Falling back to ReportLab.")

        # Fallback to ReportLab
        self._render_with_reportlab(resume, output_path)
        return output_path

    async def _render_with_playwright(self, html_content: str, output_path: Path) -> bool:
        """Generate PDF via headless Playwright browser."""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            await page.pdf(
                path=str(output_path),
                format="Letter",
                print_background=True,
                margin={"top": "0.4in", "bottom": "0.4in", "left": "0.5in", "right": "0.5in"}
            )
            await browser.close()
        return True

    async def _render_with_typst(self, resume: TailoredResume | MasterProfile, output_path: Path) -> bool:
        """Compile Typst template into PDF."""
        typst_bin = shutil.which("typst")
        if not typst_bin:
            return False

        # Prepare Typst content
        contact_parts = [
            resume.contact.location,
            resume.contact.email,
            resume.contact.phone,
        ]
        if resume.contact.github_url:
            contact_parts.append(f"#link(\"{resume.contact.github_url}\")[GitHub]")
        if resume.contact.linkedin_url:
            contact_parts.append(f"#link(\"{resume.contact.linkedin_url}\")[LinkedIn]")

        contact_line = " | ".join(contact_parts)

        summary_sec = f"section(\"Professional Summary\")\n{resume.summary}\n" if resume.summary else ""
        
        skills_lines = ["section(\"Technical Skills\")\n#table(columns: (1.5fr, 4fr), stroke: none, inset: (x: 0pt, y: 2pt),"]
        for cat in resume.skills:
            skills_lines.append(f"  [* {cat.category}:*], [{', '.join(cat.skills)}],")
        skills_lines.append(")")
        skills_sec = "\n".join(skills_lines)

        exp_lines = ["section(\"Work Experience\")"]
        for exp in resume.experience:
            exp_lines.append(f"#grid(columns: (1fr, 1fr), [*{exp.position}*], align(right)[{exp.start_date} - {exp.end_date}])")
            exp_lines.append(f"#text(style: \"italic\")[{exp.company} - {exp.location}]")
            for hl in exp.highlights:
                # Escape typst markup
                clean_hl = hl.replace("$", "\\$").replace("#", "\\#")
                exp_lines.append(f"- {clean_hl}")
            exp_lines.append("#v(3pt)")
        exp_sec = "\n".join(exp_lines)

        proj_lines = ["section(\"Projects\")"]
        for proj in resume.projects:
            proj_lines.append(f"#grid(columns: (1fr, 1fr), [*{proj.name}* #text(size: 8pt)[| {', '.join(proj.technologies)}]], align(right)[{proj.link or ''}])")
            proj_lines.append(f"{proj.description}")
            for hl in proj.highlights:
                proj_lines.append(f"- {hl}")
            proj_lines.append("#v(2pt)")
        proj_sec = "\n".join(proj_lines)

        edu_lines = ["section(\"Education\")"]
        for edu in resume.education:
            edu_lines.append(f"#grid(columns: (1fr, 1fr), [*{edu.institution}*], align(right)[{edu.start_date} - {edu.end_date}])")
            edu_lines.append(f"_{edu.degree} in {edu.field_of_study}_")
            for hl in edu.highlights:
                edu_lines.append(f"- {hl}")
        edu_sec = "\n".join(edu_lines)

        typ_template_path = TEMPLATES_DIR / "resume_ats.typ"
        template_text = typ_template_path.read_text(encoding="utf-8")
        
        content = template_text.replace("NAME_PLACEHOLDER", resume.contact.full_name)\
                               .replace("CONTACT_PLACEHOLDER", contact_line)\
                               .replace("SUMMARY_SECTION_PLACEHOLDER", summary_sec)\
                               .replace("SKILLS_SECTION_PLACEHOLDER", skills_sec)\
                               .replace("EXPERIENCE_SECTION_PLACEHOLDER", exp_sec)\
                               .replace("PROJECTS_SECTION_PLACEHOLDER", proj_sec)\
                               .replace("EDUCATION_SECTION_PLACEHOLDER", edu_sec)

        with tempfile.NamedTemporaryFile(suffix=".typ", mode="w", encoding="utf-8", delete=False) as tf:
            tf.write(content)
            tf_path = tf.name

        import asyncio
        proc = await asyncio.create_subprocess_exec(
            typst_bin, "compile", tf_path, str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        try:
            os.remove(tf_path)
        except OSError:
            pass

        return proc.returncode == 0

    def _render_with_reportlab(self, resume: TailoredResume | MasterProfile, output_path: Path):
        """Pure Python fallback PDF generation using ReportLab."""
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        normal = styles["Normal"]
        
        name_style = ParagraphStyle(
            "NameStyle",
            parent=normal,
            fontSize=16,
            leading=18,
            fontName="Helvetica-Bold",
            alignment=1
        )
        contact_style = ParagraphStyle(
            "ContactStyle",
            parent=normal,
            fontSize=8.5,
            leading=11,
            alignment=1,
            textColor=colors.HexColor("#374151")
        )
        sec_header_style = ParagraphStyle(
            "SecHeaderStyle",
            parent=normal,
            fontSize=10,
            leading=13,
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#111827"),
            spaceBefore=8,
            spaceAfter=3
        )
        body_style = ParagraphStyle(
            "BodyStyle",
            parent=normal,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#1F2937")
        )
        bullet_style = ParagraphStyle(
            "BulletStyle",
            parent=normal,
            fontSize=8.5,
            leading=11,
            leftIndent=12,
            bulletIndent=4,
            textColor=colors.HexColor("#1F2937")
        )

        story = []
        # Header
        story.append(Paragraph(resume.contact.full_name, name_style))
        contact_str = f"{resume.contact.location} | {resume.contact.email} | {resume.contact.phone}"
        story.append(Paragraph(contact_str, contact_style))
        story.append(Spacer(1, 8))

        def add_summary():
            if resume.summary:
                story.append(Paragraph("<b>PROFESSIONAL SUMMARY</b>", sec_header_style))
                story.append(Paragraph(resume.summary, body_style))
                story.append(Spacer(1, 4))

        def add_skills():
            if resume.skills:
                story.append(Paragraph("<b>TECHNICAL SKILLS</b>", sec_header_style))
                for cat in resume.skills:
                    story.append(Paragraph(f"<b>{cat.category}:</b> {', '.join(cat.skills)}", body_style))
                story.append(Spacer(1, 4))

        def add_experience():
            if resume.experience:
                story.append(Paragraph("<b>WORK EXPERIENCE</b>", sec_header_style))
                for exp in resume.experience:
                    story.append(Paragraph(f"<b>{exp.position}</b> — {exp.company} ({exp.start_date} - {exp.end_date})", body_style))
                    for hl in exp.highlights:
                        story.append(Paragraph(f"• {hl}", bullet_style))
                    story.append(Spacer(1, 4))

        def add_projects():
            if getattr(resume, "projects", None):
                story.append(Paragraph("<b>FEATURED PROJECTS</b>", sec_header_style))
                for proj in resume.projects:
                    tech_str = f" | {', '.join(proj.technologies)}" if proj.technologies else ""
                    story.append(Paragraph(f"<b>{proj.name}</b>{tech_str}", body_style))
                    if proj.description:
                        story.append(Paragraph(proj.description, body_style))
                    for hl in proj.highlights:
                        story.append(Paragraph(f"• {hl}", bullet_style))
                    story.append(Spacer(1, 4))

        def add_education():
            if resume.education:
                story.append(Paragraph("<b>EDUCATION</b>", sec_header_style))
                for edu in resume.education:
                    story.append(Paragraph(f"<b>{edu.institution}</b> — {edu.degree} in {edu.field_of_study} ({edu.start_date} - {edu.end_date})", body_style))
                    for hl in edu.highlights:
                        story.append(Paragraph(f"• {hl}", bullet_style))
                    story.append(Spacer(1, 4))

        def add_certifications():
            if getattr(resume, "certifications", None):
                story.append(Paragraph("<b>CERTIFICATIONS</b>", sec_header_style))
                for cert in resume.certifications:
                    story.append(Paragraph(f"• {cert}", bullet_style))
                story.append(Spacer(1, 4))

        section_dispatch = {
            "summary": add_summary,
            "skills": add_skills,
            "experience": add_experience,
            "projects": add_projects,
            "education": add_education,
            "certifications": add_certifications,
        }

        order = ["summary", "skills", "experience", "education", "projects", "certifications"]
        if getattr(resume, "style_preferences", None) and resume.style_preferences.section_order:
            order = resume.style_preferences.section_order

        for sec in order:
            if sec in section_dispatch:
                section_dispatch[sec]()

        doc.build(story)
