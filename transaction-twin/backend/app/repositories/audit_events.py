"""AuditEvent repository — append-only audit trail."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent


class AuditEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        event_type: str,
        actor_type: str | None = None,
        actor_id: uuid.UUID | None = None,
        metadata: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            metadata_=metadata,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    # No update/delete methods — audit events are append-only by design.
    # Database-level enforcement will be strengthened in Sprint 12.
