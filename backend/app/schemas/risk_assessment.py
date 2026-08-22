"""Pydantic schemas for RiskAssessment model."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RiskAssessmentCreate(BaseModel):
    transaction_id: uuid.UUID
    overall_score: float | None = None
    intent_match_score: float | None = None
    behavioral_risk: float | None = None
    agent_trust_score: float | None = None
    policy_risk: float | None = None
    velocity_risk: float | None = None
    merchant_risk: float | None = None
    model_version: str | None = None
    features: dict[str, Any] | None = None


class RiskAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    overall_score: float | None
    intent_match_score: float | None
    behavioral_risk: float | None
    agent_trust_score: float | None
    policy_risk: float | None
    velocity_risk: float | None
    merchant_risk: float | None
    model_version: str | None
    created_at: datetime
