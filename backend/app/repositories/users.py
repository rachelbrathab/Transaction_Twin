"""User repository — data access for user entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, *, display_name: str, external_reference: str | None = None) -> User:
        user = User(display_name=display_name, external_reference=external_reference)
        self.db.add(user)
        await self.db.flush()
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_external_reference(self, ref: str) -> User | None:
        result = await self.db.execute(select(User).where(User.external_reference == ref))
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[User]:
        result = await self.db.execute(select(User))
        return result.scalars().all()
