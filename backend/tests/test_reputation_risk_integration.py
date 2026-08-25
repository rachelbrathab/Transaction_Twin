"""Tests for Risk Engine integration with Reputation Engine.

Tests AGENT_BEHAVIOR signal, double-count prevention with AGENT_TRUST,
and backward compatibility when reputation is unavailable.
"""


from app.services.risk_engine.constants import SIGNAL_WEIGHTS
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import (
    RiskContext,
    RiskLevel,
    RiskSignalType,
)


def _make_risk_ctx(**kwargs) -> RiskContext:
    defaults = {
        "user_id": "u1",
        "agent_id": "a1",
        "intent_id": "i1",
        "intent_version": 1,
    }
    defaults.update(kwargs)
    return RiskContext(**defaults)


class TestAgentBehaviorSignal:
    def test_behavior_not_available_no_signal(self):
        ctx = _make_risk_ctx()
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        signal_types = [s.signal_type for s in result.signals]
        assert RiskSignalType.AGENT_BEHAVIOR not in signal_types

    def test_behavior_available_produces_signal(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.80,
            agent_reputation_level="high",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        signal_types = [s.signal_type for s in result.signals]
        assert RiskSignalType.AGENT_BEHAVIOR in signal_types

    def test_high_reputation_zero_contribution(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.80,
            agent_reputation_level="high",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        behavior_signal = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_BEHAVIOR
        )
        assert behavior_signal.risk_contribution == 0.0

    def test_medium_reputation_small_contribution(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.50,
            agent_reputation_level="medium",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        behavior_signal = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_BEHAVIOR
        )
        assert behavior_signal.risk_contribution == 0.05

    def test_low_reputation_higher_contribution(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.25,
            agent_reputation_level="low",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        behavior_signal = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_BEHAVIOR
        )
        assert behavior_signal.risk_contribution == 0.15

    def test_very_low_reputation_highest_contribution(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.10,
            agent_reputation_level="low",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        behavior_signal = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_BEHAVIOR
        )
        assert behavior_signal.risk_contribution == 0.30


class TestDoubleCountPrevention:
    def test_agent_trust_excluded_when_behavior_present(self):
        """When AGENT_BEHAVIOR is available, AGENT_TRUST is NOT emitted."""
        ctx = _make_risk_ctx(
            agent_trust_score=0.15,  # Very low trust
            agent_reputation_available=True,
            agent_reputation_score=0.80,  # But high reputation
            agent_reputation_level="high",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)

        trust_signal = next(
            (s for s in result.signals
             if s.signal_type == RiskSignalType.AGENT_TRUST),
            None,
        )
        behavior_signal = next(
            (s for s in result.signals
             if s.signal_type == RiskSignalType.AGENT_BEHAVIOR),
            None,
        )

        # AGENT_TRUST must NOT be present (mutual exclusion)
        assert trust_signal is None
        # AGENT_BEHAVIOR replaces it
        assert behavior_signal is not None
        assert behavior_signal.risk_contribution == 0.0  # High reputation → 0 risk

    def test_agent_trust_active_when_behavior_absent(self):
        """When AGENT_BEHAVIOR is absent, AGENT_TRUST works normally."""
        ctx = _make_risk_ctx(
            agent_trust_score=0.15,  # Very low trust
            agent_reputation_available=False,
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)

        trust_signal = next(
            (s for s in result.signals
             if s.signal_type == RiskSignalType.AGENT_TRUST),
            None,
        )
        assert trust_signal is not None
        # Trust signal should have non-zero contribution
        assert trust_signal.risk_contribution > 0.0


class TestBackwardCompatibility:
    def test_no_reputation_backward_compatible(self):
        """Without reputation, behavior works exactly as before."""
        ctx = _make_risk_ctx(
            agent_trust_score=0.50,
            agent_reputation_available=False,
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        # Should have AGENT_TRUST but not AGENT_BEHAVIOR
        signal_types = [s.signal_type for s in result.signals]
        assert RiskSignalType.AGENT_TRUST in signal_types
        assert RiskSignalType.AGENT_BEHAVIOR not in signal_types

    def test_existing_risk_weights_still_sum_to_one(self):
        total = sum(SIGNAL_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_risk_level_mapping_unchanged(self):
        ctx = _make_risk_ctx()
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        # Empty context should produce low risk
        assert result.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)


class TestReputationSourceEngine:
    def test_behavior_signal_has_reputation_engine_source(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.60,
            agent_reputation_level="medium",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        behavior_signal = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_BEHAVIOR
        )
        assert behavior_signal.source_engine.value == "reputation_engine"

    def test_behavior_signal_has_correct_source_fields(self):
        ctx = _make_risk_ctx(
            agent_reputation_available=True,
            agent_reputation_score=0.60,
            agent_reputation_level="medium",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)
        behavior_signal = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_BEHAVIOR
        )
        assert "agent_reputation_score" in behavior_signal.source_fields
        assert "agent_reputation_level" in behavior_signal.source_fields


class TestWeightInvariant:
    """Verify Sprint 7 weights are preserved exactly."""

    def test_original_sprint7_weights_preserved(self):
        """Sprint 8 must NOT change Sprint 7 weights."""
        assert SIGNAL_WEIGHTS[RiskSignalType.INTENT_DRIFT] == 0.25
        assert SIGNAL_WEIGHTS[RiskSignalType.AMOUNT_ANOMALY] == 0.15
        assert SIGNAL_WEIGHTS[RiskSignalType.AGENT_TRUST] == 0.15
        assert SIGNAL_WEIGHTS[RiskSignalType.MERCHANT_TRUST] == 0.10
        assert SIGNAL_WEIGHTS[RiskSignalType.POLICY_INTERACTION] == 0.20
        assert SIGNAL_WEIGHTS[RiskSignalType.VELOCITY] == 0.05
        assert SIGNAL_WEIGHTS[RiskSignalType.DATA_QUALITY] == 0.00
        assert SIGNAL_WEIGHTS[RiskSignalType.CURRENCY_MISMATCH] == 0.05
        assert SIGNAL_WEIGHTS[RiskSignalType.GEOGRAPHIC_ANOMALY] == 0.05

    def test_nonzero_weights_sum_to_one(self):
        nonzero = {k: v for k, v in SIGNAL_WEIGHTS.items() if v > 0}
        assert abs(sum(nonzero.values()) - 1.0) < 1e-9

    def test_agent_behavior_not_in_weights(self):
        """AGENT_BEHAVIOR must NOT be an additional weight."""
        assert RiskSignalType.AGENT_BEHAVIOR not in SIGNAL_WEIGHTS

    def test_agent_behavior_uses_agent_trust_weight(self):
        """AGENT_BEHAVIOR replaces AGENT_TRUST — same 0.15 weight."""
        assert SIGNAL_WEIGHTS[RiskSignalType.AGENT_TRUST] == 0.15


class TestSprint7BackwardCompatibility:
    """Sprint 7 contexts without reputation fields produce identical results."""

    def test_sprint7_context_unchanged(self):
        """A context with no reputation fields matches Sprint 7 behavior."""
        ctx = _make_risk_ctx(
            drift_available=True,
            drift_overall_status="match",
            policy_available=True,
            policy_triggered_count=0,
            agent_trust_score=0.80,
            proposal_merchant_trusted=True,
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)

        # Must be low risk, no trust signal issues
        assert result.risk_level == RiskLevel.LOW
        # AGENT_TRUST should be present (legacy path)
        trust = next(
            s for s in result.signals
            if s.signal_type == RiskSignalType.AGENT_TRUST
        )
        assert trust.risk_contribution == 0.0
        # AGENT_BEHAVIOR must NOT be present
        behavior = next(
            (s for s in result.signals
             if s.signal_type == RiskSignalType.AGENT_BEHAVIOR),
            None,
        )
        assert behavior is None

    def test_reputation_replaces_trust_completely(self):
        """When reputation available, AGENT_BEHAVIOR replaces AGENT_TRUST."""
        ctx = _make_risk_ctx(
            agent_trust_score=0.10,  # Very low legacy trust
            agent_reputation_available=True,
            agent_reputation_score=0.85,  # High reputation
            agent_reputation_level="high",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)

        trust = next(
            (s for s in result.signals
             if s.signal_type == RiskSignalType.AGENT_TRUST),
            None,
        )
        behavior = next(
            (s for s in result.signals
             if s.signal_type == RiskSignalType.AGENT_BEHAVIOR),
            None,
        )
        # Trust absent, behavior present
        assert trust is None
        assert behavior is not None
        # The very low trust score does NOT contribute (reputation overrides)
        assert behavior.risk_contribution == 0.0  # High reputation = 0 risk

    def test_both_trust_and_behavior_never_coexist(self):
        """AGENT_TRUST and AGENT_BEHAVIOR are mutually exclusive."""
        ctx = _make_risk_ctx(
            agent_trust_score=0.30,
            agent_reputation_available=True,
            agent_reputation_score=0.30,
            agent_reputation_level="low",
        )
        engine = RiskEngine()
        result = engine.evaluate(ctx)

        trust_types = [
            s.signal_type for s in result.signals
            if s.signal_type in (RiskSignalType.AGENT_TRUST, RiskSignalType.AGENT_BEHAVIOR)
        ]
        assert len(trust_types) == 1
        assert trust_types[0] == RiskSignalType.AGENT_BEHAVIOR
