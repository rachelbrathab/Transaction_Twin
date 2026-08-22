"""TransactionEvent repository — data access for transaction event entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction_event import TransactionEvent


class TransactionEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        transaction_id: uuid.UUID,
        agent_id: uuid.UUID,
        sequence_number: int,
        event_type: str,
        payload: dict | None = None,
    ) -> TransactionEvent:
        event = TransactionEvent(
            transaction_id=transaction_id,
            agent_id=agent_id,
            sequence_number=sequence_number,
            event_type=event_type,
            payload=payload,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_by_transaction(self, transaction_id: uuid.UUID) -> Sequence[TransactionEvent]:
        result = await self.db.execute(
            select(TransactionEvent)
            .where(TransactionEvent.transaction_id == transaction_id)
            .order_by(TransactionEvent.sequence_number)
        )
        return result.scalars().all()
