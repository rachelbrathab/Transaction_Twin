"""Ownership validation helpers.

Cross-table ownership constraints cannot be fully enforced by FK alone.
Service/repository layer must call these before INSERT operations.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.intent import Intent


async def validate_agent_belongs_to_user(
    db: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """Verify that the agent belongs to the specified user.

    Raises ValueError if agent doesn't exist or belongs to a different user.
    """
    result = await db.execute(
        select(Agent.id, Agent.user_id).where(Agent.id == agent_id)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError(f"Agent {agent_id} does not exist.")
    if row.user_id != user_id:
        raise ValueError(
            f"Agent {agent_id} belongs to user {row.user_id}, not {user_id}."
        )


async def validate_intent_ownership(
    db: AsyncSession,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    intent_id: uuid.UUID,
) -> None:
    """Verify intent belongs to the specified user and agent.

    Raises ValueError if intent doesn't exist or ownership is inconsistent.
    """
    result = await db.execute(
        select(Intent.id, Intent.user_id, Intent.agent_id).where(Intent.id == intent_id)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError(f"Intent {intent_id} does not exist.")
    if row.user_id != user_id:
        raise ValueError(
            f"Intent {intent_id} belongs to user {row.user_id}, not {user_id}."
        )
    if row.agent_id != agent_id:
        raise ValueError(
            f"Intent {intent_id} was created for agent {row.agent_id}, not {agent_id}."
        )
