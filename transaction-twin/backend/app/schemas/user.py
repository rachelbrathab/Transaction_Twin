"""Pydantic schemas for User model."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    display_name: str
    external_reference: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_reference: str | None
    display_name: str
    status: str
    created_at: datetime
    updated_at: datetime
