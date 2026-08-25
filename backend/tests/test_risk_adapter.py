"""Tests for RiskAdapter and Decision Engine risk integration.

Tests that RiskAdapter correctly maps risk levels to decision signals.
Tests that DecisionEngine processes risk signals correctly.
"""

from decimal import Decimal

from app.services.decision_engine.engine import DecisionEngine
from app.services.decision_engine.models import DecisionContext, DecisionStatus
from app.services.decision_engine.risk_adapter import RiskAdapter
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import (
    ComponentScores,
    RiskContext,
    RiskLevel,
    RiskResult,
    VelocityContext,
)


def _make_ctx(**overrides) -> RiskContext:
    defaults = {
        "user_id": "u1",
        "agent_id": "a1",
        "intent_id": "i1",
        "intent_version": 1,
    }
    defaults.update(overrides)
    return RiskContext(**defaults)


def _make_decision_ctx(**overrides) -> DecisionContext:
    defaults = {
        "user_id": "u1",
        "agent_id": "a1",
        "intent_id": "i1",
        "intent_version": 1,
        "intent_status": "active",
        "intent_transaction_type": "purchase",
        "proposal_intent_id": "i1",
        "proposal_transaction_type": "purchase",
        "proposal_merchant_trusted": True,
        "drift_result_available": True,
        "drift_overall_status": "match",
        "drift_severity": "none",
        "policy_result_available": True,
    }
    defaults.update(overrides)
    return DecisionContext(**defaults)


def _make_risk_result(
    level: RiskLevel = RiskLevel.LOW,
    score: float = 0.1,
    confidence: float = 0.9,
) -> RiskResult:
    return RiskResult(
        overall_score=score,
        risk_level=level,
        confidence=confidence,
        component_scores=ComponentScores(),
        signals=[],
        signal_count=0,
        evaluation_id="test",
    )


# ── RiskAdapter Mapping ────────────────────────────────────────────


class TestRiskAdapter:
    def test_critical_maps_to_violation(self):
        result = _make_risk_result(level=RiskLevel.CRITICAL, score=0.80)
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert len(signals) == 1
        assert signals[0].status == "violation"

    def test_high_maps_to_negative(self):
        result = _make_risk_result(level=RiskLevel.HIGH, score=0.60)
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert len(signals) == 1
        assert signals[0].status == "negative"

    def test_medium_maps_to_negative(self):
        result = _make_risk_result(level=RiskLevel.MEDIUM, score=0.35)
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert len(signals) == 1
        assert signals[0].status == "negative"

    def test_low_maps_to_positive(self):
        result = _make_risk_result(level=RiskLevel.LOW, score=0.10)
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert len(signals) == 1
        assert signals[0].status == "positive"

    def test_low_confidence_overrides_to_unknown(self):
        result = _make_risk_result(level=RiskLevel.HIGH, confidence=0.2)
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert signals[0].status == "unknown"

    def test_signal_source_is_risk(self):
        result = _make_risk_result()
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert signals[0].source == "risk"

    def test_evidence_contains_score(self):
        result = _make_risk_result(score=0.62)
        adapter = RiskAdapter()
        signals = adapter.to_signals(result)
        assert signals[0].evidence["overall_score"] == 0.62


# ── Decision Engine + Risk Integration ─────────────────────────────


class TestDecisionEngineRiskIntegration:
    def test_no_risk_result_backward_compat(self):
        """When risk_result is None, Decision Engine behaves as Sprint 6."""
        ctx = _make_decision_ctx(risk_result=None)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        # Should work exactly as before
        allowed = (DecisionStatus.ALLOW, DecisionStatus.REVIEW, DecisionStatus.BLOCK)
        assert result.decision in allowed
        risk_signals = [s for s in result.signals if s.source == "risk"]
        assert len(risk_signals) == 0

    def test_critical_risk_adds_review(self):
        """Critical risk should contribute to REVIEW or BLOCK."""
        risk = _make_risk_result(level=RiskLevel.CRITICAL, score=0.80)
        ctx = _make_decision_ctx(risk_result=risk)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        risk_signals = [s for s in result.signals if s.source == "risk"]
        assert len(risk_signals) == 1
        assert risk_signals[0].status == "violation"

    def test_high_risk_adds_negative_signal(self):
        risk = _make_risk_result(level=RiskLevel.HIGH, score=0.60)
        ctx = _make_decision_ctx(risk_result=risk)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        risk_signals = [s for s in result.signals if s.source == "risk"]
        assert len(risk_signals) == 1
        assert risk_signals[0].status == "negative"

    def test_low_risk_adds_positive_signal(self):
        risk = _make_risk_result(level=RiskLevel.LOW, score=0.10)
        ctx = _make_decision_ctx(risk_result=risk)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        risk_signals = [s for s in result.signals if s.source == "risk"]
        assert len(risk_signals) == 1
        assert risk_signals[0].status == "positive"

    def test_risk_summary_populated(self):
        risk = _make_risk_result(level=RiskLevel.HIGH, score=0.60)
        ctx = _make_decision_ctx(risk_result=risk)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.risk_summary is not None
        assert result.risk_summary.available is True
        assert result.risk_summary.overall_score == 0.60


# ── End-to-End Risk → Decision ─────────────────────────────────────


class TestEndToEndRiskDecision:
    def test_full_pipeline_low_risk_allows(self):
        """Low risk + all other signals positive → ALLOW."""
        risk_ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="match",
            drift_severity="none",
            agent_trust_score=0.9,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.95,
            policy_available=True,
            proposal_amount=Decimal("3000"),
            intent_amount_max=5000.0,
        )
        risk_engine = RiskEngine()
        risk_result = risk_engine.evaluate(risk_ctx)

        decision_ctx = _make_decision_ctx(
            risk_result=risk_result,
            agent_trust_score=0.9,
            proposal_merchant_trusted=True,
            intent_confidence=0.95,
        )
        decision_engine = DecisionEngine()
        decision = decision_engine.evaluate(decision_ctx)
        assert decision.decision == DecisionStatus.ALLOW

    def test_full_pipeline_high_risk_reviews(self):
        """High risk contributes to REVIEW or BLOCK."""
        risk_ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="high",
            agent_trust_score=0.2,
            proposal_merchant_trusted=False,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.5,
            policy_available=True,
            policy_triggered_count=1,
            policy_highest_severity="medium",
            proposal_amount=Decimal("8000"),
            intent_amount_max=5000.0,
        )
        risk_engine = RiskEngine()
        risk_result = risk_engine.evaluate(risk_ctx)

        decision_ctx = _make_decision_ctx(
            risk_result=risk_result,
            agent_trust_score=0.2,
            proposal_merchant_trusted=False,
            intent_confidence=0.5,
            drift_overall_status="drift_detected",
            drift_severity="high",
            policy_highest_triggered_severity="medium",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Amount Limit",
                 "status": "triggered",
                 "highest_triggered_severity": "medium",
                 "categories": ["amount_limit"]},
            ],
            policy_triggered_count=1,
        )
        decision_engine = DecisionEngine()
        decision = decision_engine.evaluate(decision_ctx)
        # High drift + risk + trust issues → BLOCK or REVIEW
        assert decision.decision in (DecisionStatus.REVIEW, DecisionStatus.BLOCK)
