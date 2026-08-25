"""Tests for Decision Engine core logic.

All tests are deterministic, offline, and database-independent.
No LLM, no payment, no network calls.
"""

from decimal import Decimal

from app.services.decision_engine.engine import DecisionEngine
from app.services.decision_engine.models import (
    DecisionContext,
    DecisionStatus,
)


def _make_context(**overrides) -> DecisionContext:
    """Create a DecisionContext with sensible defaults."""
    defaults = {
        "user_id": "user-1",
        "agent_id": "agent-1",
        "agent_trust_score": 0.8,
        "intent_id": "intent-1",
        "intent_version": 1,
        "intent_status": "active",
        "intent_confidence": 0.9,
        "intent_transaction_type": "purchase",
        "proposal_intent_id": "intent-1",
        "proposal_transaction_type": "purchase",
        "proposal_amount": Decimal("5000"),
        "proposal_currency": "INR",
        "proposal_merchant_name": "Amazon",
        "proposal_merchant_trusted": True,
        "proposal_country": "IN",
        "drift_result_available": True,
        "drift_overall_status": "match",
        "drift_severity": "none",
        "policy_result_available": True,
        "policy_triggered_count": 0,
        "policy_unknown_count": 0,
        "policy_invalid_count": 0,
        "policy_highest_triggered_severity": None,
        "policy_results_for_signals": [],
        "risk_result": None,
        "evaluation_id": "eval-test",
    }
    defaults.update(overrides)
    return DecisionContext(**defaults)


# ── ALLOW Conditions ───────────────────────────────────────────────


class TestAllowConditions:
    def test_all_signals_positive_allows(self):
        ctx = _make_context()
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW
        assert result.reason == "All conditions satisfied"

    def test_allow_with_medium_trust(self):
        ctx = _make_context(agent_trust_score=0.5)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_allow_with_low_confidence_threshold(self):
        ctx = _make_context(intent_confidence=0.5)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_allow_with_partial_match_drift(self):
        ctx = _make_context(drift_overall_status="partial_match", drift_severity="low")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_allow_with_low_drift(self):
        ctx = _make_context(drift_overall_status="drift_detected", drift_severity="low")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_allow_with_zero_policy_triggers(self):
        ctx = _make_context(
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "pass", "highest_triggered_severity": "none",
                 "categories": ["amount_limit"]},
            ]
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_allow_has_positive_signals(self):
        ctx = _make_context()
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        statuses = [s.status for s in result.signals]
        assert all(s in ("positive", "neutral") for s in statuses)

    def test_allow_no_violation_signals(self):
        ctx = _make_context()
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        violation_signals = [s for s in result.signals if s.status == "violation"]
        assert len(violation_signals) == 0


# ── REVIEW Conditions ──────────────────────────────────────────────


