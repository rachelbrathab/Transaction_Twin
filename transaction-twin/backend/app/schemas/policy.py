"""Pydantic schemas for Policy model."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PolicyCreate(BaseModel):
    user_id: uuid.UUID
    name: str
    description: str | None = None
    version: int = 1
    rules: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
