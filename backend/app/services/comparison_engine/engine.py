"""Comparison Engine — main orchestrator.

Deterministically compares a StructuredIntent against a TransactionProposal.
No database dependency. No HTTP dependency. No LLM dependency. No side effects.

Database/API orchestration belongs outside this core comparator.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog

from app.services.comparison_engine.aggregator import (
    aggregate_counts,
    compute_drift_severity,
    compute_overall_status,
    generate_summary,
)
from app.services.comparison_engine.comparator import (
    compare_amount,
    compare_authorization_scope,
    compare_category,
    compare_currency,
    compare_geographic,
    compare_merchant,
    compare_product_attributes,
    compare_temporal,
    compare_transaction_type,
)
from app.services.comparison_engine.models import (
    DriftResult,
    FieldComparisonResult,
    FieldStatus,
    OverallStatus,
    TransactionProposal,
)
from app.services.intent_engine.models import StructuredIntent

logger = structlog.get_logger()

# Valid currencies for proposal validation
_VALID_CURRENCIES = frozenset({"INR", "USD", "EUR", "GBP"})


class ComparisonEngine:
    """Deterministic Transaction Twin comparator.

    Compares a StructuredIntent against a TransactionProposal.
    The core comparator has no database, HTTP, LLM, or side effects.
    """

    def compare(
        self,
        intent: StructuredIntent,
        proposal: TransactionProposal,
        *,
        intent_id: str | None = None,
        intent_version: int | None = None,
    ) -> DriftResult:
        """Compare intent against proposal. Pure function — no side effects."""
        start_time = time.monotonic()
        comparison_id = str(uuid.uuid4())[:8]

        log = logger.bind(
            comparison_id=comparison_id,
            intent_id=intent_id or proposal.intent_id,
        )

        # Validate proposal
        validation_result = self._validate_proposal(proposal)
        if validation_result is not None:
            log.info("invalid_proposal", reason=validation_result)
            return DriftResult(
                intent_id=intent_id or proposal.intent_id,
                intent_version=intent_version or 1,
                proposal_intent_id=proposal.intent_id,
                overall_status=OverallStatus.INVALID_PROPOSAL,
                drift_severity="none",
                rejection_reason=validation_result,
                compared_at=datetime.now(UTC).isoformat(),
            )

        # Validate ownership match
        ownership_error = self._validate_ownership(intent, proposal)
        if ownership_error is not None:
            log.info("ownership_mismatch", reason=ownership_error)
            return DriftResult(
                intent_id=intent_id or proposal.intent_id,
                intent_version=intent_version or 1,
                proposal_intent_id=proposal.intent_id,
                overall_status=OverallStatus.INVALID_PROPOSAL,
                drift_severity="none",
                rejection_reason=ownership_error,
                compared_at=datetime.now(UTC).isoformat(),
            )

        # Validate intent is active
        # (intent status check is done at API layer; here we trust the caller)

        # Run field-by-field comparisons
        comparisons: list[FieldComparisonResult] = [
            compare_transaction_type(intent, proposal),
            compare_amount(intent, proposal),
            compare_currency(intent, proposal),
            compare_category(intent, proposal),
            compare_product_attributes(intent, proposal),
            compare_merchant(intent, proposal),
            compare_geographic(intent, proposal),
            compare_temporal(intent, proposal),
            compare_authorization_scope(intent, proposal),
        ]

        # Aggregate
        overall_status = compute_overall_status(comparisons)
        severity = compute_drift_severity(comparisons)
        match_count, mismatch_count, unknown_count, not_applicable_count = (
            aggregate_counts(comparisons)
        )

        # Build result
        result = DriftResult(
            intent_id=intent_id or proposal.intent_id,
            intent_version=intent_version or 1,
            proposal_intent_id=proposal.intent_id,
            overall_status=overall_status,
            drift_severity=severity,
            field_comparisons=comparisons,
            match_count=match_count,
            mismatch_count=mismatch_count,
            unknown_count=unknown_count,
            not_applicable_count=not_applicable_count,
            intent_confidence=float(intent.metadata.confidence)
            if hasattr(intent.metadata, "confidence")
            else None,
            compared_at=datetime.now(UTC).isoformat(),
        )

        # Generate summary
        result.summary = generate_summary(result)

        # Log
        latency_ms = int((time.monotonic() - start_time) * 1000)
        log.info(
            "comparison_completed",
            overall_status=result.overall_status.value,
            drift_severity=result.drift_severity.value,
            match_count=match_count,
            mismatch_count=mismatch_count,
            latency_ms=latency_ms,
        )

        if mismatch_count > 0:
            log.warning(
                "intent_drift_detected",
                mismatched_fields=[
                    fr.field for fr in comparisons if fr.status == FieldStatus.MISMATCH
                ],
            )

        return result

    def _validate_proposal(self, proposal: TransactionProposal) -> str | None:
        """Validate proposal structure. Returns error message or None.

        INVALID_PROPOSAL is reserved for malformed/invalid input.
        Missing nullable fields are valid — they produce UNKNOWN.
        """
        # Amount must be non-negative
        if proposal.amount is not None and proposal.amount < 0:
            return "amount must be non-negative"

        # Currency must be 3-char alphabetic if provided
        if proposal.currency is not None:
            if len(proposal.currency) != 3 or not proposal.currency.isalpha():
                return f"invalid currency code: {proposal.currency}"

        return None

    def _validate_ownership(
        self,
        intent: StructuredIntent,
        proposal: TransactionProposal,
    ) -> str | None:
        """Validate that proposal references match intent ownership.

        Cross-user or cross-agent comparison is not allowed.
        Ownership validation is done at the API layer via the database.
        Here we only validate that the proposal's user_id and agent_id
        are present and well-formed UUIDs.
        """
        try:
            uuid.UUID(proposal.user_id)
        except ValueError:
            return f"invalid user_id format: {proposal.user_id}"

        try:
            uuid.UUID(proposal.agent_id)
        except ValueError:
            return f"invalid agent_id format: {proposal.agent_id}"

        try:
            uuid.UUID(proposal.intent_id)
        except ValueError:
            return f"invalid intent_id format: {proposal.intent_id}"

        return None
