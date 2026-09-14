# JobFlow AI 🚀
**Autonomous Job Application Engine & Dynamic ATS CV Tailor**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-green.svg)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

JobFlow AI is an end-to-end automated job application platform with real-time ATS CV generation, job description extraction, and stealth browser application bot.

---

## 🌟 Key Features

1. **📄 Dynamic ATS Resume Generator:**
   - Heuristic & LLM-powered keyword matcher (evaluates ATS match % against Job Descriptions).
   - Generates clean, ATS-compliant PDFs via ReportLab, WeasyPrint, and Typst.
   - Preserves candidate truthfulness while maximizing keyword alignment using the Google X-Y-Z formula.

2. **🤖 Multi-Platform Job Scraper & Parser:**
   - Automatic extraction of job titles, company names, and requirements from **LinkedIn**, **JobStreet**, **Glints**, and generic careers portals.

3. **⚡ Stealth Browser Automation:**
   - Powered by **Playwright** with human jitter delays and persistent cookie/session storage.
   - Form-filling engine with intelligent Q&A rule matching for salary, notice period, and citizenship questions.
   - Captures screenshot proof upon submission.

4. **🖥️ Clean Dark Dashboard UI:**
   - Built with **Tailwind CSS** (Zinc / Jet Black monochrome aesthetic).
   - Live streaming task console and iframe ATS previewer.
   - REST API and full background async task execution.

5. **🐳 Docker & Docker Compose Support:**
   - Multi-container architecture with Redis broker, SQLite/PostgreSQL persistence, and headless browser drivers.

---

## 🛠️ Architecture & Tech Stack

```text
               ┌────────────────────────────────────────────────────────┐
               │                  Web Dashboard (UI)                    │
               │         Tailwind CSS • Modern Monochrome Dark          │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │                   FastAPI Backend                      │
               │   Async REST Endpoints • SQLite/PostgreSQL • Celery   │
               └───────────────┬────────────────────────┬───────────────┘
                               │                        │
            ┌──────────────────┴──┐                  ┌──┴──────────────────┐
            │   Resume Engine     │                  │  Automation Engine  │
            │  ATS Keyword Scorer │                  │  Playwright Stealth │
            │  PDF Synthesizer    │                  │  Form Solver & Log  │
            └─────────────────────┘                  └─────────────────────┘
```

---

## 🚀 Quick Start (Docker)

### 1. Clone repository
```bash
git clone https://github.com/NadhifFauzilAdhim/jobflow-ai.git
cd jobflow-ai
```

### 2. Configure Environment (Optional)
```bash
cp .env.example .env
```
*(If you have OpenAI, Anthropic, Gemini, or Groq API keys, paste them into `.env`. Otherwise, JobFlow AI defaults to its heuristic ATS engine).*

### 3. Start with Docker Compose
```bash
docker-compose up --build -d
```
Open **`http://localhost:8000`** in your browser to access the dashboard.

---

## 💻 Local Development Setup

### 1. Install dependencies with `uv` or `pip`
```bash
uv venv
source .venv/bin/activate
uv pip install -e .
playwright install chromium
```

### 2. Run CLI Commands
- **Start Web Dashboard:**
  ```bash
  jobflow serve --port 8000
  ```
- **CLI Tailor CV from prompt:**
  ```bash
  jobflow tailor --title "Senior Python Developer" --company "Acme Corp" --desc "FastAPI Docker Redis"
  ```

### 3. Run Automated Tests
```bash
pytest tests/
```

---

## 📂 Project Structure
```text
jobflow-ai/
├── data/
│   ├── master_profile.json      # Master candidate resume & Q&A answers
│   └── sample_jobs.json         # Sample job listings
├── src/jobflow/
│   ├── api/                     # FastAPI backend & routes
│   ├── automations/             # Playwright stealth & form solver
│   ├── core/                    # ATS scorer, resume tailor & PDF engine
│   ├── db/                      # SQLAlchemy models & migrations
│   ├── extractors/              # LinkedIn, JobStreet, Glints extractors
│   ├── templates/               # Dashboard UI & PDF HTML/Typst templates
│   ├── cli.py                   # Typer CLI interface
│   └── config.py                # Environment configuration
├── tests/                       # Unit & integration tests
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## 📄 License
MIT License. Created by [Nadhif Fauzil Adhim](https://github.com/NadhifFauzilAdhim).
