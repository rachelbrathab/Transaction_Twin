"""Health check endpoints.

Provides GET /health and GET /api/v1/health for liveness and readiness checks.
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health")
async def root_health() -> dict[str, str]:
    """Basic liveness check — no database dependency."""
    return {"status": "ok"}


@router.get("/api/v1/health")
async def api_v1_health(db: AsyncSession = Depends(get_db)) -> dict[str, str | bool]:
    """Readiness check — verifies database connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": True}
    except Exception:
        logger.warning("health_check_db_failed")
        return {"status": "degraded", "database": False}
