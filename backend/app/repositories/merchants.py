"""Merchant repository — data access for merchant entities."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant


class MerchantRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        name: str,
        external_reference: str | None = None,
        category: str | None = None,
        country: str | None = None,
    ) -> Merchant:
        merchant = Merchant(
            name=name,
            external_reference=external_reference,
            category=category,
            country=country,
        )
        self.db.add(merchant)
        await self.db.flush()
        return merchant

    async def get_by_id(self, merchant_id: uuid.UUID) -> Merchant | None:
        return await self.db.get(Merchant, merchant_id)
