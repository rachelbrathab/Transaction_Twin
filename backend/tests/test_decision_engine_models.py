"""Tests for Decision Engine domain models."""

from decimal import Decimal

from app.services.decision_engine.models import (
    DecisionContext,
    DecisionResult,
    DecisionSignal,
    DecisionStatus,
    DriftSummary,
    PolicySummary,
    RiskSignal,
    RiskSummary,
)


class TestDecisionStatus:
    def test_allow_value(self):
        assert DecisionStatus.ALLOW.value == "allow"

    def test_review_value(self):
        assert DecisionStatus.REVIEW.value == "review"

    def test_block_value(self):
        assert DecisionStatus.BLOCK.value == "block"

    def test_all_statuses_exist(self):
        assert len(DecisionStatus) == 3


class TestDecisionSignal:
    def test_basic_signal(self):
        sig = DecisionSignal(
            source="policy",
            signal_type="policy_triggered",
            status="triggered",
            severity="high",
            description="Policy triggered",
        )
        assert sig.source == "policy"
        assert sig.signal_type == "policy_triggered"
        assert sig.status == "triggered"
        assert sig.severity == "high"

    def test_signal_with_evidence(self):
        sig = DecisionSignal(
            source="trust",
            signal_type="agent_trust_low",
            status="negative",
            evidence={"trust_score": 0.2},
        )
        assert sig.evidence["trust_score"] == 0.2

    def test_signal_defaults(self):
        sig = DecisionSignal(
            source="test", signal_type="test", status="neutral"
        )
        assert sig.severity is None
        assert sig.description == ""
        assert sig.evidence == {}


class TestPolicySummary:
    def test_defaults(self):
        s = PolicySummary()
        assert s.total_policies == 0
        assert s.triggered_count == 0
        assert s.triggered_policy_names == []

    def test_with_values(self):
        s = PolicySummary(
            total_policies=5,
            triggered_count=2,
            highest_triggered_severity="high",
            triggered_policy_names=["p1", "p2"],
        )
        assert s.total_policies == 5
        assert s.triggered_count == 2


class TestRiskSummary:
    def test_unavailable(self):
        s = RiskSummary()
        assert s.available is False
        assert s.overall_score is None

    def test_available(self):
        s = RiskSummary(available=True, overall_score=0.8, risk_level="low")
        assert s.available is True
        assert s.overall_score == 0.8


class TestDriftSummary:
    def test_defaults(self):
        s = DriftSummary()
        assert s.overall_status is None
        assert s.mismatch_count == 0

    def test_with_values(self):
        s = DriftSummary(overall_status="match", severity="none", mismatch_count=0)
        assert s.overall_status == "match"


class TestRiskSignal:
    def test_future_model(self):
        rs = RiskSignal(overall_score=0.5, risk_level="medium")
        assert rs.overall_score == 0.5
        assert rs.available if hasattr(rs, "available") else True

    def test_defaults(self):
        rs = RiskSignal()
        assert rs.overall_score is None
        assert rs.risk_level is None


class TestDecisionContext:
    def test_minimal_context(self):
        ctx = DecisionContext(
            user_id="u1",
            agent_id="a1",
            intent_id="i1",
        )
        assert ctx.user_id == "u1"
        assert ctx.agent_trust_score is None
        assert ctx.drift_result_available is False
        assert ctx.policy_result_available is False
        assert ctx.risk_result is None

    def test_full_context(self):
        ctx = DecisionContext(
            user_id="u1",
            agent_id="a1",
            agent_trust_score=0.8,
            intent_id="i1",
            intent_version=2,
            intent_status="active",
            intent_confidence=0.95,
            intent_transaction_type="purchase",
            proposal_intent_id="i1",
            proposal_transaction_type="purchase",
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_merchant_name="Amazon",
            proposal_merchant_trusted=True,
            proposal_country="IN",
            drift_result_available=True,
            drift_overall_status="match",
            drift_severity="none",
            policy_result_available=True,
            policy_triggered_count=0,
            risk_result=None,
        )
        assert ctx.agent_trust_score == 0.8
        assert ctx.proposal_amount == Decimal("5000")

    def test_risk_none_not_unknown(self):
        """risk_result=None means Risk Engine is not part of evaluation,
        NOT that risk is unknown."""
        ctx = DecisionContext(
            user_id="u1", agent_id="a1", intent_id="i1", risk_result=None
        )
        assert ctx.risk_result is None


class TestDecisionResult:
    def test_minimal_result(self):
        result = DecisionResult(
            decision=DecisionStatus.ALLOW,
            reason="All conditions satisfied",
            evaluation_id="eval1",
            intent_id="i1",
            intent_version=1,
            proposal_intent_id="i1",
        )
        assert result.decision == DecisionStatus.ALLOW
        assert result.signal_count == 0
        assert result.signals == []

    def test_with_signals(self):
        sig = DecisionSignal(
            source="policy", signal_type="policy_triggered", status="triggered"
        )
        result = DecisionResult(
            decision=DecisionStatus.REVIEW,
            reason="Policy triggered",
            evaluation_id="eval1",
            intent_id="i1",
            intent_version=1,
            proposal_intent_id="i1",
            signals=[sig],
            signal_count=1,
        )
        assert result.signal_count == 1
        assert result.signals[0].source == "policy"

    def test_decision_version(self):
        result = DecisionResult(
            decision=DecisionStatus.ALLOW,
            reason="ok",
            evaluation_id="e",
            intent_id="i",
            intent_version=1,
            proposal_intent_id="i",
        )
        assert result.decision_version == "decision-v1"
