"""FastAPI Main Application and Dashboard Server with Session Authentication."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.openapi.utils import get_openapi
from jobflow.config import settings, STATIC_DIR, TEMPLATES_DIR
from jobflow.db.database import init_db
from jobflow.core.security import get_authenticated_user
from jobflow.api.routes import profile, jobs, resume, apply, auth, api_keys
from jobflow.api.v1.router import router as v1_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PUBLIC_PATH_PREFIXES = (
    "/health",
    "/login",
    "/logout",
    "/api/auth/login",
    "/api/auth/logout",
    "/static/",
    "/favicon.ico",
    "/developers",
    "/api-docs",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    yield


app = FastAPI(
    title=f"{settings.APP_NAME} - Developer & Automation API",
    version="1.0.0",
    description="Autonomous Job Application Engine, ATS CV Tailoring & Job Discovery API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=f"{settings.APP_NAME} Developer API",
        version="1.0.0",
        description="Public developer API for resume tailoring, ATS scoring, multi-platform job discovery, and automated applications.",
        routes=app.routes,
    )
    openapi_schema["components"] = openapi_schema.get("components", {})
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Enter your JobFlow AI API Key (starts with jf_live_...)"
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT / Key",
            "description": "Bearer token authentication (Session Token or API Key)"
        }
    }
    # Security requirement options: ApiKeyAuth or BearerAuth
    openapi_schema["security"] = [{"ApiKeyAuth": []}, {"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# Authentication Middleware for Public Deployment Security
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if settings.AUTH_ENABLED:
        path = request.url.path
        # Allow unrestricted access to public paths
        is_public = any(path == p or path.startswith(p) for p in PUBLIC_PATH_PREFIXES)
        if not is_public:
            user = get_authenticated_user(request)
            if not user:
                if path.startswith("/api/"):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Authentication required. Please log in or provide a valid Bearer token / API key."}
                    )
                # Redirect browser web requests to /login
                redirect_url = f"/login?next={path}" if path != "/" else "/login"
                return RedirectResponse(url=redirect_url, status_code=303)

    return await call_next(request)


# Mount static and templates
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API Routers
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(profile.router)
app.include_router(jobs.router)
app.include_router(resume.router)
app.include_router(apply.router)
app.include_router(v1_router)


@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    """Serve login interface or redirect to dashboard if already authenticated."""
    if settings.AUTH_ENABLED:
        user = get_authenticated_user(request)
        if user:
            return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"app_name": settings.APP_NAME})


@app.get("/logout")
@app.post("/logout")
async def logout_browser():
    """Clear session cookie and redirect browser to login page."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax"
    )
    return response


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serve modern monochrome dark-themed dashboard."""
    username = get_authenticated_user(request) or "admin"
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.APP_NAME, "username": username}
    )


@app.get("/developers", response_class=HTMLResponse)
@app.get("/api-docs", response_class=HTMLResponse)
async def serve_api_docs(request: Request):
    """Serve dedicated Developer Documentation Portal."""
    username = get_authenticated_user(request)
    return templates.TemplateResponse(
        request=request,
        name="api_docs.html",
        context={"app_name": settings.APP_NAME, "username": username}
    )


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "jobflow-ai"}


