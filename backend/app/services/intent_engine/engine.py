"""Intent Engine — main orchestrator.

Converts natural language into structured authorization intent.
NEVER executes payments, authorizes transactions, or calls payment APIs.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ownership import validate_agent_belongs_to_user
from app.services.intent_engine.adapters.base import LLMAdapter
from app.services.intent_engine.adapters.deterministic import DeterministicAdapter
from app.services.intent_engine.ambiguity import detect_ambiguities, has_required_ambiguities
from app.services.intent_engine.confidence import calculate_confidence
from app.services.intent_engine.currency import resolve_currency
from app.services.intent_engine.models import (
    CurrencyInfo,
    IntentParseRequest,
    ParseResult,
    ParseStatus,
    StructuredIntent,
)
from app.services.intent_engine.normalization import normalize_request
from app.services.intent_engine.prompts import CURRENT_PARSER_VERSION, DETERMINISTIC_PARSER_VERSION
from app.services.intent_engine.security import analyze_security
from app.services.intent_engine.validation import validate_structured_intent

logger = structlog.get_logger()


class IntentEngine:
    """Main intent parsing orchestrator.

    Pipeline:
        normalize → security → currency → adapter → schema validation →
        constraint validation → ambiguity → confidence → ParseResult
    """

    def __init__(self, adapters: list[LLMAdapter] | None = None) -> None:
        self._adapters = adapters or [DeterministicAdapter()]

    async def parse(
        self,
        request: IntentParseRequest,
        db: AsyncSession,
    ) -> ParseResult:
        """Parse a natural language request into structured intent.

        Does NOT execute payments or authorize transactions.
        Only produces structured intent data.
        """
        start_time = time.monotonic()
        request_id = str(uuid.uuid4())[:8]

        log = logger.bind(request_id=request_id, user_id=request.user_id)

        # Step 1: Normalize
        try:
            norm = normalize_request(request.original_request)
        except ValueError as e:
            log.warning("normalization_failed", error=str(e))
            return ParseResult(
                status=ParseStatus.REJECTED,
                rejection_reason=f"Invalid request: {e}",
            )

        # Step 2: Ownership verification
        try:
            agent_uuid = uuid.UUID(request.agent_id)
            user_uuid = uuid.UUID(request.user_id)
            await validate_agent_belongs_to_user(db, user_uuid, agent_uuid)
        except (ValueError, Exception) as e:
            log.warning("ownership_validation_failed", error=str(e))
            return ParseResult(
                status=ParseStatus.REJECTED,
                rejection_reason=f"Agent ownership validation failed: {e}",
            )

        # Step 3: Security analysis
        security = analyze_security(norm.canonical_request)
        if security.injection_detected:
            log.info(
                "injection_detected",
                patterns=security.detected_patterns,
            )

        # Step 4: Currency resolution
        currency = resolve_currency(
            canonical_request=norm.canonical_request,
            user_default_currency=request.default_currency,
        )

        # Step 5: Choose adapter and parse
        adapter_result = None
        used_deterministic = False

        for adapter in self._adapters:
            try:
                adapter_result = await adapter.parse_intent(
                    canonical_request=norm.canonical_request,
                    resolved_currency=currency.code,
                    transaction_type_hint=(
                        request.transaction_type_hint.value
                        if request.transaction_type_hint
                        else None
                    ),
                    reference_timestamp=datetime.now(UTC).isoformat(),
                    prompt_version=CURRENT_PARSER_VERSION,
                )
                if adapter_result.success:
                    break
            except Exception as e:
                log.warning(
                    "adapter_failed",
                    adapter=type(adapter).__name__,
                    error=str(e),
                )
                continue

        # Fallback to deterministic if all adapters failed
        if adapter_result is None or not adapter_result.success:
            deterministic = DeterministicAdapter()
            adapter_result = await deterministic.parse_intent(
                canonical_request=norm.canonical_request,
                resolved_currency=currency.code,
                transaction_type_hint=(
                    request.transaction_type_hint.value
                    if request.transaction_type_hint
                    else None
                ),
                reference_timestamp=datetime.now(UTC).isoformat(),
                prompt_version=DETERMINISTIC_PARSER_VERSION,
            )
            used_deterministic = True

        if not adapter_result.success:
            log.error("all_adapters_failed", error=adapter_result.error)
            return ParseResult(
                status=ParseStatus.ERROR,
                rejection_reason=f"All parsing adapters failed: {adapter_result.error}",
            )

        # Step 6: Schema validation (HARD GATE)
        try:
            structured_intent = StructuredIntent(**adapter_result.raw_output)  # type: ignore[arg-type]
        except PydanticValidationError as e:
            log.warning("schema_validation_failed", errors=str(e))
            return ParseResult(
                status=ParseStatus.REJECTED,
                rejection_reason=f"Schema validation failed: {e}",
            )

        # Step 7: Deterministic constraint validation (HARD GATE)
        validation = validate_structured_intent(structured_intent)
        if not validation.valid:
            log.warning("constraint_validation_failed", errors=validation.errors)
            return ParseResult(
                status=ParseStatus.REJECTED,
                rejection_reason="; ".join(validation.errors),
            )

        # Step 8: Ambiguity detection
        ambiguities = detect_ambiguities(structured_intent)

        # Step 9: Confidence calculation
        confidence = calculate_confidence(
            intent=structured_intent,
            ambiguities=ambiguities,
            was_modified=norm.was_modified,
            is_deterministic=used_deterministic,
        )

        # Step 10: Determine status
        if has_required_ambiguities(ambiguities):
            status = ParseStatus.NEEDS_CLARIFICATION
        elif confidence < 0.30:
            status = ParseStatus.REJECTED
        else:
            status = ParseStatus.PARSED

        # Step 11: Build result
        result = ParseResult(
            status=status,
            structured_intent=structured_intent,
            confidence=confidence,
            ambiguities=ambiguities,
        )

        # Step 12: Persist if parsed
        if status == ParseStatus.PARSED:
            result = await self._persist_intent(
                db=db,
                request=request,
                structured_intent=structured_intent,
                confidence=confidence,
                original_request=norm.original_request,
                currency=currency,
            )

        # Log
        latency_ms = int((time.monotonic() - start_time) * 1000)
        log.info(
            "intent_parsed",
            status=status.value,
            confidence=confidence,
            parser_version=(
                adapter_result.provider_info.model
                if adapter_result.provider_info else "unknown"
            ),
            provider=(
                adapter_result.provider_info.provider
                if adapter_result.provider_info else "unknown"
            ),
            latency_ms=latency_ms,
            ambiguity_count=len(ambiguities),
            injection_detected=security.injection_detected,
        )

        return result

    async def _persist_intent(
        self,
        db: AsyncSession,
        request: IntentParseRequest,
        structured_intent: StructuredIntent,
        confidence: float,
        original_request: str,
        currency: CurrencyInfo,
    ) -> ParseResult:
        """Persist a successfully parsed intent to the database."""
        from app.models.intent import Intent

        intent = Intent(
            user_id=uuid.UUID(request.user_id),
            agent_id=uuid.UUID(request.agent_id),
            original_request=original_request,
            structured_intent=structured_intent.model_dump(mode="json"),
            status="active",
            currency=currency.code or "INR",
            min_amount=structured_intent.amount.min,
            max_amount=structured_intent.amount.max,
            category_constraints=structured_intent.category_constraints.model_dump(
                mode="json"
            ),
            merchant_constraints=structured_intent.merchant_constraints.model_dump(
                mode="json"
            ),
            geographic_constraints=structured_intent.geographic_constraints.model_dump(
                mode="json"
            ),
            authorization_scope=(
                structured_intent.authorization_scope.value.value
                if structured_intent.authorization_scope.value
                else None
            ),
            confidence=confidence,
            version=1,
        )

        db.add(intent)
        await db.flush()

        return ParseResult(
            status=ParseStatus.PARSED,
            intent_id=str(intent.id),
            version=intent.version,
            structured_intent=structured_intent,
            confidence=confidence,
            ambiguities=[],
        )
