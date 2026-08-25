"""Risk Adapter — thin integration between Risk Engine and Decision Engine.

This is the ONLY place where risk_level maps to DecisionSignal status.
DecisionEngine core remains risk-agnostic.
"""

from __future__ import annotations

from app.services.decision_engine.models import DecisionSignal
from app.services.risk_engine.models import RiskLevel, RiskResult


class RiskAdapter:
    """Converts RiskResult into DecisionSignals for the DecisionEngine."""

    def to_signals(self, risk_result: RiskResult) -> list[DecisionSignal]:
        """Convert RiskResult to DecisionSignals."""
        signals: list[DecisionSignal] = []

        level = risk_result.risk_level
        score = risk_result.overall_score
        confidence = risk_result.confidence

        # Map risk level to decision signal status
        if level == RiskLevel.CRITICAL:
            status = "violation"
        elif level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
            status = "negative"
        elif level == RiskLevel.LOW:
            status = "positive"
        else:
            status = "unknown"

        # Low confidence overrides to unknown
        if confidence < 0.3:
            status = "unknown"

        # Build top signal descriptions
        top_signals = sorted(
            risk_result.signals,
            key=lambda s: s.risk_contribution,
            reverse=True,
        )[:3]
        signal_descriptions = "; ".join(
            s.what for s in top_signals if s.risk_contribution > 0
        )

        signals.append(DecisionSignal(
            source="risk",
            signal_type="risk_assessment",
            status=status,
            severity=level.value,
            description=(
                f"Risk assessment: {level.value} "
                f"(score: {score:.2f}, confidence: {confidence:.2f}). "
                f"{signal_descriptions}"
            ).strip(),
            evidence={
                "overall_score": score,
                "risk_level": level.value,
                "confidence": confidence,
                "model_version": risk_result.risk_model_version,
                "signal_count": risk_result.signal_count,
            },
        ))

        return signals
