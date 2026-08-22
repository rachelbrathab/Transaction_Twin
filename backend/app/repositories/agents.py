"""Agent repository — data access for agent entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent


class AgentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        description: str | None = None,
        external_reference: str | None = None,
    ) -> Agent:
        agent = Agent(
            user_id=user_id,
            name=name,
            description=description,
            external_reference=external_reference,
        )
        self.db.add(agent)
        await self.db.flush()
        return agent

    async def get_by_id(self, agent_id: uuid.UUID) -> Agent | None:
        return await self.db.get(Agent, agent_id)

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[Agent]:
        result = await self.db.execute(select(Agent).where(Agent.user_id == user_id))
        return result.scalars().all()
