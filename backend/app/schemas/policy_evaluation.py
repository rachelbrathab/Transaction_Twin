"""Pydantic schemas for Policy Engine API."""

from typing import Any

from pydantic import BaseModel, Field

from app.services.policy_engine.models import (
    ConditionStatus,
    PolicyEvaluationStatus,
    PolicySeverity,
)


class PolicyEvaluationRequest(BaseModel):
    """Request body for POST /api/v1/policies/evaluate."""

    intent_id: str = Field(..., description="Intent UUID to evaluate against")
    proposal: dict[str, Any] = Field(
        ..., description="TransactionProposal as JSON object"
    )


class ConditionResultResponse(BaseModel):
    """Single condition evaluation in API response."""

    field: str
    operator: str
    expected_value: Any = None
    observed_value: Any = None
    status: ConditionStatus
    explanation: str = ""


class RuleResultResponse(BaseModel):
    """Single rule evaluation in API response."""

    name: str
    description: str
    category: str
    severity: PolicySeverity
    status: PolicyEvaluationStatus
    condition_results: list[ConditionResultResponse] = Field(default_factory=list)
    explanation: str = ""


class PolicyResultResponse(BaseModel):
    """Single policy evaluation in API response."""

    policy_id: str
    policy_version: int
    policy_name: str
    status: PolicyEvaluationStatus
    rule_results: list[RuleResultResponse] = Field(default_factory=list)
    matched_rule_count: int = Field(default=0, ge=0)
    triggered_rule_count: int = Field(default=0, ge=0)
    unknown_rule_count: int = Field(default=0, ge=0)
    highest_triggered_severity: PolicySeverity = PolicySeverity.NONE
    explanation: str = ""


class PolicyEvaluationResponse(BaseModel):
    """Response body for POST /api/v1/policies/evaluate."""

    intent_id: str
    proposal_intent_id: str
    evaluation_id: str
    policy_results: list[PolicyResultResponse] = Field(default_factory=list)
    total_policies: int = Field(default=0, ge=0)
    triggered_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    invalid_count: int = Field(default=0, ge=0)
    pass_count: int = Field(default=0, ge=0)
    highest_severity: PolicySeverity = PolicySeverity.NONE
    summary: str = ""
    evaluated_at: str = ""
    evaluator_version: str = "policy-v1"
