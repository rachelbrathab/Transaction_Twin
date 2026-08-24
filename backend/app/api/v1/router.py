"""API v1 router.

Aggregates all versioned endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import comparisons, health, intents

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(intents.router, tags=["Intents"])
api_router.include_router(comparisons.router, tags=["Comparisons"])
