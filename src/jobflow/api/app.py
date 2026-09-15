"""FastAPI Main Application and Dashboard Server."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jobflow.config import settings, STATIC_DIR, TEMPLATES_DIR
from jobflow.db.database import init_db
from jobflow.api.routes import profile, jobs, resume, apply

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Autonomous Job Application Engine & ATS CV Generator",
    lifespan=lifespan
)

# Mount static and templates
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API Routers
app.include_router(profile.router)
app.include_router(jobs.router)
app.include_router(resume.router)
app.include_router(apply.router)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serve modern monochrome dark-themed dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"app_name": settings.APP_NAME})


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "jobflow-ai"}
