"""API v1 router.

Aggregates all versioned endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health, intents

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(intents.router, tags=["Intents"])
