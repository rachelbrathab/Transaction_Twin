"""Pydantic schemas for Intent model."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class IntentCreate(BaseModel):
    user_id: uuid.UUID
    agent_id: uuid.UUID
    original_request: str
    structured_intent: dict[str, Any] | None = None
    currency: str = "INR"
    min_amount: float | None = None
    max_amount: float | None = None
    authorization_scope: str | None = None


class IntentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    agent_id: uuid.UUID
    original_request: str
    status: str
    currency: str
    min_amount: float | None
    max_amount: float | None
    authorization_scope: str | None
    confidence: float | None
    version: int
    created_at: datetime
    updated_at: datetime
