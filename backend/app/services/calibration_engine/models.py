"""Calibration Engine domain models.

Strongly typed Pydantic models for decision calibration analytics.
Framework-independent. No database/HTTP/LLM dependencies.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class DataSufficiencyLevel(StrEnum):
    """Data sufficiency classification."""

    INSUFFICIENT = "insufficient"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class FindingSeverity(StrEnum):
    """Severity of a calibration finding."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class FindingType(StrEnum):
    """Type of calibration finding."""

    DRIFT_DETECTED = "drift_detected"
    HIGH_TRIGGER_RATE = "high_trigger_rate"
    UNSTABLE_AGENT = "unstable_agent"
    IMPROVING_AGENT = "improving_agent"
    DECLINING_AGENT = "declining_agent"
    SIGNAL_DOMINANCE = "signal_dominance"
    INSUFFICIENT_DATA = "insufficient_data"
    SYSTEM_SUMMARY = "system_summary"


# ── Data Sufficiency ───────────────────────────────────────────────


class DataSufficiency(BaseModel):
    """Whether enough data exists for reliable analysis."""

    sample_count: int = Field(ge=0)
    level: DataSufficiencyLevel
    explanation: str = ""


# ── Decision Distribution ──────────────────────────────────────────


class DecisionDistribution(BaseModel):
    """Distribution of decision outcomes."""

    total: int = Field(ge=0)
    allow_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    allow_rate: float = Field(ge=0.0, le=1.0)
    review_rate: float = Field(ge=0.0, le=1.0)
    block_rate: float = Field(ge=0.0, le=1.0)
    sample_count: int = Field(ge=0)


# ── Risk Level Distribution ────────────────────────────────────────


class RiskLevelDistribution(BaseModel):
    """Distribution of risk levels from decision explanations."""

    total_with_risk: int = Field(ge=0)
    low_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    risk_unavailable_count: int = Field(ge=0)


# ── Signal Contribution ────────────────────────────────────────────


class SignalContribution(BaseModel):
    """How a signal source contributes to decisions."""

    source: str
    appeared_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    violation_count: int = Field(ge=0)
    contribution_rate: float = Field(ge=0.0, le=1.0)


class SignalContributionDistribution(BaseModel):
    """Distribution of all signal sources."""

    signals: list[SignalContribution] = Field(default_factory=list)
    total_decisions: int = Field(default=0, ge=0)


# ── Policy Analysis ────────────────────────────────────────────────


class PolicyDecisionSummary(BaseModel):
    """Per-policy calibration analysis."""

    policy_id: str
    policy_name: str
    evaluation_count: int = Field(ge=0)
    trigger_count: int = Field(ge=0)
    trigger_rate: float = Field(ge=0.0, le=1.0)
    invalid_count: int = Field(ge=0)
    highest_severity_seen: str | None = None
    associated_allow: int = Field(default=0, ge=0)
    associated_review: int = Field(default=0, ge=0)
    associated_block: int = Field(default=0, ge=0)


# ── Agent Analysis ─────────────────────────────────────────────────


class AgentDecisionSummary(BaseModel):
    """Per-agent decision pattern analysis."""

    agent_id: str
    agent_name: str | None = None
    total_decisions: int = Field(default=0, ge=0)
    allow_rate: float = Field(ge=0.0, le=1.0)
    review_rate: float = Field(ge=0.0, le=1.0)
    block_rate: float = Field(ge=0.0, le=1.0)
    avg_signal_count: float = Field(ge=0.0)
    drift_severity_distribution: dict[str, int] = Field(default_factory=dict)
    reputation_score: float | None = None
    data_sufficiency: DataSufficiency = Field(default_factory=lambda: DataSufficiency(
        sample_count=0, level=DataSufficiencyLevel.INSUFFICIENT
    ))


# ── Drift Detection ────────────────────────────────────────────────


class DriftDetection(BaseModel):
    """Detection of changes in system behavior between periods."""

    metric_name: str
    baseline_value: float
    current_value: float
    change_ratio: float
    is_drifting: bool
    explanation: str = ""
    baseline_sample_count: int = Field(ge=0)
    current_sample_count: int = Field(ge=0)


# ── Calibration Finding ────────────────────────────────────────────


class CalibrationFinding(BaseModel):
    """A single explanatory finding from calibration analysis."""

    finding_type: FindingType
    severity: FindingSeverity
    title: str
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    sample_count: int = Field(ge=0)
    data_sufficiency: DataSufficiencyLevel = DataSufficiencyLevel.INSUFFICIENT


# ── Calibration Context ────────────────────────────────────────────


class DecisionRecord(BaseModel):
    """A single decision record extracted from the database.

    Contains decision data plus AuditEvent metadata.
    """

    decision_id: str
    decision: str  # "allow", "review", "block"
    policy_id: str | None = None
    reason: str | None = None
    explanation: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: str = ""

    # From AuditEvent metadata
    evaluation_id: str | None = None
    intent_id: str | None = None
    signal_count: int = 0
    policy_triggered_count: int = 0
    drift_severity: str | None = None
    risk_available: bool = False


class AgentRecord(BaseModel):
    """Agent information for calibration."""

    agent_id: str
    agent_name: str | None = None
    reputation_snapshot: dict[str, Any] | None = None


class PolicyRecord(BaseModel):
    """Policy metadata for calibration."""

    policy_id: str
    policy_name: str
    policy_version: int = 1


class CalibrationContext(BaseModel):
    """All data needed for deterministic calibration analysis.

    Built by the API service layer from bounded SQL queries.
    Calibration Engine consumes but does not query the database.
    """

    user_id: str
    decisions: list[DecisionRecord] = Field(default_factory=list)
    agents: list[AgentRecord] = Field(default_factory=list)
    policies: list[PolicyRecord] = Field(default_factory=list)

    # Time window
    window_days: int = 30
    baseline_window_days: int = 60

    # Optional filters
    filter_agent_id: str | None = None
    filter_policy_id: str | None = None


# ── Calibration Result ─────────────────────────────────────────────


class CalibrationResult(BaseModel):
    """Complete calibration analysis result."""

    # Summary
    decision_distribution: DecisionDistribution
    risk_level_distribution: RiskLevelDistribution
    signal_distribution: SignalContributionDistribution
    policy_summaries: list[PolicyDecisionSummary] = Field(default_factory=list)
    agent_summaries: list[AgentDecisionSummary] = Field(default_factory=list)
    drift_detections: list[DriftDetection] = Field(default_factory=list)
    findings: list[CalibrationFinding] = Field(default_factory=list)

    # Data quality
    data_sufficiency: DataSufficiency
    merchant_analysis: str = (
        "NOT_AVAILABLE — Merchant attribution is unavailable because "
        "historical decisions do not contain a reliable transaction/merchant "
        "relationship."
    )

    # Metadata
    computed_at: str = ""
    window_days: int = 30
    total_decisions_analyzed: int = 0
