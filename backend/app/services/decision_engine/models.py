"""Decision Engine domain models.

Strongly typed Pydantic models for the Decision Engine pipeline.
These models are framework-independent and contain no database/HTTP/LLM dependencies.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.services.risk_engine.models import RiskResult

# ── Enums ──────────────────────────────────────────────────────────


class DecisionStatus(StrEnum):
    """Final transaction disposition."""

    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


# ── Decision Signal ────────────────────────────────────────────────


class DecisionSignal(BaseModel):
    """A single signal that influenced the decision.

    Each signal represents one observation from an upstream engine or trust check.
    """

    source: str = Field(
        ...,
        description=(
            "Which engine/check produced this signal: "
            "'validation', 'policy', 'drift', 'trust', 'intent'"
        ),
    )
    signal_type: str = Field(
        ...,
        description="Specific signal identifier, e.g. 'policy_triggered', 'merchant_trust_unknown'",
    )
    status: str = Field(
        ...,
        description=(
            "Signal classification: 'violation', 'triggered', "
            "'unknown', 'positive', 'negative', 'neutral'"
        ),
    )
    severity: str | None = Field(
        None, description="Severity if applicable (from policy or drift)"
    )
    description: str = Field(default="", description="Human-readable explanation")
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Supporting evidence data"
    )


# ── Summary Models ─────────────────────────────────────────────────


class PolicySummary(BaseModel):
    """Condensed policy evaluation summary for the decision result."""

    total_policies: int = Field(default=0, ge=0)
    triggered_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    invalid_count: int = Field(default=0, ge=0)
    highest_triggered_severity: str | None = None
    triggered_policy_names: list[str] = Field(default_factory=list)
    triggered_policy_categories: list[str] = Field(default_factory=list)


class RiskSummary(BaseModel):
    """Condensed risk assessment summary.

    In Sprint 6, available is always False.
    """

    overall_score: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: str | None = None
    available: bool = False


class DriftSummary(BaseModel):
    """Condensed drift information for the decision result."""

    overall_status: str | None = None
    severity: str | None = None
    mismatch_count: int = Field(default=0, ge=0)


# ── Risk Signal (Future — Sprint 7) ───────────────────────────────


class RiskSignal(BaseModel):
    """Abstraction for the future Risk Engine (Sprint 7+).

    Sprint 6: risk_result is always None in DecisionContext.
    Sprint 7: Risk Engine populates this model.
    """

    overall_score: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: str | None = None

    intent_match_score: float | None = None
    behavioral_risk: float | None = None
    agent_trust_score: float | None = None
    merchant_risk: float | None = None
    velocity_risk: float | None = None

    confidence: float = 0.0
    model_version: str | None = None
    explanation: str = ""
    signals: list[dict[str, Any]] = Field(default_factory=list)


# ── Decision Context ───────────────────────────────────────────────


class DecisionContext(BaseModel):
    """All signals needed for a deterministic decision.

    Every field is optional/nullable. Missing signals are interpreted
    as UNKNOWN — which generally produces REVIEW, not BLOCK or ALLOW.

    Risk Engine is NOT required in Sprint 6. risk_result=None means
    the Risk Engine is not part of the evaluation — it is NOT treated
    as an unknown signal.
    """

    # ── Identity ──────────────────────────────────────────
    user_id: str
    agent_id: str
    agent_trust_score: float | None = Field(
        default=None, description="Precomputed from Agent.trust_score"
    )

    # ── Intent ────────────────────────────────────────────
    intent_id: str
    intent_version: int = 1
    intent_status: str = "active"
    intent_confidence: float | None = None
    intent_transaction_type: str | None = None

    # ── Proposal ──────────────────────────────────────────
    proposal_intent_id: str = ""
    proposal_transaction_type: str | None = None
    proposal_amount: Decimal | None = None
    proposal_currency: str | None = None
    proposal_merchant_name: str | None = None
    proposal_merchant_trusted: bool | None = None
    proposal_country: str | None = None

    # ── Transaction Twin (Sprint 4) ───────────────────────
    drift_result_available: bool = False
    drift_overall_status: str | None = None
    drift_severity: str | None = None

    # ── Policy Engine (Sprint 5) ──────────────────────────
    policy_result_available: bool = False
    policy_triggered_count: int = Field(default=0, ge=0)
    policy_unknown_count: int = Field(default=0, ge=0)
    policy_invalid_count: int = Field(default=0, ge=0)
    policy_highest_triggered_severity: str | None = None
    policy_results_for_signals: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw policy results for building DecisionSignals",
    )

    # ── Risk Engine (Sprint 7) ──────────────────────────
    risk_result: RiskResult | None = None

    # ── Metadata ──────────────────────────────────────────
    evaluation_id: str = ""
    evaluated_at: str = ""


# ── Decision Result ────────────────────────────────────────────────


class DecisionResult(BaseModel):
    """Final deterministic decision output.

    Contains the decision, explanation, upstream summaries, and all signals
    that influenced the decision. Designed for direct frontend rendering.
    """

    decision: DecisionStatus
    reason: str
    decision_version: str = "decision-v1"

    # Identity
    evaluation_id: str
    intent_id: str
    intent_version: int
    proposal_intent_id: str

    # Upstream summaries
    policy_summary: PolicySummary | None = None
    risk_summary: RiskSummary | None = None
    drift_summary: DriftSummary | None = None

    # Signals (ordered by precedence)
    signals: list[DecisionSignal] = Field(default_factory=list)
    signal_count: int = Field(default=0, ge=0)

    # Explainability
    explanation: dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    created_at: str = ""
    evaluated_at: str = ""
