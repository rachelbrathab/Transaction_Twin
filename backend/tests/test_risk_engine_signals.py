"""Tests for Risk Engine signal extractors.

All tests are deterministic, offline, and database-independent.
"""

from decimal import Decimal

from app.services.risk_engine.models import (
    RiskContext,
    SourceEngine,
    VelocityContext,
)
from app.services.risk_engine.signals import (
    extract_agent_trust_signal,
    extract_amount_anomaly_signal,
    extract_currency_mismatch_signal,
    extract_data_quality_signal,
    extract_geographic_anomaly_signal,
    extract_intent_drift_signal,
    extract_merchant_trust_signal,
    extract_policy_interaction_signal,
    extract_velocity_signal,
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


# ── Intent Drift ───────────────────────────────────────────────────


class TestIntentDriftSignal:
    def test_drift_unavailable_returns_none(self):
        ctx = _make_ctx(drift_available=False)
        assert extract_intent_drift_signal(ctx) is None

    def test_match_gives_zero_contribution(self):
        ctx = _make_ctx(drift_available=True, drift_overall_status="match", drift_severity="none")
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert sig.source_engine == SourceEngine.TRANSACTION_TWIN

    def test_partial_match_gives_low_contribution(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="partial_match",
            drift_severity="low",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.05

    def test_drift_low(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="low",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.10

    def test_drift_medium(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="medium",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.25

    def test_drift_high(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="high",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.45

    def test_drift_critical(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="critical",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.65

    def test_insufficient_data_reduces_confidence(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="insufficient_data",
            drift_severity=None,
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert sig.confidence < 1.0

    def test_invalid_proposal_returns_none(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="invalid_proposal",
            drift_severity="critical",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is None  # Handled by Decision Engine hard blocks

    def test_amount_deviation_adds_increment(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="high",
            drift_amount_deviation_percent=Decimal("45"),
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.45  # Base + increment

    def test_source_fields_correct(self):
        ctx = _make_ctx(drift_available=True, drift_overall_status="match", drift_severity="none")
        sig = extract_intent_drift_signal(ctx)
        assert "drift_overall_status" in sig.source_fields


# ── Amount Anomaly ─────────────────────────────────────────────────


class TestAmountAnomalySignal:
    def test_missing_amount_gives_zero_risk(self):
        ctx = _make_ctx(proposal_amount=None)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert sig.confidence < 1.0

    def test_no_intent_bounds_gives_zero_risk(self):
        ctx = _make_ctx(
            proposal_amount=Decimal("5000"),
            intent_amount_max=None,
            intent_amount_min=None,
        )
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_within_bounds(self):
        ctx = _make_ctx(proposal_amount=Decimal("3000"), intent_amount_max=5000.0)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_exceeds_max(self):
        ctx = _make_ctx(proposal_amount=Decimal("8000"), intent_amount_max=5000.0)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_below_min(self):
        ctx = _make_ctx(proposal_amount=Decimal("100"), intent_amount_min=500.0)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_at_max_is_zero(self):
        ctx = _make_ctx(proposal_amount=Decimal("5000"), intent_amount_max=5000.0)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_large_deviation_caps_at_040(self):
        ctx = _make_ctx(proposal_amount=Decimal("50000"), intent_amount_max=5000.0)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution <= 0.40

    def test_source_engine_is_risk_engine(self):
        ctx = _make_ctx(proposal_amount=Decimal("3000"), intent_amount_max=5000.0)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.source_engine == SourceEngine.RISK_ENGINE


# ── Agent Trust ────────────────────────────────────────────────────


class TestAgentTrustSignal:
    def test_high_trust(self):
        ctx = _make_ctx(agent_trust_score=0.85)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_medium_trust(self):
        ctx = _make_ctx(agent_trust_score=0.65)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.05

    def test_moderate_concern(self):
        ctx = _make_ctx(agent_trust_score=0.45)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.15

    def test_elevated_risk(self):
        ctx = _make_ctx(agent_trust_score=0.25)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.30

    def test_high_risk(self):
        ctx = _make_ctx(agent_trust_score=0.10)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.45

    def test_unknown_trust_gives_zero_risk(self):
        ctx = _make_ctx(agent_trust_score=None)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert sig.confidence < 1.0

    def test_boundary_08(self):
        ctx = _make_ctx(agent_trust_score=0.8)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_boundary_06(self):
        ctx = _make_ctx(agent_trust_score=0.6)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.05

    def test_source_is_database(self):
        ctx = _make_ctx(agent_trust_score=0.5)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.source_engine == SourceEngine.DATABASE


# ── Merchant Trust ─────────────────────────────────────────────────


class TestMerchantTrustSignal:
    def test_trusted_merchant(self):
        ctx = _make_ctx(proposal_merchant_trusted=True, proposal_merchant_name="Amazon")
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_untrusted_merchant(self):
        ctx = _make_ctx(proposal_merchant_trusted=False, proposal_merchant_name="SketchyShop")
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.25

    def test_unknown_merchant_gives_mild_penalty(self):
        ctx = _make_ctx(proposal_merchant_trusted=None, merchant_trust_score=None)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.10
        assert sig.confidence < 1.0

    def test_trust_score_high(self):
        ctx = _make_ctx(proposal_merchant_trusted=None, merchant_trust_score=0.85)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_trust_score_low(self):
        ctx = _make_ctx(proposal_merchant_trusted=None, merchant_trust_score=0.2)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.30

    def test_explicitly_untrusted_is_negative_evidence(self):
        ctx = _make_ctx(proposal_merchant_trusted=False)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0  # Negative evidence

    def test_unknown_is_not_negative(self):
        ctx = _make_ctx(proposal_merchant_trusted=None, merchant_trust_score=None)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        # Unknown has mild penalty but is not strongly negative
        assert sig.risk_contribution <= 0.15


# ── Policy Interaction ─────────────────────────────────────────────


class TestPolicyInteractionSignal:
    def test_no_policies_returns_none(self):
        ctx = _make_ctx(policy_available=False)
        assert extract_policy_interaction_signal(ctx) is None

    def test_all_passed(self):
        ctx = _make_ctx(policy_available=True, policy_triggered_count=0)
        sig = extract_policy_interaction_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_one_medium_trigger(self):
        ctx = _make_ctx(
            policy_available=True,
            policy_triggered_count=1,
            policy_highest_severity="medium",
        )
        sig = extract_policy_interaction_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_three_triggers(self):
        ctx = _make_ctx(
            policy_available=True,
            policy_triggered_count=3,
            policy_highest_severity="medium",
        )
        sig = extract_policy_interaction_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.30

    def test_critical_trigger(self):
        ctx = _make_ctx(
            policy_available=True,
            policy_triggered_count=1,
            policy_highest_severity="critical",
        )
        sig = extract_policy_interaction_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.50

    def test_unknown_policies_reduce_confidence(self):
        ctx = _make_ctx(
            policy_available=True,
            policy_triggered_count=0,
            policy_unknown_count=2,
        )
        sig = extract_policy_interaction_signal(ctx)
        assert sig is not None
        assert sig.confidence < 1.0


# ── Velocity ───────────────────────────────────────────────────────


class TestVelocitySignal:
    def test_no_history(self):
        ctx = _make_ctx(velocity=None)
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert sig.confidence < 1.0

    def test_history_unavailable(self):
        ctx = _make_ctx(velocity=VelocityContext(history_available=False))
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_normal_velocity(self):
        ctx = _make_ctx(velocity=VelocityContext(
            transactions_last_hour=1,
            history_available=True,
        ))
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_high_frequency(self):
        ctx = _make_ctx(velocity=VelocityContext(
            transactions_last_hour=6,
            history_available=True,
        ))
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_moderate_frequency(self):
        ctx = _make_ctx(velocity=VelocityContext(
            transactions_last_hour=3,
            history_available=True,
        ))
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_repeat_merchant(self):
        ctx = _make_ctx(velocity=VelocityContext(
            same_merchant_count_last_hour=4,
            history_available=True,
        ))
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_amount_velocity_spike(self):
        ctx = _make_ctx(
            intent_amount_max=5000.0,
            velocity=VelocityContext(
                total_amount_last_hour=Decimal("20000"),
                history_available=True,
            ),
        )
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_high_diversity(self):
        ctx = _make_ctx(velocity=VelocityContext(
            unique_merchants_last_day=12,
            history_available=True,
        ))
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0


# ── Data Quality ───────────────────────────────────────────────────


class TestDataQualitySignal:
    def test_all_data_present_returns_none(self):
        ctx = _make_ctx(
            drift_available=True,
            agent_trust_score=0.8,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.9,
            policy_available=True,
            proposal_amount=Decimal("5000"),
        )
        assert extract_data_quality_signal(ctx) is None

    def test_missing_drift(self):
        ctx = _make_ctx(
            drift_available=False,
            agent_trust_score=0.8,
            proposal_merchant_trusted=True,
            velocity=VelocityContext(history_available=True),
            intent_confidence=0.9,
            policy_available=True,
            proposal_amount=Decimal("5000"),
        )
        sig = extract_data_quality_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0  # Never contributes to risk
        assert "drift_result" in sig.evidence["missing_fields"]

    def test_multiple_missing(self):
        ctx = _make_ctx(
            drift_available=False,
            agent_trust_score=None,
            proposal_merchant_trusted=None,
            merchant_trust_score=None,
        )
        sig = extract_data_quality_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert len(sig.evidence["missing_fields"]) >= 3


# ── Currency Mismatch ──────────────────────────────────────────────


class TestCurrencyMismatchSignal:
    def test_both_unknown(self):
        ctx = _make_ctx(intent_currency=None, proposal_currency=None)
        sig = extract_currency_mismatch_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert sig.confidence < 1.0

    def test_same_currency(self):
        ctx = _make_ctx(intent_currency="INR", proposal_currency="INR")
        sig = extract_currency_mismatch_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_mismatch(self):
        ctx = _make_ctx(intent_currency="INR", proposal_currency="USD")
        sig = extract_currency_mismatch_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.15

    def test_case_insensitive_match(self):
        ctx = _make_ctx(intent_currency="inr", proposal_currency="INR")
        sig = extract_currency_mismatch_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_one_unknown(self):
        ctx = _make_ctx(intent_currency="INR", proposal_currency=None)
        sig = extract_currency_mismatch_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0


# ── Geographic Anomaly ─────────────────────────────────────────────


class TestGeographicAnomalySignal:
    def test_both_unknown(self):
        ctx = _make_ctx(intent_country=None, proposal_country=None)
        sig = extract_geographic_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_same_country(self):
        ctx = _make_ctx(intent_country="IN", proposal_country="IN")
        sig = extract_geographic_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_mismatch(self):
        ctx = _make_ctx(intent_country="IN", proposal_country="US")
        sig = extract_geographic_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.10

    def test_one_unknown(self):
        ctx = _make_ctx(intent_country="IN", proposal_country=None)
        sig = extract_geographic_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0


# ── UNKNOWN vs NEGATIVE ───────────────────────────────────────────


class TestUnknownVsNegative:
    def test_agent_none_is_unknown_not_negative(self):
        ctx = _make_ctx(agent_trust_score=None)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
        assert "not available" in sig.what.lower()

    def test_agent_low_is_negative(self):
        ctx = _make_ctx(agent_trust_score=0.15)
        sig = extract_agent_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution > 0.0

    def test_merchant_none_is_unknown(self):
        ctx = _make_ctx(proposal_merchant_trusted=None, merchant_trust_score=None)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution <= 0.15  # Mild penalty, not strongly negative

    def test_merchant_false_is_negative(self):
        ctx = _make_ctx(proposal_merchant_trusted=False)
        sig = extract_merchant_trust_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.25  # Strong negative

    def test_drift_unavailable_is_unknown(self):
        ctx = _make_ctx(drift_available=False)
        sig = extract_intent_drift_signal(ctx)
        assert sig is None  # Returns None when unavailable

    def test_critical_drift_is_negative(self):
        ctx = _make_ctx(
            drift_available=True,
            drift_overall_status="drift_detected",
            drift_severity="critical",
        )
        sig = extract_intent_drift_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.65

    def test_no_velocity_is_unknown(self):
        ctx = _make_ctx(velocity=None)
        sig = extract_velocity_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0

    def test_missing_amount_is_unknown(self):
        ctx = _make_ctx(proposal_amount=None)
        sig = extract_amount_anomaly_signal(ctx)
        assert sig is not None
        assert sig.risk_contribution == 0.0
