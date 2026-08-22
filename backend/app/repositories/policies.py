"""Policy repository — data access for policy entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy


class PolicyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        description: str | None = None,
        version: int = 1,
        rules: dict | None = None,
        scope: dict | None = None,
    ) -> Policy:
        policy = Policy(
            user_id=user_id,
            name=name,
            description=description,
            version=version,
            rules=rules,
            scope=scope,
        )
        self.db.add(policy)
        await self.db.flush()
        return policy

    async def get_by_id(self, policy_id: uuid.UUID) -> Policy | None:
        return await self.db.get(Policy, policy_id)

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[Policy]:
        result = await self.db.execute(select(Policy).where(Policy.user_id == user_id))
        return result.scalars().all()
