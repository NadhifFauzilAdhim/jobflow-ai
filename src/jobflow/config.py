"""Configuration module for JobFlow AI."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App General
    APP_NAME: str = "JobFlow AI"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    SECRET_KEY: str = "jobflow-insecure-secret-key-change-in-production"

    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DATA_DIR}/jobflow.db"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # LLM Provider Configuration
    LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Browser & Automation
    BROWSER_HEADLESS: bool = True
    BROWSER_SLOW_MO: int = 50
    BROWSER_TIMEOUT: int = 30000
    USER_DATA_DIR: str = str(DATA_DIR / "browser_sessions")

    # Master Profile
    MASTER_PROFILE_PATH: str = str(DATA_DIR / "master_profile.json")


settings = Settings()

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Path(settings.USER_DATA_DIR).mkdir(parents=True, exist_ok=True)
