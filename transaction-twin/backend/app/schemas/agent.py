"""Pydantic schemas for Agent and AgentCapability models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentCapabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    capability: str


class AgentCreate(BaseModel):
    user_id: uuid.UUID
    name: str
    description: str | None = None
    external_reference: str | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    external_reference: str | None
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
