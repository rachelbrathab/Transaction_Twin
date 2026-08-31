"""
Transaction Twin — Backend API Server

FastAPI application for the Transaction Twin risk control plane.

Usage:
    uvicorn app.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings, validate_production_settings
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.security_headers import SecurityHeadersMiddleware

settings = get_settings()
logger = structlog.get_logger()

# Fail-fast validation — abort if production has insecure config
validate_production_settings(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup and shutdown events."""
    setup_logging(settings.log_level)
    logger.info(
        "application_starting",
        version=__version__,
        environment=settings.app_env,
    )
    yield
    logger.info("application_shutting_down")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Transaction Twin — intent-aware risk control plane for AI payments.",
    lifespan=lifespan,
)

# CORS middleware — production origins are comma-separated in CORS_ORIGINS env var
_cors_origins: list[str] = [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# Security headers
app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)

# Error handlers
register_error_handlers(app)

# Direct /health endpoint for reverse-proxy liveness checks (Caddy routes /health)
@app.get("/health")
async def _root_health() -> dict[str, str]:
    return {"status": "ok"}

# API router — all routes under /api/v1
app.include_router(api_router, prefix=settings.api_v1_prefix)
