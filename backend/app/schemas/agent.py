"""Pydantic schemas for Agent and AgentCapability models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentCapabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    capability: str


class AgentCreate(BaseModel):
    """Request body for creating an agent.

    user_id is derived from the authenticated JWT — never from the client.
    """

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    external_reference: str | None = None


class AgentUpdate(BaseModel):
    """Request body for updating an agent.

    All fields are optional — only provided fields are updated.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    external_reference: str | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive|suspended)$")


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    external_reference: str | None
    name: str
    description: str | None
    status: str
    trust_score: float | None = None
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    """Response for listing agents."""

    agents: list[AgentRead]
    total: int
