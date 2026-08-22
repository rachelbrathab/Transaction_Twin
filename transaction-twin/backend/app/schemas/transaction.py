"""Pydantic schemas for Transaction model."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TransactionCreate(BaseModel):
    user_id: uuid.UUID
    agent_id: uuid.UUID
    intent_id: uuid.UUID
    policy_id: uuid.UUID | None = None
    merchant_id: uuid.UUID | None = None
    idempotency_key: uuid.UUID
    transaction_type: str
    amount: float
    currency: str = "INR"


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    agent_id: uuid.UUID
    intent_id: uuid.UUID
    policy_id: uuid.UUID | None
    merchant_id: uuid.UUID | None
    transaction_type: str
    amount: float
    currency: str
    status: str
    created_at: datetime
    updated_at: datetime