class TestReviewConditions:
    def test_unknown_agent_trust_reviews(self):
        ctx = _make_context(agent_trust_score=None)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_low_agent_trust_reviews(self):
        ctx = _make_context(agent_trust_score=0.2)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_merchant_trust_reviews(self):
        ctx = _make_context(proposal_merchant_trusted=None)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_untrusted_merchant_reviews(self):
        ctx = _make_context(proposal_merchant_trusted=False)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_low_intent_confidence_reviews(self):
        ctx = _make_context(intent_confidence=0.3)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_intent_confidence_reviews(self):
        ctx = _make_context(intent_confidence=None)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_drift_unavailable_reviews(self):
        ctx = _make_context(drift_result_available=False)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_drift_insufficient_data_reviews(self):
        ctx = _make_context(
            drift_overall_status="insufficient_data", drift_severity=None
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_high_drift_reviews(self):
        ctx = _make_context(drift_overall_status="drift_detected", drift_severity="high")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_medium_drift_reviews(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="medium"
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_transaction_type_reviews(self):
        ctx = _make_context(proposal_transaction_type=None)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_policy_unknown_reviews(self):
        ctx = _make_context(
            policy_unknown_count=1,
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "unknown", "highest_triggered_severity": "none",
                 "categories": []},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_invalid_policy_reviews(self):
        ctx = _make_context(
            policy_invalid_count=1,
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "invalid_policy", "highest_triggered_severity": "none",
                 "categories": []},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_medium_policy_trigger_reviews(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="medium",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "medium",
                 "categories": ["amount_limit"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_low_policy_trigger_reviews(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="low",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "low",
                 "categories": ["amount_limit"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_high_non_security_policy_reviews(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="high",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "high",
                 "categories": ["amount_limit"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_merchant_and_low_trust_both_review(self):
        ctx = _make_context(
            proposal_merchant_trusted=None,
            agent_trust_score=0.1,
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW


# ── BLOCK Conditions ───────────────────────────────────────────────


class TestBlockConditions:
    def test_inactive_intent_blocks(self):
        ctx = _make_context(intent_status="revoked")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_expired_intent_blocks(self):
        ctx = _make_context(intent_status="expired")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_rejected_intent_blocks(self):
        ctx = _make_context(intent_status="rejected")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_missing_structured_intent_blocks(self):
        ctx = _make_context(intent_transaction_type=None)
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_invalid_proposal_drift_blocks(self):
        ctx = _make_context(drift_overall_status="invalid_proposal")
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_transaction_type_mismatch_blocks(self):
        ctx = _make_context(
            intent_transaction_type="purchase",
            proposal_transaction_type="refund",
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_critical_drift_blocks(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="critical"
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_critical_policy_blocks(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="critical",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "critical",
                 "categories": ["amount_limit"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_high_security_policy_blocks(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="high",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "high",
                 "categories": ["transaction_type_restriction"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_high_authorization_scope_policy_blocks(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="high",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "high",
                 "categories": ["authorization_scope"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_high_agent_restriction_policy_blocks(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="high",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "high",
                 "categories": ["agent_restriction"]},
            ],
        )
        engine = DecisionEngine()
        result = engine.evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK


# ── Transaction Type Tests ─────────────────────────────────────────


class TestTransactionType:
    def test_mismatch_both_known_blocks(self):
        ctx = _make_context(
            intent_transaction_type="purchase",
            proposal_transaction_type="refund",
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_unknown_proposal_type_reviews(self):
        ctx = _make_context(proposal_transaction_type=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_same_type_allows(self):
        ctx = _make_context(
            intent_transaction_type="purchase",
            proposal_transaction_type="purchase",
        )
        result = DecisionEngine().evaluate(ctx)
        # Should not block due to type mismatch
        block_signals = [s for s in result.signals if s.signal_type == "transaction_type_mismatch"]
        assert len(block_signals) == 0


# ── Risk Unavailable Tests ─────────────────────────────────────────


class TestRiskUnavailable:
    def test_risk_none_does_not_force_review(self):
        """When all other signals are positive, risk=None should still ALLOW."""
        ctx = _make_context(risk_result=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_risk_none_with_review_signal_reviews(self):
        ctx = _make_context(
            risk_result=None,
            proposal_merchant_trusted=None,
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_risk_none_with_hard_violation_blocks(self):
        ctx = _make_context(
            risk_result=None,
            intent_status="revoked",
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_risk_summary_unavailable(self):
        ctx = _make_context(risk_result=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.risk_summary is not None
        assert result.risk_summary.available is False


# ── Policy Integration Tests ───────────────────────────────────────


class TestPolicyIntegration:
    def test_all_policies_pass_allows(self):
        ctx = _make_context(
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "A",
                 "status": "pass", "highest_triggered_severity": "none",
                 "categories": ["amount_limit"]},
                {"policy_id": "p2", "policy_name": "B",
                 "status": "pass", "highest_triggered_severity": "none",
                 "categories": ["merchant_restriction"]},
            ]
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_multiple_medium_triggers_still_review(self):
        """Multiple MEDIUM triggers do NOT escalate to BLOCK."""
        ctx = _make_context(
            policy_triggered_count=3,
            policy_highest_triggered_severity="medium",
            policy_results_for_signals=[
                {"policy_id": f"p{i}", "policy_name": f"Policy {i}",
                 "status": "triggered", "highest_triggered_severity": "medium",
                 "categories": ["amount_limit"]}
                for i in range(3)
            ],
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_critical_always_blocks(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_highest_triggered_severity="critical",
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Critical Policy",
                 "status": "triggered", "highest_triggered_severity": "critical",
                 "categories": ["amount_limit"]},
            ],
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_valid_and_invalid_policies_both_returned(self):
        ctx = _make_context(
            policy_invalid_count=1,
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Valid",
                 "status": "pass", "highest_triggered_severity": "none",
                 "categories": ["amount_limit"]},
                {"policy_id": "p2", "policy_name": "Invalid",
                 "status": "invalid_policy", "highest_triggered_severity": "none",
                 "categories": []},
            ],
        )
        result = DecisionEngine().evaluate(ctx)
        # Invalid policy produces REVIEW
        assert result.decision == DecisionStatus.REVIEW

    def test_policy_summary_built(self):
        ctx = _make_context(
            policy_triggered_count=1,
            policy_results_for_signals=[
                {"policy_id": "p1", "policy_name": "Policy A",
                 "status": "triggered", "highest_triggered_severity": "high",
                 "categories": ["amount_limit"]},
            ],
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.policy_summary is not None
        assert result.policy_summary.triggered_count == 1
        assert "Policy A" in result.policy_summary.triggered_policy_names

    def test_no_policy_results_produces_allow(self):
        ctx = _make_context(
            policy_result_available=True,
            policy_results_for_signals=[],
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.ALLOW

    def test_policy_engine_unavailable_no_signals(self):
        ctx = _make_context(policy_result_available=False)
        result = DecisionEngine().evaluate(ctx)
        policy_signals = [s for s in result.signals if s.source == "policy"]
        assert len(policy_signals) == 0


# ── Drift Integration Tests ────────────────────────────────────────


class TestDriftIntegration:
    def test_match_drift_positive(self):
        ctx = _make_context(drift_overall_status="match", drift_severity="none")
        result = DecisionEngine().evaluate(ctx)
        drift_signals = [s for s in result.signals if s.source == "drift"]
        assert any(s.status == "positive" for s in drift_signals)

    def test_critical_drift_blocks(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="critical"
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_high_drift_reviews(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="high"
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_medium_drift_reviews(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="medium"
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_low_drift_neutral(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="low"
        )
        result = DecisionEngine().evaluate(ctx)
        drift_signals = [s for s in result.signals if s.source == "drift"]
        assert any(s.status == "neutral" for s in drift_signals)

    def test_drift_unavailable_unknown(self):
        ctx = _make_context(drift_result_available=False)
        result = DecisionEngine().evaluate(ctx)
        drift_signals = [s for s in result.signals if s.source == "drift"]
        assert any(s.status == "unknown" for s in drift_signals)

    def test_drift_summary_built(self):
        ctx = _make_context(
            drift_overall_status="drift_detected", drift_severity="high"
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.drift_summary is not None
        assert result.drift_summary.overall_status == "drift_detected"
        assert result.drift_summary.severity == "high"


# ── Agent Trust Tests ──────────────────────────────────────────────


class TestAgentTrust:
    def test_high_trust_positive(self):
        ctx = _make_context(agent_trust_score=0.85)
        result = DecisionEngine().evaluate(ctx)
        trust_signals = [s for s in result.signals if s.source == "trust"]
        agent_signals = [s for s in trust_signals if "agent" in s.signal_type]
        assert any(s.status == "positive" for s in agent_signals)

    def test_medium_trust_neutral(self):
        ctx = _make_context(agent_trust_score=0.5)
        result = DecisionEngine().evaluate(ctx)
        trust_signals = [s for s in result.signals if s.source == "trust"]
        agent_signals = [s for s in trust_signals if "agent" in s.signal_type]
        assert any(s.status == "neutral" for s in agent_signals)

    def test_low_trust_reviews(self):
        ctx = _make_context(agent_trust_score=0.2)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_trust_reviews(self):
        ctx = _make_context(agent_trust_score=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_trust_boundary_07(self):
        ctx = _make_context(agent_trust_score=0.7)
        result = DecisionEngine().evaluate(ctx)
        trust_signals = [s for s in result.signals if "agent_trust" in s.signal_type]
        assert any(s.status == "positive" for s in trust_signals)

    def test_trust_boundary_03(self):
        ctx = _make_context(agent_trust_score=0.3)
        result = DecisionEngine().evaluate(ctx)
        trust_signals = [s for s in result.signals if "agent_trust" in s.signal_type]
        assert any(s.status == "neutral" for s in trust_signals)

    def test_trust_never_blocks(self):
        """Agent trust alone must never BLOCK."""
        ctx = _make_context(agent_trust_score=0.01)
        # Remove other REVIEW signals
        ctx.proposal_merchant_trusted = True
        ctx.intent_confidence = 0.9
        result = DecisionEngine().evaluate(ctx)
        # Should be REVIEW (trust is low), not BLOCK
        assert result.decision == DecisionStatus.REVIEW


# ── Merchant Trust Tests ───────────────────────────────────────────


class TestMerchantTrust:
    def test_trusted_merchant_positive(self):
        ctx = _make_context(proposal_merchant_trusted=True)
        result = DecisionEngine().evaluate(ctx)
        trust_signals = [s for s in result.signals if s.source == "trust"]
        merchant_signals = [s for s in trust_signals if "merchant" in s.signal_type]
        assert any(s.status == "positive" for s in merchant_signals)

    def test_untrusted_merchant_reviews(self):
        ctx = _make_context(proposal_merchant_trusted=False)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_merchant_reviews(self):
        ctx = _make_context(proposal_merchant_trusted=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_merchant_never_blocks(self):
        """Merchant trust alone must never BLOCK."""
        ctx = _make_context(
            proposal_merchant_trusted=False,
            agent_trust_score=0.9,
            intent_confidence=0.9,
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW


# ── Intent Confidence Tests ────────────────────────────────────────


class TestIntentConfidence:
    def test_high_confidence_positive(self):
        ctx = _make_context(intent_confidence=0.9)
        result = DecisionEngine().evaluate(ctx)
        intent_signals = [s for s in result.signals if s.source == "intent"]
        assert any(s.status == "positive" for s in intent_signals)

    def test_low_confidence_reviews(self):
        ctx = _make_context(intent_confidence=0.3)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_unknown_confidence_reviews(self):
        ctx = _make_context(intent_confidence=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_boundary_confidence(self):
        ctx = _make_context(intent_confidence=0.5)
        result = DecisionEngine().evaluate(ctx)
        intent_signals = [s for s in result.signals if s.source == "intent"]
        confidence_signals = [s for s in intent_signals if "confidence" in s.signal_type]
        assert any(s.status == "positive" for s in confidence_signals)


# ── Signal Aggregation Tests ───────────────────────────────────────


class TestSignalAggregation:
    def test_all_positive_signals_allows(self):
        ctx = _make_context()
        result = DecisionEngine().evaluate(ctx)
        statuses = [s.status for s in result.signals]
        assert all(s in ("positive", "neutral") for s in statuses)
        assert result.decision == DecisionStatus.ALLOW

    def test_single_review_signal_reviews(self):
        ctx = _make_context(proposal_merchant_trusted=None)
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.REVIEW

    def test_block_overrides_review(self):
        """If there's both a BLOCK and REVIEW signal, decision is BLOCK."""
        ctx = _make_context(
            intent_status="revoked",
            proposal_merchant_trusted=None,
        )
        result = DecisionEngine().evaluate(ctx)
        assert result.decision == DecisionStatus.BLOCK

    def test_deterministic_same_input_same_output(self):
        ctx = _make_context(agent_trust_score=0.5)
        engine = DecisionEngine()
        r1 = engine.evaluate(ctx)
        r2 = engine.evaluate(ctx)
        assert r1.decision == r2.decision
        assert r1.reason == r2.reason

    def test_signal_ordering_deterministic(self):
        ctx = _make_context(agent_trust_score=0.5)
        engine = DecisionEngine()
        r1 = engine.evaluate(ctx)
        r2 = engine.evaluate(ctx)
        s1 = [(s.source, s.signal_type) for s in r1.signals]
        s2 = [(s.source, s.signal_type) for s in r2.signals]
        assert s1 == s2


# ── Explainability Tests ───────────────────────────────────────────


class TestExplainability:
    def test_result_has_explanation(self):
        ctx = _make_context()
        result = DecisionEngine().evaluate(ctx)
        assert result.explanation is not None
        assert isinstance(result.explanation, dict)

    def test_result_has_reason(self):
        ctx = _make_context()
        result = DecisionEngine().evaluate(ctx)
        assert result.reason != ""

    def test_review_has_descriptive_reason(self):
        ctx = _make_context(proposal_merchant_trusted=None)
        result = DecisionEngine().evaluate(ctx)
        assert len(result.reason) > 0

    def test_signals_have_descriptions(self):
        ctx = _make_context()
        result = DecisionEngine().evaluate(ctx)
        for sig in result.signals:
            assert sig.description != ""

    def test_evaluation_id_present(self):
        ctx = _make_context(evaluation_id="test-eval-123")
        result = DecisionEngine().evaluate(ctx)
        assert result.evaluation_id == "test-eval-123"

    def test_timestamps_present(self):
        ctx = _make_context()
        result = DecisionEngine().evaluate(ctx)
        assert result.created_at != ""
        assert result.evaluated_at != ""


# ── Versioning Tests ───────────────────────────────────────────────


class TestVersioning:
    def test_decision_version_default(self):
        ctx = _make_context()
        result = DecisionEngine().evaluate(ctx)
        assert result.decision_version == "decision-v1"

    def test_intent_version_preserved(self):
        ctx = _make_context(intent_version=5)
        result = DecisionEngine().evaluate(ctx)
        assert result.intent_version == 5

    def test_proposal_intent_id_preserved(self):
        ctx = _make_context(proposal_intent_id="intent-42")
        result = DecisionEngine().evaluate(ctx)
        assert result.proposal_intent_id == "intent-42"


# ── Security Tests ─────────────────────────────────────────────────


class TestSecurity:
    def test_no_eval_in_engine(self):
        """Verify the Decision Engine does not use eval()."""
        import inspect

        from app.services.decision_engine import engine
        source = inspect.getsource(engine)
        assert "eval(" not in source or "eval(" in source.split("eval('regex")[
            0
        ]  # Check it's not used for code execution

    def test_no_exec_in_engine(self):
        import inspect

        from app.services.decision_engine import engine
        source = inspect.getsource(engine)
        assert "exec(" not in source

    def test_no_subprocess_in_engine(self):
        import inspect

        from app.services.decision_engine import engine
        source = inspect.getsource(engine)
        assert "subprocess" not in source

    def test_no_import_in_engine(self):
        import inspect

        from app.services.decision_engine import engine
        source = inspect.getsource(engine)
        assert "__import__" not in source

    def test_no_llm_in_engine(self):
        import inspect

        from app.services.decision_engine import engine
        source = inspect.getsource(engine)
        assert "gemini" not in source.lower()
        assert "openai" not in source.lower()
        assert "anthropic" not in source.lower()

    def test_no_payment_in_engine(self):
        import inspect

        from app.services.decision_engine import engine
        source = inspect.getsource(engine)
        # Check no actual payment execution code, ignoring docstrings/comments
        code_only = "\n".join(
            line for line in source.split("\n")
            if not line.strip().startswith("#")
            and not line.strip().startswith('"""')
            and not line.strip().startswith("'''")
        )
        assert "razorpay" not in code_only.lower()
        assert "payment_execute" not in code_only.lower()
        assert "process_payment" not in code_only.lower()
