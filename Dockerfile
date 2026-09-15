FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies & Playwright requirements & Typst
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    fonts-dejavu-core \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN pip install --no-cache-dir uv

# Copy project definition
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY data/ ./data/

# Install python dependencies and project
RUN uv pip install --system -e .

# Install Playwright browser binaries
RUN playwright install chromium
RUN playwright install-deps chromium || true

EXPOSE 8000

CMD ["python", "-m", "jobflow.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
