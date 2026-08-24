"""Pydantic schemas for Comparison Engine API."""

from typing import Any

from pydantic import BaseModel, Field

from app.services.comparison_engine.models import (
    DriftSeverity,
    FieldStatus,
    OverallStatus,
)


class ComparisonRequest(BaseModel):
    """Request body for POST /api/v1/comparisons/compare."""

    proposal: dict[str, Any] = Field(
        ..., description="TransactionProposal as JSON object"
    )


class FieldComparisonResponse(BaseModel):
    """Single field comparison in API response."""

    field: str
    status: FieldStatus
    drift_category: str
    severity: DriftSeverity
    intent_value: Any = None
    intent_evidence: dict[str, Any] | None = None
    proposal_value: Any = None
    explanation: str = ""
    drift: dict[str, Any] | None = None


class ComparisonResponse(BaseModel):
    """Response body for POST /api/v1/comparisons/compare."""

    intent_id: str
    intent_version: int
    proposal_intent_id: str
    overall_status: OverallStatus
    drift_severity: DriftSeverity
    field_comparisons: list[FieldComparisonResponse]
    match_count: int
    mismatch_count: int
    unknown_count: int
    not_applicable_count: int
    intent_confidence: float | None = None
    summary: str
    rejection_reason: str | None = None
    compared_at: str
    comparator_version: str = "twin-v1"
