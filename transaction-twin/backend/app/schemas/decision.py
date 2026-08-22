"""Pydantic schemas for Decision model."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DecisionCreate(BaseModel):
    transaction_id: uuid.UUID
    decision: str
    reason: str | None = None
    explanation: dict[str, Any] | None = None
    risk_assessment_id: uuid.UUID | None = None
    policy_id: uuid.UUID | None = None
    version: int = 1


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    decision: str
    reason: str | None
    risk_assessment_id: uuid.UUID | None
    policy_id: uuid.UUID | None
    version: int
    override_status: str | None
    override_actor_id: str | None
    created_at: datetime
