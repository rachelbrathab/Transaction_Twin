"""Pydantic schemas for Merchant model."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MerchantCreate(BaseModel):
    name: str
    external_reference: str | None = None
    category: str | None = None
    country: str | None = None


class MerchantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_reference: str | None
    name: str
    category: str | None
    country: str | None
    trust_score: float | None
    status: str
    created_at: datetime
    updated_at: datetime
