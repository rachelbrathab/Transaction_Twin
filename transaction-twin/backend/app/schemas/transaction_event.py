"""Pydantic schemas for TransactionEvent model."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TransactionEventCreate(BaseModel):
    transaction_id: uuid.UUID
    agent_id: uuid.UUID
    sequence_number: int
    event_type: str
    payload: dict[str, Any] | None = None


class TransactionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    agent_id: uuid.UUID
    sequence_number: int
    event_type: str
    created_at: datetime
