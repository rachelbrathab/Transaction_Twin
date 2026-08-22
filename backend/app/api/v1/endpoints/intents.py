"""Intent parsing endpoint.

POST /api/v1/intents/parse — parses natural language into structured intent.
Does NOT execute payments or authorize transactions.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.intent_engine.adapters.deterministic import DeterministicAdapter
from app.services.intent_engine.engine import IntentEngine
from app.services.intent_engine.models import (
    IntentParseRequest,
    IntentParseResponse,
)

logger = structlog.get_logger()
router = APIRouter()


def _get_intent_engine() -> IntentEngine:
    """Create IntentEngine with available adapters.

    Uses dependency injection so tests can override.
    """
    adapters = []

    # Try Gemini if configured
    try:
        from app.services.intent_engine.adapters.gemini import GeminiAdapter

        gemini = GeminiAdapter()
        if gemini.is_available:
            adapters.append(gemini)
    except Exception:
        pass

    # Always include deterministic fallback
    adapters.append(DeterministicAdapter())

    return IntentEngine(adapters=adapters)


@router.post("/intents/parse", response_model=IntentParseResponse)
async def parse_intent(
    request: IntentParseRequest,
    db: AsyncSession = Depends(get_db),
    engine: IntentEngine = Depends(_get_intent_engine),
) -> IntentParseResponse:
    """Parse a natural language request into structured intent.

    Returns parsed intent, needs_clarification, rejected, or error.
    """
    try:
        result = await engine.parse(request, db)
    except Exception as e:
        logger.error("intent_parse_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal parsing error")

    # Build response
    response = IntentParseResponse(
        status=result.status,
        intent_id=result.intent_id,
        version=result.version,
        structured_intent=(
            result.structured_intent.model_dump(mode="json")
            if result.structured_intent
            else None
        ),
        confidence=result.confidence,
        ambiguities=[
            {"field": a.field, "severity": a.severity.value, "message": a.message}
            for a in result.ambiguities
        ],
        rejection_reason=result.rejection_reason,
    )

    return response
