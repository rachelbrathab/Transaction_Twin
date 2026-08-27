"""Calibration Intelligence domain models.

Strongly typed enums and Pydantic models for verified-outcome-based
calibration analysis and advisory recommendations.

No database, no SQLAlchemy, no external dependencies beyond Pydantic.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class RecommendationStatus(StrEnum):
    """Status of a calibration recommendation."""

    GENERATED = "generated"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"
    SUPERSEDED = "superseded"


class RecommendationType(StrEnum):
    """Type of calibration recommendation."""

    WEIGHT_REVIEW = "weight_review"
    THRESHOLD_REVIEW = "threshold_review"
    CONFIDENCE_REVIEW = "confidence_review"
    POLICY_REVIEW = "policy_review"
    REPUTATION_REVIEW = "reputation_review"
    BEHAVIORAL_REVIEW = "behavioral_review"
    NETWORK_REVIEW = "network_review"
    SUMMARY = "summary"


class DataSufficiencyLevel(StrEnum):
    """Data sufficiency classification."""

    INSUFFICIENT = "insufficient"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class SampleExclusionReason(StrEnum):
    """Why a calibration sample was excluded."""

    UNKNOWN_FEEDBACK = "unknown_feedback"
    UNVERIFIED_OUTCOME = "unverified_outcome"
    PENDING_OUTCOME = "pending_outcome"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_DECISION = "missing_decision"
    MISSING_TRANSACTION = "missing_transaction"


# ── Calibration Sample ─────────────────────────────────────────────


class CalibrationSample(BaseModel):
    """A single eligible record for calibration analysis."""

    transaction_id: str
    decision_id: str
    original_decision: str
    final_lifecycle_status: str
    feedback_type: str
    feedback_confidence: float = Field(ge=0.0, le=1.0)
    verification_state: str
    risk_level: str | None = None
    risk_available: bool = False
    signal_count: int = Field(default=0, ge=0)
    policy_triggered_count: int = Field(default=0, ge=0)
    policy_id: str | None = None
    drift_severity: str | None = None
    agent_id: str | None = None
    amount: float | None = None
    currency: str | None = None
    transaction_type: str | None = None
    created_at: str = ""
    sample_eligible: bool = True
    exclusion_reason: str | None = None


# ── Calibration Dataset ────────────────────────────────────────────


class CalibrationDataset(BaseModel):
    """Complete calibration dataset built from verified evidence."""

    samples: list[CalibrationSample] = Field(default_factory=list)
    total_samples: int = Field(default=0, ge=0)
    eligible_samples: int = Field(default=0, ge=0)
    excluded_samples: int = Field(default=0, ge=0)
    exclusion_summary: dict[str, int] = Field(default_factory=dict)
    window_days: int = 30
    computed_at: str = ""


# ── Metric Result ──────────────────────────────────────────────────


class MetricResult(BaseModel):
    """A single calibration metric with full provenance."""

    metric_name: str
    value: float | None = None
    sample_count: int = Field(default=0, ge=0)
    data_sufficiency: DataSufficiencyLevel = DataSufficiencyLevel.INSUFFICIENT
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


# ── Risk Cross-Tabulation ──────────────────────────────────────────


class RiskOutcomeCrossTab(BaseModel):
    """Cross-tabulation of risk level vs verified outcome."""

    risk_level: str
    correct_allow: int = Field(default=0, ge=0)
    correct_block: int = Field(default=0, ge=0)
    correct_review: int = Field(default=0, ge=0)
    false_positive: int = Field(default=0, ge=0)
    false_negative: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


# ── Policy Effectiveness ───────────────────────────────────────────


class PolicyEffectiveness(BaseModel):
    """Per-policy calibration analysis using verified outcomes."""

    policy_id: str
    policy_name: str
    total_evaluations: int = Field(default=0, ge=0)
    correct_block_count: int = Field(default=0, ge=0)
    false_positive_count: int = Field(default=0, ge=0)
    false_negative_count: int = Field(default=0, ge=0)
    correct_allow_count: int = Field(default=0, ge=0)
    trigger_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    fp_rate: float | None = None
    fn_rate: float | None = None
    effectiveness_score: float | None = None
    data_sufficiency: DataSufficiencyLevel = DataSufficiencyLevel.INSUFFICIENT


# ── Agent Effectiveness ────────────────────────────────────────────


class AgentEffectiveness(BaseModel):
    """Per-agent calibration analysis using verified outcomes."""

    agent_id: str
    agent_name: str | None = None
    total_verified: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    false_positive_count: int = Field(default=0, ge=0)
    false_negative_count: int = Field(default=0, ge=0)
    correct_rate: float | None = None
    reputation_level: str | None = None
    reputation_score: float | None = None
    data_sufficiency: DataSufficiencyLevel = DataSufficiencyLevel.INSUFFICIENT


# ── Calibration Recommendation ─────────────────────────────────────


class CalibrationRecommendation(BaseModel):
    """An advisory calibration recommendation.

    GENERATED recommendations MUST NOT affect runtime behavior.
    Activation requires explicit human approval.
    """

    recommendation_id: str
    recommendation_type: RecommendationType
    engine: str
    parameter: str | None = None
    current_value: Any | None = None
    proposed_value: Any | None = None
    proposed_range: tuple[float, float] | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    sample_count: int = Field(default=0, ge=0)
    data_sufficiency: DataSufficiencyLevel = DataSufficiencyLevel.INSUFFICIENT
    rationale: str = ""
    severity: str = "info"
    generated_at: str = ""
    calibration_version: str = ""
    status: RecommendationStatus = RecommendationStatus.GENERATED


# ── Calibration Version ────────────────────────────────────────────


class CalibrationVersion(BaseModel):
    """A versioned calibration snapshot."""

    version_id: str
    generated_at: str = ""
    source_window_days: int = 30
    total_samples: int = Field(default=0, ge=0)
    eligible_samples: int = Field(default=0, ge=0)
    excluded_samples: int = Field(default=0, ge=0)
    recommendation_count: int = Field(default=0, ge=0)
    parameter_snapshot: dict[str, Any] | None = None
    activated_at: str | None = None
    activated_by: str | None = None
    previous_version: str | None = None
    status: str = RecommendationStatus.GENERATED


# ── Calibration Intelligence Result ────────────────────────────────


class CalibrationIntelligenceResult(BaseModel):
    """Complete calibration intelligence analysis."""

    dataset: CalibrationDataset
    metrics: list[MetricResult] = Field(default_factory=list)
    risk_cross_tab: list[RiskOutcomeCrossTab] = Field(default_factory=list)
    policy_effectiveness: list[PolicyEffectiveness] = Field(default_factory=list)
    agent_effectiveness: list[AgentEffectiveness] = Field(default_factory=list)
    recommendations: list[CalibrationRecommendation] = Field(
        default_factory=list,
    )
    version: CalibrationVersion | None = None
    computed_at: str = ""
