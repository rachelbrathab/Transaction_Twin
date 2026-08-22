"""Transaction repository — data access for transaction entities."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction


class TransactionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        agent_id: uuid.UUID,
        intent_id: uuid.UUID,
        idempotency_key: uuid.UUID,
        transaction_type: str,
        amount: float,
        currency: str = "INR",
        policy_id: uuid.UUID | None = None,
        merchant_id: uuid.UUID | None = None,
    ) -> Transaction:
        transaction = Transaction(
            user_id=user_id,
            agent_id=agent_id,
            intent_id=intent_id,
            idempotency_key=idempotency_key,
            transaction_type=transaction_type,
            amount=amount,
            currency=currency,
            policy_id=policy_id,
            merchant_id=merchant_id,
        )
        self.db.add(transaction)
        await self.db.flush()
        return transaction

    async def get_by_id(self, transaction_id: uuid.UUID) -> Transaction | None:
        return await self.db.get(Transaction, transaction_id)

    async def get_by_idempotency_key(
        self, agent_id: uuid.UUID, idempotency_key: uuid.UUID
    ) -> Transaction | None:
        """Look up existing transaction by agent-scoped idempotency key."""
        result = await self.db.execute(
            select(Transaction).where(
                Transaction.agent_id == agent_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()
