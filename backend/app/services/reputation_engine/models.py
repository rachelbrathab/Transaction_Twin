"""Reputation Engine domain models.

Strongly typed Pydantic models for agent behavioral reputation.
Framework-independent. No database/HTTP/LLM dependencies.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class ReputationDimension(StrEnum):
    """Individual reputation dimensions."""

    SUCCESS_RATE = "success_rate"
    POLICY_COMPLIANCE = "policy_compliance"
    DRIFT_BEHAVIOR = "drift_behavior"
    RISK_PROFILE = "risk_profile"
    CONSISTENCY = "consistency"
    LONGEVITY = "longevity"
    AMOUNT_BEHAVIOR = "amount_behavior"


class ReputationChange(StrEnum):
    """Direction of reputation change."""

    IMPROVED = "improved"
    DECLINED = "declined"
    STABLE = "stable"
    NEW_AGENT = "new_agent"


class TrustLevel(StrEnum):
    """Trust level classification derived from reputation score."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNESTABLISHED = "unestablished"


# ── Behavioral Context ─────────────────────────────────────────────


class BehavioralContext(BaseModel):
    """Pre-computed behavioral features for an agent.

    Built by the API/service layer from bounded historical queries.
    Reputation Engine consumes but does not query the database.
    """

    agent_id: str
    user_id: str

    # ── Transaction Counts ─────────────────────────────────
    total_transactions: int = Field(default=0, ge=0)
    transactions_last_hour: int = Field(default=0, ge=0)
    transactions_last_day: int = Field(default=0, ge=0)
    transactions_last_week: int = Field(default=0, ge=0)
    transactions_last_month: int = Field(default=0, ge=0)

    # ── Decision Outcomes ──────────────────────────────────
    total_decisions: int = Field(default=0, ge=0)
    allow_count: int = Field(default=0, ge=0)
    review_count: int = Field(default=0, ge=0)
    block_count: int = Field(default=0, ge=0)

    # Recent decisions (last 30 days)
    recent_allow_count: int = Field(default=0, ge=0)
    recent_review_count: int = Field(default=0, ge=0)
    recent_block_count: int = Field(default=0, ge=0)

    # ── Policy Violations ──────────────────────────────────
    total_policy_violations: int = Field(default=0, ge=0)
    recent_policy_violations: int = Field(default=0, ge=0)
    critical_violations: int = Field(default=0, ge=0)
    high_violations: int = Field(default=0, ge=0)

    # ── Drift History ──────────────────────────────────────
    total_drift_events: int = Field(default=0, ge=0)
    critical_drift_count: int = Field(default=0, ge=0)
    high_drift_count: int = Field(default=0, ge=0)

    # ── Amount Patterns ────────────────────────────────────
    average_transaction_amount: float | None = None
    max_transaction_amount: float | None = None
    amount_stddev: float | None = None

    # ── Merchant Diversity ─────────────────────────────────
    unique_merchants_all_time: int = Field(default=0, ge=0)
    unique_merchants_last_week: int = Field(default=0, ge=0)

    # ── Temporal Patterns ──────────────────────────────────
    first_transaction_at: str | None = None  # ISO 8601
    last_transaction_at: str | None = None  # ISO 8601
    account_age_days: int | None = None

    # ── Risk Assessment History ────────────────────────────
    average_risk_score: float | None = None
    max_risk_score: float | None = None
    critical_risk_count: int = Field(default=0, ge=0)

    # ── Data Completeness ──────────────────────────────────
    history_available: bool = False
    decision_history_available: bool = False
    risk_history_available: bool = False


# ── Dimension Score ────────────────────────────────────────────────


class DimensionScore(BaseModel):
    """A single reputation dimension with evidence."""

    dimension: ReputationDimension
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    weighted_contribution: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    what: str = ""
    why: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


# ── Reputation Result ──────────────────────────────────────────────


class ReputationResult(BaseModel):
    """Complete reputation assessment.

    Stored in Agent.reputation_snapshot as JSONB.
    Trust score is computed as derived_trust_score.
    """

    # ── Overall ────────────────────────────────────────────
    overall_score: float = Field(ge=0.0, le=1.0)
    trust_level: TrustLevel

    # ── Dimensions ─────────────────────────────────────────
    dimensions: list[DimensionScore]

    # ── Change Detection ───────────────────────────────────
    previous_score: float | None = None
    change: ReputationChange
    change_magnitude: float = Field(default=0.0, ge=0.0, le=1.0)
    change_reasons: list[str] = Field(default_factory=list)

    # ── Explainability ─────────────────────────────────────
    summary: str = ""
    explanation: dict[str, Any] = Field(default_factory=dict)

    # ── Metadata ───────────────────────────────────────────
    evaluation_id: str = ""
    agent_id: str = ""
    evaluated_at: str = ""
    history_window_days: int = 90
    model_version: str = "reputation-v1"
    feature_version: str = "v1"
