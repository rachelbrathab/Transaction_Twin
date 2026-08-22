"""RiskAssessment repository — data access for risk assessment entities."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk_assessment import RiskAssessment


class RiskAssessmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        transaction_id: uuid.UUID,
        overall_score: float | None = None,
        intent_match_score: float | None = None,
        behavioral_risk: float | None = None,
        agent_trust_score: float | None = None,
        policy_risk: float | None = None,
        velocity_risk: float | None = None,
        merchant_risk: float | None = None,
        model_version: str | None = None,
        features: dict | None = None,
    ) -> RiskAssessment:
        assessment = RiskAssessment(
            transaction_id=transaction_id,
            overall_score=overall_score,
            intent_match_score=intent_match_score,
            behavioral_risk=behavioral_risk,
            agent_trust_score=agent_trust_score,
            policy_risk=policy_risk,
            velocity_risk=velocity_risk,
            merchant_risk=merchant_risk,
            model_version=model_version,
            features=features,
        )
        self.db.add(assessment)
        await self.db.flush()
        return assessment

    async def get_by_id(self, assessment_id: uuid.UUID) -> RiskAssessment | None:
        return await self.db.get(RiskAssessment, assessment_id)
