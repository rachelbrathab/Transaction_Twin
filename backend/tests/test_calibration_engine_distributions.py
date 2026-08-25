"""Tests for Calibration Engine distribution analysis."""

from app.services.calibration_engine.distributions import (
    compute_decision_distribution,
    compute_risk_distribution,
    compute_signal_distribution,
)
from app.services.calibration_engine.models import (
    CalibrationContext,
    DecisionRecord,
)


def _make_ctx(decisions: list[dict]) -> CalibrationContext:
    records = []
    for d in decisions:
        records.append(DecisionRecord(
            decision_id=d.get("id", "d1"),
            decision=d.get("decision", "allow"),
            explanation=d.get("explanation", {}),
            signal_count=d.get("signal_count", 0),
            policy_triggered_count=d.get("policy_triggered_count", 0),
            drift_severity=d.get("drift_severity"),
            risk_available=d.get("risk_available", False),
        ))
    return CalibrationContext(user_id="u1", decisions=records)


class TestDecisionDistribution:
    def test_empty(self):
        ctx = _make_ctx([])
        dist = compute_decision_distribution(ctx)
        assert dist.total == 0
        assert dist.allow_rate == 0.0

    def test_one_decision(self):
        ctx = _make_ctx([{"decision": "allow"}])
        dist = compute_decision_distribution(ctx)
        assert dist.total == 1
        assert dist.allow_count == 1
        assert dist.allow_rate == 1.0

    def test_all_allow(self):
        ctx = _make_ctx([{"decision": "allow"} for _ in range(10)])
        dist = compute_decision_distribution(ctx)
        assert dist.allow_rate == 1.0
        assert dist.review_rate == 0.0
        assert dist.block_rate == 0.0

    def test_all_review(self):
        ctx = _make_ctx([{"decision": "review"} for _ in range(10)])
        dist = compute_decision_distribution(ctx)
        assert dist.review_rate == 1.0

    def test_all_block(self):
        ctx = _make_ctx([{"decision": "block"} for _ in range(10)])
        dist = compute_decision_distribution(ctx)
        assert dist.block_rate == 1.0

    def test_mixed(self):
        decisions = (
            [{"decision": "allow"} for _ in range(70)]
            + [{"decision": "review"} for _ in range(20)]
            + [{"decision": "block"} for _ in range(10)]
        )
        ctx = _make_ctx(decisions)
        dist = compute_decision_distribution(ctx)
        assert dist.total == 100
        assert dist.allow_rate == 0.7
        assert dist.review_rate == 0.2
        assert dist.block_rate == 0.1

    def test_sample_count(self):
        ctx = _make_ctx([{"decision": "allow"} for _ in range(5)])
        dist = compute_decision_distribution(ctx)
        assert dist.sample_count == 5


class TestRiskDistribution:
    def test_no_risk_data(self):
        ctx = _make_ctx([
            {"decision": "allow", "risk_available": False},
            {"decision": "review", "risk_available": False},
        ])
        dist = compute_risk_distribution(ctx)
        assert dist.risk_unavailable_count == 2
        assert dist.total_with_risk == 0

    def test_with_risk_low(self):
        ctx = _make_ctx([
            {
                "decision": "allow",
                "risk_available": True,
                "explanation": {
                    "risk": {"available": True},
                    "signals_by_source": {
                        "risk": [{"severity": "low"}],
                    },
                },
            },
        ])
        dist = compute_risk_distribution(ctx)
        assert dist.total_with_risk == 1
        assert dist.low_count == 1

    def test_with_risk_critical(self):
        ctx = _make_ctx([
            {
                "decision": "block",
                "risk_available": True,
                "explanation": {
                    "risk": {"available": True},
                    "signals_by_source": {
                        "risk": [{"severity": "critical"}],
                    },
                },
            },
        ])
        dist = compute_risk_distribution(ctx)
        assert dist.critical_count == 1

    def test_mixed_risk_levels(self):
        ctx = _make_ctx([
            {
                "decision": "allow", "risk_available": True,
                "explanation": {
                    "risk": {"available": True},
                    "signals_by_source": {"risk": [{"severity": "low"}]},
                },
            },
            {
                "decision": "review", "risk_available": True,
                "explanation": {
                    "risk": {"available": True},
                    "signals_by_source": {"risk": [{"severity": "high"}]},
                },
            },
            {
                "decision": "block", "risk_available": False,
                "explanation": {"risk": {"available": False}},
            },
        ])
        dist = compute_risk_distribution(ctx)
        assert dist.low_count == 1
        assert dist.high_count == 1
        assert dist.risk_unavailable_count == 1


class TestSignalDistribution:
    def test_empty(self):
        ctx = _make_ctx([])
        dist = compute_signal_distribution(ctx)
        assert dist.total_decisions == 0
        assert len(dist.signals) == 6  # All 6 signal sources

    def test_valid_signals(self):
        ctx = _make_ctx([
            {
                "decision": "allow",
                "explanation": {
                    "signals_by_source": {
                        "policy": [
                            {"status": "positive", "signal_type": "policy_passed"},
                        ],
                        "drift": [
                            {"status": "positive", "signal_type": "drift_match"},
                        ],
                    },
                },
            },
        ])
        dist = compute_signal_distribution(ctx)
        assert dist.total_decisions == 1
        policy_sig = next(s for s in dist.signals if s.source == "policy")
        assert policy_sig.appeared_count == 1
        assert policy_sig.positive_count == 1

    def test_malformed_jsonb(self):
        ctx = _make_ctx([
            {
                "decision": "allow",
                "explanation": {"signals_by_source": "not_a_dict"},
            },
        ])
        dist = compute_signal_distribution(ctx)
        assert dist.total_decisions == 1

    def test_unknown_status(self):
        ctx = _make_ctx([
            {
                "decision": "review",
                "explanation": {
                    "signals_by_source": {
                        "trust": [
                            {"status": "unknown", "signal_type": "merchant_trust_unknown"},
                        ],
                    },
                },
            },
        ])
        dist = compute_signal_distribution(ctx)
        trust_sig = next(s for s in dist.signals if s.source == "trust")
        assert trust_sig.unknown_count == 1

    def test_violation_signal(self):
        ctx = _make_ctx([
            {
                "decision": "block",
                "explanation": {
                    "signals_by_source": {
                        "validation": [
                            {"status": "violation", "signal_type": "invalid_proposal"},
                        ],
                    },
                },
            },
        ])
        dist = compute_signal_distribution(ctx)
        val_sig = next(s for s in dist.signals if s.source == "validation")
        assert val_sig.violation_count == 1
