"""Pydantic schemas for Decision Engine API."""

from typing import Any

from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    """Request body for POST /api/v1/transactions/decide."""

    intent_id: str = Field(..., description="Intent UUID to evaluate against")
    proposal: dict[str, Any] = Field(
        ..., description="Transaction proposal fields (TransactionProposal-compatible)"
    )


class DecisionSignalResponse(BaseModel):
    source: str
    signal_type: str
    status: str
    severity: str | None = None
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class PolicySummaryResponse(BaseModel):
    total_policies: int = 0
    triggered_count: int = 0
    unknown_count: int = 0
    invalid_count: int = 0
    highest_triggered_severity: str | None = None
    triggered_policy_names: list[str] = Field(default_factory=list)
    triggered_policy_categories: list[str] = Field(default_factory=list)


class RiskSummaryResponse(BaseModel):
    overall_score: float | None = None
    risk_level: str | None = None
    available: bool = False


class DriftSummaryResponse(BaseModel):
    overall_status: str | None = None
    severity: str | None = None
    mismatch_count: int = 0


class DecisionResponse(BaseModel):
    """Response body for POST /api/v1/transactions/decide."""

    decision: str
    reason: str
    decision_version: str
    evaluation_id: str
    intent_id: str
    intent_version: int
    proposal_intent_id: str
    policy_summary: PolicySummaryResponse | None = None
    risk_summary: RiskSummaryResponse | None = None
    drift_summary: DriftSummaryResponse | None = None
    signals: list[DecisionSignalResponse] = Field(default_factory=list)
    signal_count: int = 0
    explanation: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    evaluated_at: str = ""
