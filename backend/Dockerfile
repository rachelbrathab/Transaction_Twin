# Transaction Twin — Backend Dockerfile
# Multi-stage build for minimal production image

# ── Stage 1: Dependencies ──────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

# Install system dependencies required for asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency specification first for Docker layer caching
COPY pyproject.toml ./

# Install dependencies into a virtual environment
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -e ".[dev]"

# ── Stage 2: Production ────────────────────────────────────────────
FROM python:3.12-slim AS production

# Non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy virtual environment from deps stage
COPY --from=deps /opt/venv /opt/venv

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Runtime environment — venv is the default Python
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set ownership
RUN chown -R appuser:appuser /app

USER appuser

# Application port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Production command — no --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--no-access-log"]
