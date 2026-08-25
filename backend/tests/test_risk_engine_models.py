"""Tests for Risk Engine domain models."""

from decimal import Decimal

from app.services.risk_engine.models import (
    ComponentScores,
    RiskContext,
    RiskEvidence,
    RiskLevel,
    RiskResult,
    RiskSignalType,
    SourceEngine,
    VelocityContext,
)


class TestRiskLevel:
    def test_all_levels_exist(self):
        assert len(RiskLevel) == 4

    def test_low_value(self):
        assert RiskLevel.LOW.value == "low"

    def test_critical_value(self):
        assert RiskLevel.CRITICAL.value == "critical"


class TestRiskSignalType:
    def test_all_types_exist(self):
        assert len(RiskSignalType) == 9

    def test_intent_drift_value(self):
        assert RiskSignalType.INTENT_DRIFT.value == "intent_drift"

    def test_data_quality_value(self):
        assert RiskSignalType.DATA_QUALITY.value == "data_quality"


class TestSourceEngine:
    def test_all_sources_exist(self):
        assert len(SourceEngine) == 6

    def test_risk_engine_value(self):
        assert SourceEngine.RISK_ENGINE.value == "risk_engine"


class TestVelocityContext:
    def test_defaults(self):
        vc = VelocityContext()
        assert vc.transactions_last_hour == 0
        assert vc.history_available is False

    def test_with_values(self):
        vc = VelocityContext(
            transactions_last_hour=5,
            transactions_last_day=20,
            total_amount_last_hour=Decimal("50000"),
            history_available=True,
        )
        assert vc.transactions_last_hour == 5
        assert vc.total_amount_last_hour == Decimal("50000")

    def test_validation_negative_rejected(self):
        try:
            VelocityContext(transactions_last_hour=-1)
            assert False, "Should have raised validation error"
        except Exception:
            pass


class TestRiskContext:
    def test_minimal_context(self):
        ctx = RiskContext(
            user_id="u1",
            agent_id="a1",
            intent_id="i1",
            intent_version=1,
        )
        assert ctx.user_id == "u1"
        assert ctx.drift_available is False
        assert ctx.policy_available is False
        assert ctx.velocity is None

    def test_full_context(self):
        ctx = RiskContext(
            user_id="u1",
            agent_id="a1",
            intent_id="i1",
            intent_version=1,
            intent_confidence=0.9,
            intent_amount_max=5000.0,
            proposal_amount=Decimal("3000"),
            proposal_currency="INR",
            drift_available=True,
            drift_overall_status="match",
            drift_severity="none",
            policy_available=True,
            agent_trust_score=0.8,
            velocity=VelocityContext(history_available=True),
        )
        assert ctx.proposal_amount == Decimal("3000")
        assert ctx.drift_available is True


class TestRiskEvidence:
    def test_basic_evidence(self):
        e = RiskEvidence(
            signal_type=RiskSignalType.AGENT_TRUST,
            risk_contribution=0.15,
            confidence=1.0,
            what="Agent trust low",
            why="Score below threshold",
            source_engine=SourceEngine.DATABASE,
        )
        assert e.signal_type == RiskSignalType.AGENT_TRUST
        assert e.risk_contribution == 0.15

    def test_bounds_validation(self):
        try:
            RiskEvidence(
                signal_type=RiskSignalType.AGENT_TRUST,
                risk_contribution=1.5,
                confidence=1.0,
                source_engine=SourceEngine.DATABASE,
            )
            assert False, "Should have raised validation error"
        except Exception:
            pass

    def test_negative_contribution_rejected(self):
        try:
            RiskEvidence(
                signal_type=RiskSignalType.AGENT_TRUST,
                risk_contribution=-0.1,
                confidence=1.0,
                source_engine=SourceEngine.DATABASE,
            )
            assert False, "Should have raised validation error"
        except Exception:
            pass

    def test_with_evidence(self):
        e = RiskEvidence(
            signal_type=RiskSignalType.AMOUNT_ANOMALY,
            risk_contribution=0.25,
            confidence=1.0,
            what="Amount exceeds max",
            why="Exceeds boundary",
            evidence={"proposal": 8000, "max": 5000},
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["proposal_amount", "intent_amount_max"],
        )
        assert e.evidence["proposal"] == 8000
        assert len(e.source_fields) == 2


class TestComponentScores:
    def test_defaults(self):
        cs = ComponentScores()
        assert cs.intent_match is None
        assert cs.agent_trust is None

    def test_with_values(self):
        cs = ComponentScores(
            intent_match=0.3,
            agent_trust=0.15,
            merchant_risk=0.0,
        )
        assert cs.intent_match == 0.3


class TestRiskResult:
    def test_minimal_result(self):
        r = RiskResult(
            overall_score=0.0,
            risk_level=RiskLevel.LOW,
            confidence=1.0,
            component_scores=ComponentScores(),
        )
        assert r.overall_score == 0.0
        assert r.risk_level == RiskLevel.LOW
        assert r.signal_count == 0

    def test_full_result(self):
        sig = RiskEvidence(
            signal_type=RiskSignalType.INTENT_DRIFT,
            risk_contribution=0.35,
            confidence=1.0,
            what="Drift detected",
            why="High drift",
            source_engine=SourceEngine.TRANSACTION_TWIN,
        )
        r = RiskResult(
            overall_score=0.62,
            risk_level=RiskLevel.HIGH,
            confidence=0.85,
            component_scores=ComponentScores(intent_match=0.55),
            signals=[sig],
            signal_count=1,
            summary="High risk",
            evaluation_id="test-123",
        )
        assert r.overall_score == 0.62
        assert r.signal_count == 1
        assert r.evaluation_id == "test-123"
