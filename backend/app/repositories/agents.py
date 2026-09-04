"""Agent repository — data access for agent entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
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

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[Agent], int]:
        """List agents for a user with pagination.

        Returns (agents, total_count).
        """
        # Count query
        count_result = await self.db.execute(
            select(func.count()).select_from(Agent).where(Agent.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Data query
        result = await self.db.execute(
            select(Agent)
            .where(Agent.user_id == user_id)
            .order_by(Agent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        agents = result.scalars().all()
        return agents, total

    async def update(
        self,
        agent: Agent,
        *,
        name: str | None = None,
        description: str | None = None,
        external_reference: str | None = None,
        status: str | None = None,
    ) -> Agent:
        """Update agent fields. Only non-None values are applied."""
        if name is not None:
            agent.name = name
        if description is not None:
            agent.description = description
        if external_reference is not None:
            agent.external_reference = external_reference
        if status is not None:
            agent.status = status
        await self.db.flush()
        return agent
