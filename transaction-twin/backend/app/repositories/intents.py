"""Intent repository — data access for intent entities."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intent import Intent


class IntentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        agent_id: uuid.UUID,
        original_request: str,
        **kwargs,
    ) -> Intent:
        intent = Intent(
            user_id=user_id,
            agent_id=agent_id,
            original_request=original_request,
            **kwargs,
        )
        self.db.add(intent)
        await self.db.flush()
        return intent

    async def get_by_id(self, intent_id: uuid.UUID) -> Intent | None:
        return await self.db.get(Intent, intent_id)
