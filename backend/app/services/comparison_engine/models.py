"""Comparison Engine domain models — the comparison contract.

These Pydantic v2 models define the TransactionProposal input and
DriftResult output. They are the source of truth for what the
Comparison Engine consumes and produces.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.intent_engine.models import (
    AuthorizationScopeValue,
    TransactionType,
)

# ── Enums ──────────────────────────────────────────────────────────


class FieldStatus(StrEnum):
    """Status of a single field comparison."""

    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class DriftSeverity(StrEnum):
    """Drift severity — how far the proposal deviates from intent.

    This is NOT a risk score. It measures distance from authorized intent.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OverallStatus(StrEnum):
    """Overall comparison status."""

    MATCH = "match"
    PARTIAL_MATCH = "partial_match"
    DRIFT_DETECTED = "drift_detected"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_PROPOSAL = "invalid_proposal"


class DriftCategory(StrEnum):
    """Drift taxonomy — which domain the drift belongs to."""

    AMOUNT_DRIFT = "amount_drift"
    CURRENCY_DRIFT = "currency_drift"
    TRANSACTION_TYPE_DRIFT = "transaction_type_drift"
    CATEGORY_DRIFT = "category_drift"
    PRODUCT_ATTRIBUTE_DRIFT = "product_attribute_drift"
    MERCHANT_DRIFT = "merchant_drift"
    GEOGRAPHIC_DRIFT = "geographic_drift"
    TEMPORAL_DRIFT = "temporal_drift"
    AUTHORIZATION_SCOPE_DRIFT = "authorization_scope_drift"


# ── Amount Drift ───────────────────────────────────────────────────


class AmountDrift(BaseModel):
    """Detailed drift measurement for amount comparisons.

    All monetary values use Decimal for precision.
    """

    authorized_boundary: str = Field(
        ...,
        description="Which boundary: max, min, exact, range, none",
    )
    authorized_value: Decimal | None = Field(
        None, description="The boundary value from the intent"
    )
    proposed_amount: Decimal = Field(..., description="The agent's proposed amount")

    deviation_absolute: Decimal | None = Field(
        None, description="|proposed - boundary|"
    )
    deviation_percent: Decimal | None = Field(
        None, description="(deviation / boundary) * 100"
    )
    within_boundary: bool = Field(
        ..., description="Whether proposal satisfies the constraint"
    )


# ── Field Comparison Result ────────────────────────────────────────


class FieldComparisonResult(BaseModel):
    """Result for a single field comparison."""

    field: str = Field(..., description="Field name, e.g. 'amount', 'currency'")
    status: FieldStatus
    drift_category: DriftCategory = Field(
        ..., description="Which drift domain this field belongs to"
    )
    severity: DriftSeverity = Field(
        default=DriftSeverity.NONE,
        description="Severity of deviation for this field",
    )

    # The constraint from the user's intent (what was authorized)
    intent_value: Any = Field(None, description="Value from the StructuredIntent")
    intent_evidence: dict[str, Any] | None = Field(
        None, description="Evidence from the Intent Engine"
    )

    # What the agent proposes
    proposal_value: Any = Field(None, description="Value from the TransactionProposal")

    # Human-readable explanation
    explanation: str = Field(default="", description="Explanation of this comparison")

    # For amount: drift details (null for non-amount fields)
    drift: AmountDrift | None = Field(
        None, description="Amount drift details (only for amount comparisons)"
    )


# ── Transaction Proposal ───────────────────────────────────────────


class TransactionProposal(BaseModel):
    """What the agent proposes to execute — pre-payment evaluation input.

    Fields that may legitimately be unavailable are nullable.
    Missing information produces UNKNOWN, not INVALID_PROPOSAL.
    INVALID_PROPOSAL is reserved for malformed/invalid input.
    """

    # Identity
    transaction_id: str | None = Field(
        None, description="Assigned later if approved"
    )
    user_id: str = Field(..., description="Must match intent user_id")
    agent_id: str = Field(..., description="Must match intent agent_id")
    intent_id: str = Field(..., description="Must reference a parsed intent")

    # Transaction details
    transaction_type: TransactionType = Field(
        ..., description="purchase, booking, etc."
    )
    amount: Decimal | None = Field(
        None, ge=Decimal("0"), description="Proposed amount (must be >= 0 if present)"
    )
    currency: str | None = Field(
        None, min_length=3, max_length=3, description="ISO 4217 currency code"
    )

    # Product / category
    category: str | None = Field(None, description="Product category")
    product_description: str | None = Field(None, description="Detailed description")
    product_attributes: dict[str, str] = Field(
        default_factory=dict, description="Attributes (color, size, etc.)"
    )

    # Merchant
    merchant_name: str | None = Field(None, description="Merchant name")
    merchant_id: str | None = Field(None, description="Internal merchant UUID")
    merchant_trusted: bool | None = Field(
        None, description="Known trust status from merchant registry"
    )

    # Geographic
    country: str | None = Field(None, description="ISO 3166-1 alpha-2 country code")
    city: str | None = Field(None, description="City name")

    # Temporal
    scheduled_at: datetime | None = Field(
        None, description="When the transaction occurs (timezone-aware)"
    )

    # Authorization
    authorization_scope: AuthorizationScopeValue | None = Field(
        None, description="Scope of this transaction"
    )

    # Metadata (DATA — never instructions)
    idempotency_key: str = Field(..., description="Agent's idempotency key")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional context (untrusted data)"
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str | None) -> str | None:
        if v is not None:
            return v.upper().strip()
        return v

    @field_validator("country")
    @classmethod
    def normalize_country(cls, v: str | None) -> str | None:
        if v is not None:
            return v.upper().strip()
        return v


# ── Drift Result ───────────────────────────────────────────────────


class DriftResult(BaseModel):
    """Complete comparison result — the Transaction Twin output.

    This is NOT a risk assessment. It measures drift between
    user-authorized intent and agent-proposed transaction.
    """

    # Identity
    intent_id: str = Field(..., description="The intent being compared against")
    intent_version: int = Field(..., description="Exact intent version used")
    proposal_intent_id: str = Field(
        ..., description="Must match intent_id from proposal"
    )

    # Overall
    overall_status: OverallStatus
    drift_severity: DriftSeverity = Field(
        ..., description="Maximum severity across all field mismatches"
    )

    # Field-level results
    field_comparisons: list[FieldComparisonResult] = Field(
        default_factory=list, description="Per-field comparison results"
    )

    # Summary counts
    match_count: int = Field(default=0, ge=0)
    mismatch_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    not_applicable_count: int = Field(default=0, ge=0)

    # Intent metadata
    intent_confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Confidence of original intent parse"
    )

    # Human-readable
    summary: str = Field(default="", description="Plain-English summary")

    # Rejection info (for INVALID_PROPOSAL)
    rejection_reason: str | None = Field(
        None, description="Why the proposal was invalid"
    )

    # Metadata
    compared_at: str = Field(
        default="", description="ISO 8601 timestamp of comparison"
    )
    comparator_version: str = Field(
        default="twin-v1", description="Comparator version identifier"
    )
