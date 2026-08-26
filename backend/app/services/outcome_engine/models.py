"""Outcome Engine domain models.

Strongly typed enums and Pydantic models for transaction lifecycle,
event ingestion, and feedback classification.

No database, no SQLAlchemy, no external dependencies beyond Pydantic.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class TransactionLifecycle(StrEnum):
    """Transaction lifecycle states."""

    PROPOSED = "proposed"
    DECIDED = "decided"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    CHARGEBACK = "chargeback"
    DISPUTED = "disputed"


class OutcomeEventType(StrEnum):
    """Types of outcome events."""

    DECISION_CREATED = "decision_created"
    PAYMENT_INITIATED = "payment_initiated"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_CANCELLED = "payment_cancelled"
    PAYMENT_EXPIRED = "payment_expired"
    REFUND_INITIATED = "refund_initiated"
    REFUND_COMPLETED = "refund_completed"
    PARTIAL_REFUND = "partial_refund"
    CHARGEBACK_RECEIVED = "chargeback_received"
    DISPUTE_OPENED = "dispute_opened"
    DISPUTE_RESOLVED = "dispute_resolved"
    MANUAL_APPROVED = "manual_approved"
    MANUAL_REJECTED = "manual_rejected"
    FRAUD_CONFIRMED = "fraud_confirmed"
    FRAUD_FALSE_POSITIVE = "fraud_false_positive"


class OutcomeSource(StrEnum):
    """Provenance of the outcome event."""

    PAYMENT_PROVIDER = "payment_provider"
    MERCHANT = "merchant"
    USER = "user"
    ADMIN = "admin"
    MANUAL_REVIEW = "manual_review"
    SYSTEM = "system"
    SIMULATOR = "simulator"


class VerificationState(StrEnum):
    """Verification level of an outcome event."""

    VERIFIED = "verified"
    PENDING = "pending"
    UNVERIFIED = "unverified"


class FeedbackType(StrEnum):
    """Classification of decision correctness."""

    CORRECT_ALLOW = "correct_allow"
    CORRECT_BLOCK = "correct_block"
    CORRECT_REVIEW = "correct_review"
    POSSIBLE_FALSE_POSITIVE = "possible_false_positive"
    POSSIBLE_FALSE_NEGATIVE = "possible_false_negative"
    UNKNOWN = "unknown"


# ── Models ─────────────────────────────────────────────────────────


class OutcomeEvent(BaseModel):
    """A single outcome event applied to a transaction."""

    event_id: str = Field(
        ...,
        description="Unique event identifier (generated server-side)",
    )
    transaction_id: str = Field(..., description="Transaction UUID")
    event_type: OutcomeEventType
    source: OutcomeSource
    verification_state: VerificationState = VerificationState.PENDING
    provider: str | None = Field(
        default=None,
        description="Payment provider name if applicable",
    )
    external_event_id: str | None = Field(
        default=None,
        description="Provider's external event ID for idempotency",
    )
    provider_timestamp: datetime | None = Field(
        default=None,
        description="Timestamp from the external provider",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event metadata",
    )
    sequence_number: int = Field(
        ...,
        description="Monotonically increasing sequence within the transaction",
        ge=1,
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="Server-side ingestion timestamp",
    )


class FeedbackClassification(BaseModel):
    """Deterministic classification of decision correctness."""

    feedback_type: FeedbackType
    confidence: float = Field(
        ...,
        description="Confidence in the classification (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        ...,
        description="Human-readable explanation of the classification",
    )
    decision_value: str = Field(
        ...,
        description="The original decision (allow/review/block)",
    )
    outcome_event_type: str = Field(
        ...,
        description="The outcome event type that triggered classification",
    )
    verification_state: VerificationState = Field(
        ...,
        description="Verification level of the outcome",
    )


class TransactionEventRecord(BaseModel):
    """Simplified event record for history display."""

    event_id: str
    event_type: str
    source: str
    verification_state: str
    sequence_number: int
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class TransactionHistory(BaseModel):
    """Complete transaction history with lifecycle and feedback."""

    transaction_id: str
    current_status: str
    decision: str
    events: list[TransactionEventRecord] = Field(default_factory=list)
    feedback: FeedbackClassification | None = None
