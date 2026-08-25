"""Risk Engine domain models.

Strongly typed Pydantic models for the Risk Engine pipeline.
Framework-independent. No database/HTTP/LLM dependencies.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class RiskLevel(StrEnum):
    """Risk level classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskSignalType(StrEnum):
    """Types of risk signals the engine can produce."""

    INTENT_DRIFT = "intent_drift"
    AMOUNT_ANOMALY = "amount_anomaly"
    AGENT_TRUST = "agent_trust"
    MERCHANT_TRUST = "merchant_trust"
    POLICY_INTERACTION = "policy_interaction"
    VELOCITY = "velocity"
    DATA_QUALITY = "data_quality"
    CURRENCY_MISMATCH = "currency_mismatch"
    GEOGRAPHIC_ANOMALY = "geographic_anomaly"


class SourceEngine(StrEnum):
    """Which engine or component produced the evidence."""

    INTENT_ENGINE = "intent_engine"
    TRANSACTION_TWIN = "transaction_twin"
    POLICY_ENGINE = "policy_engine"
    VELOCITY_AGGREGATOR = "velocity_aggregator"
    DATABASE = "database"
    RISK_ENGINE = "risk_engine"


# ── Velocity Context ───────────────────────────────────────────────


class VelocityContext(BaseModel):
    """Pre-computed velocity features for risk evaluation.

    Built by the API service layer from recent transaction history.
    Risk Engine consumes but does not query the database.
    """

    transactions_last_hour: int = Field(default=0, ge=0)
    transactions_last_day: int = Field(default=0, ge=0)
    transactions_last_week: int = Field(default=0, ge=0)

    total_amount_last_hour: Decimal | None = Field(default=None, ge=0)
    total_amount_last_day: Decimal | None = Field(default=None, ge=0)
    average_amount_last_day: Decimal | None = Field(default=None, ge=0)

    same_merchant_count_last_hour: int = Field(default=0, ge=0)
    same_type_count_last_hour: int = Field(default=0, ge=0)
    unique_merchants_last_day: int = Field(default=0, ge=0)

    history_available: bool = False


# ── Risk Context ───────────────────────────────────────────────────


class RiskContext(BaseModel):
    """All inputs for deterministic risk evaluation.

    Every field is nullable. Missing data reduces confidence.
    Missing data does NOT automatically increase risk.
    Explicitly negative evidence (low trust, high drift) increases risk.
    """

    # ── Identity ──────────────────────────────────────────
    user_id: str
    agent_id: str

    # ── Intent ────────────────────────────────────────────
    intent_id: str
    intent_version: int
    intent_confidence: float | None = None
    intent_transaction_type: str | None = None
    intent_amount_max: float | None = None
    intent_amount_min: float | None = None
    intent_currency: str | None = None
    intent_merchant_trust_required: bool = False
    intent_country: str | None = None

    # ── Proposal ──────────────────────────────────────────
    proposal_amount: Decimal | None = None
    proposal_currency: str | None = None
    proposal_transaction_type: str | None = None
    proposal_merchant_name: str | None = None
    proposal_merchant_trusted: bool | None = None
    proposal_country: str | None = None

    # ── Drift (from Transaction Twin) ─────────────────────
    drift_available: bool = False
    drift_overall_status: str | None = None
    drift_severity: str | None = None
    drift_amount_deviation_percent: Decimal | None = None

    # ── Policy (from Policy Engine) ───────────────────────
    policy_available: bool = False
    policy_triggered_count: int = Field(default=0, ge=0)
    policy_unknown_count: int = Field(default=0, ge=0)
    policy_invalid_count: int = Field(default=0, ge=0)
    policy_highest_severity: str | None = None

    # ── Trust (from database) ─────────────────────────────
    agent_trust_score: float | None = None
    merchant_trust_score: float | None = None

    # ── Velocity (pre-computed by API layer) ──────────────
    velocity: VelocityContext | None = None


# ── Risk Evidence ──────────────────────────────────────────────────


class RiskEvidence(BaseModel):
    """A single risk signal with full provenance and explainability."""

    signal_type: RiskSignalType

    # Risk contribution (0.0–1.0) — how much this signal adds to overall risk
    risk_contribution: float = Field(ge=0.0, le=1.0)

    # Individual confidence for this specific signal (0.0–1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Human-readable: what was observed
    what: str = Field(default="", description="What was observed")

    # Human-readable: why it constitutes risk
    why: str = Field(default="", description="Why this constitutes risk")

    # Structured evidence for the frontend
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value evidence for rendering",
    )

    # Signal-level risk classification (optional)
    risk_level: str | None = Field(
        None,
        description="Signal-level risk: low/medium/high/critical, or None",
    )

    # Provenance
    source_engine: SourceEngine = Field(
        ...,
        description="Which engine produced this evidence",
    )
    source_fields: list[str] = Field(
        default_factory=list,
        description="Specific fields from the source used",
    )


# ── Component Scores ───────────────────────────────────────────────


class ComponentScores(BaseModel):
    """Sub-scores for each risk dimension."""

    intent_match: float | None = Field(default=None, ge=0.0, le=1.0)
    agent_trust: float | None = Field(default=None, ge=0.0, le=1.0)
    merchant_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    policy_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    velocity_risk: float | None = Field(default=None, ge=0.0, le=1.0)
    amount_anomaly: float | None = Field(default=None, ge=0.0, le=1.0)
    data_quality: float | None = Field(default=None, ge=0.0, le=1.0)


# ── Risk Result ────────────────────────────────────────────────────


class RiskResult(BaseModel):
    """Complete risk assessment with explainability chain.

    The Risk Engine produces this. The Decision Engine consumes it.
    This does NOT contain ALLOW/REVIEW/BLOCK — that is the Decision Engine's job.
    """

    overall_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)

    # Component sub-scores
    component_scores: ComponentScores

    # Evidence chain (ordered by risk_contribution descending)
    signals: list[RiskEvidence] = Field(default_factory=list)
    signal_count: int = Field(default=0, ge=0)

    # Explainability
    summary: str = ""

    # Metadata
    evaluation_id: str = ""
    risk_model_version: str = "deterministic-v1"
    evaluator_version: str = "risk-v1"
    feature_version: str = "v1"
    evaluated_at: str = ""
