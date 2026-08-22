"""Pydantic schemas for AuditEvent model."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventCreate(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    event_type: str
    actor_type: str | None = None
    actor_id: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    event_type: str
    actor_type: str | None
    actor_id: uuid.UUID | None
    previous_hash: str | None
    current_hash: str | None
    created_at: datetime
