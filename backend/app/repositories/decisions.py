"""Decision repository — data access for decision entities."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision import Decision


class DecisionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        transaction_id: uuid.UUID,
        decision: str,
        reason: str | None = None,
        explanation: dict | None = None,
        risk_assessment_id: uuid.UUID | None = None,
        policy_id: uuid.UUID | None = None,
        version: int = 1,
    ) -> Decision:
        dec = Decision(
            transaction_id=transaction_id,
            decision=decision,
            reason=reason,
            explanation=explanation,
            risk_assessment_id=risk_assessment_id,
            policy_id=policy_id,
            version=version,
        )
        self.db.add(dec)
        await self.db.flush()
        return dec

    async def get_by_id(self, decision_id: uuid.UUID) -> Decision | None:
        return await self.db.get(Decision, decision_id)
