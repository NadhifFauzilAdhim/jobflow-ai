"""Typer CLI interface for JobFlow AI."""

import asyncio
import typer
from rich.console import Console
from rich.table import Table
from pathlib import Path
from jobflow.config import settings
from jobflow.core.schema import JobListing, PlatformType
from jobflow.core.resume_engine import ResumeEngine
from jobflow.core.pdf_generator import PDFGenerator
from jobflow.extractors.platform_extractors import get_job_extractor
from jobflow.automations.applier import JobApplier

app = typer.Typer(help="JobFlow AI - Autonomous Job Application Engine")
console = Console()


@app.command()
def tailor(
    title: str = typer.Option(..., "--title", "-t", help="Job title"),
    company: str = typer.Option(..., "--company", "-c", help="Company name"),
    desc: str = typer.Option(..., "--desc", "-d", help="Job description or requirements"),
    output: str = typer.Option("tailored_resume.pdf", "--output", "-o", help="Output PDF name")
):
    """Tailor your resume against a job description and generate ATS PDF."""
    async def _run():
        job = JobListing(
            title=title,
            company=company,
            description=desc,
            requirements=[desc]
        )
        console.print(f"[bold green]Tailoring resume for:[/] {title} at {company}...")
        engine = ResumeEngine()
        tailored = await engine.tailor_resume(job)
        
        console.print(f"[bold cyan]ATS Match Score:[/] {tailored.ats_score}%")
        console.print(f"[bold green]Matched Keywords:[/] {', '.join(tailored.matching_keywords[:8])}")
        
        generator = PDFGenerator()
        pdf_path = await generator.generate_pdf(tailored, output_filename=output)
        console.print(f"[bold yellow]Generated ATS PDF:[/] {pdf_path}")

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload")
):
    """Start JobFlow AI Web Dashboard and API."""
    import uvicorn
    console.print(f"[bold green]Starting JobFlow Dashboard on http://{host}:{port}[/]")
    uvicorn.run("jobflow.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
