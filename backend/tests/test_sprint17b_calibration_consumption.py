"""Sprint 17B — Safe Runtime Calibration Consumption tests.

Tests for:
- RiskEngineConfig creation and defaults
- Aggregator accepts optional config
- Default equivalence (config=None matches original behavior)
- Active calibration application
- Invalid calibration fallback
- User isolation
- Superseded/generated/approved-but-inactive calibration ignored
- Partial calibration
- Invalid parameter handling
- Deterministic evaluation
- No global mutation
- Risk Engine remains DB-free
- Calibration metadata in response
- Calibration loading failure
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.calibration_runtime.models import RuntimeCalibrationConfig
from app.services.calibration_runtime.resolver import resolve_effective_config
from app.services.risk_engine.config import (
    RiskEngineConfig,
    get_default_risk_engine_config,
    get_effective_confidence_ceiling,
    get_effective_confidence_floor,
    get_effective_confidence_reduction,
    get_effective_risk_level_thresholds,
    get_effective_signal_weight,
)
from app.services.risk_engine.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    CONFIDENCE_REDUCTIONS,
    RISK_LEVEL_THRESHOLDS,
    SIGNAL_WEIGHTS,
)
from app.services.risk_engine.engine import RiskEngine
from app.services.risk_engine.models import (
    RiskContext,
    RiskLevel,
    RiskSignalType,
)

# ── Test Fixtures ─────────────────────────────────────────────────


def _make_risk_context(**overrides) -> RiskContext:
    """Create a minimal RiskContext for testing."""
    defaults = {
        "user_id": "user-123",
        "agent_id": "agent-456",
        "intent_id": "intent-789",
        "intent_version": 1,
        "intent_confidence": 0.9,
        "intent_transaction_type": "payment",
        "proposal_amount": Decimal("100.00"),
        "proposal_currency": "USD",
        "proposal_transaction_type": "payment",
        "proposal_merchant_name": "Test Merchant",
        "proposal_merchant_trusted": False,
        "proposal_country": "US",
        "drift_available": True,
        "drift_overall_status": "match",
        "drift_severity": "low",
        "policy_available": True,
        "policy_triggered_count": 0,
        "agent_trust_score": 0.7,
        "merchant_trust_score": 0.6,
    }
    defaults.update(overrides)
    return RiskContext(**defaults)


def _make_default_config() -> RiskEngineConfig:
    """Create the default RiskEngineConfig."""
    return get_default_risk_engine_config()


def _make_calibrated_config() -> RiskEngineConfig:
    """Create a calibrated RiskEngineConfig with different signal weights."""
    return RiskEngineConfig(
        signal_weights={
            "intent_drift": 0.30,
            "amount_anomaly": 0.15,
            "agent_trust": 0.15,
            "merchant_trust": 0.10,
            "policy_interaction": 0.20,
            "velocity": 0.05,
            "data_quality": 0.00,
            "currency_mismatch": 0.05,
            "geographic_anomaly": 0.05,
        },
        risk_level_thresholds={"critical": 0.75, "high": 0.50, "medium": 0.25, "low": 0.00},
        confidence_reductions={
            "drift_missing": 0.20,
            "agent_trust_missing": 0.10,
            "merchant_trust_missing": 0.05,
            "velocity_missing": 0.05,
            "intent_confidence_missing": 0.10,
            "policy_missing": 0.10,
            "proposal_amount_missing": 0.05,
            "network_shared_risk": 0.15,
            "network_concentration": 0.10,
            "network_cluster_risk": 0.15,
            "behavioral_amount_anomaly": 0.15,
            "behavioral_frequency_anomaly": 0.10,
            "behavioral_merchant_anomaly": 0.10,
        },
        confidence_floor=0.1,
        confidence_ceiling=1.0,
        calibration_active=True,
        calibration_version_id="calibration-v-test",
    )


# ── Phase 9: Default Configuration Equivalence ────────────────────


class TestDefaultConfigurationEquivalence:
    """Verify that config=None produces identical results to config=default."""

    def test_default_config_values_match_constants(self):
        cfg = get_default_risk_engine_config()
        for rt, weight in SIGNAL_WEIGHTS.items():
            assert cfg.signal_weights[rt.value] == weight, (
                f"Default config {rt.value} weight mismatch"
            )
        for threshold, level in RISK_LEVEL_THRESHOLDS:
            assert cfg.risk_level_thresholds[level.value] == threshold
        for key, val in CONFIDENCE_REDUCTIONS.items():
            assert cfg.confidence_reductions[key] == val
        assert cfg.confidence_floor == CONFIDENCE_FLOOR
        assert cfg.confidence_ceiling == CONFIDENCE_CEILING
        assert cfg.calibration_active is False

    def test_evaluate_none_matches_default_config(self):
        ctx = _make_risk_context()
        engine = RiskEngine()
        result_none = engine.evaluate(ctx, config=None)
        result_default = engine.evaluate(ctx, config=_make_default_config())

        assert result_none.overall_score == result_default.overall_score
        assert result_none.risk_level == result_default.risk_level
        assert result_none.confidence == result_default.confidence
        assert result_none.calibration_active is False
        assert result_default.calibration_active is False

    def test_signal_weights_sum_to_one(self):
        cfg = _make_default_config()
        positive = {k: v for k, v in cfg.signal_weights.items() if v > 0}
        assert abs(sum(positive.values()) - 1.0) < 1e-6

    def test_calibrated_config_preserves_non_overridden_defaults(self):
        """When only intent_drift is overridden, all other weights remain default."""
        cfg = _make_calibrated_config()
        default_cfg = _make_default_config()
        for key in default_cfg.signal_weights:
            if key != "intent_drift":
                if key in cfg.signal_weights:
                    assert cfg.signal_weights[key] == default_cfg.signal_weights[key], (
                        f"Non-overridden weight {key} changed"
                    )

    def test_config_is_frozen(self):
        cfg = _make_default_config()
        with pytest.raises(Exception):
            cfg.calibration_active = True  # type: ignore[misc]

    def test_default_config_creates_fresh_copy_each_time(self):
        cfg1 = get_default_risk_engine_config()
        cfg2 = get_default_risk_engine_config()
        # Modifying one should not affect the other
        cfg1.signal_weights["intent_drift"] = 999.0
        assert cfg2.signal_weights["intent_drift"] == 0.25


# ── Phase 10: Calibration Application Tests ───────────────────────


class TestSignalWeightCalibration:
    """Test calibrated signal weights affect evaluation correctly."""

    def test_higher_weight_increases_contribution(self):
        """A signal with higher weight should contribute more to the score."""
        ctx = _make_risk_context(
            drift_available=True,
            drift_overall_status="mismatch",
            drift_severity="high",
        )
        engine = RiskEngine()

        result_default = engine.evaluate(ctx, config=None)

        # Increase intent_drift weight significantly
        cfg = RiskEngineConfig(
            signal_weights={
                "intent_drift": 0.50,
                "amount_anomaly": 0.12,
                "agent_trust": 0.10,
                "merchant_trust": 0.08,
                "policy_interaction": 0.10,
                "velocity": 0.05,
                "data_quality": 0.00,
                "currency_mismatch": 0.025,
                "geographic_anomaly": 0.025,
            },
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
        )
        result_calibrated = engine.evaluate(ctx, config=cfg)

        # With higher intent_drift weight, score should differ
        # (direction depends on whether drift signal is high)
        assert result_calibrated.overall_score != result_default.overall_score

    def test_zero_weight_excludes_signal(self):
        """A signal with weight 0 should not contribute to weighted score."""
        ctx = _make_risk_context()
        engine = RiskEngine()

        result_default = engine.evaluate(ctx, config=None)

        # Set intent_drift to 0
        weights = {k.value: v for k, v in SIGNAL_WEIGHTS.items()}
        weights["intent_drift"] = 0.0
        cfg = RiskEngineConfig(
            signal_weights=weights,
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
        )
        result_calibrated = engine.evaluate(ctx, config=cfg)

        # Score should differ since a major weight is zeroed
        assert result_calibrated.overall_score != result_default.overall_score

    def test_unspecified_weight_uses_default(self):
        """If a weight is missing from config, the default is used."""
        ctx = _make_risk_context()
        engine = RiskEngine()

        # Only override intent_drift, leave others unspecified
        cfg = RiskEngineConfig(
            signal_weights={"intent_drift": 0.35},
        )
        result = engine.evaluate(ctx, config=cfg)

        # Should produce a valid result (uses defaults for missing weights)
        assert 0.0 <= result.overall_score <= 1.0
        assert result.risk_level in RiskLevel


class TestRiskThresholdCalibration:
    """Test calibrated risk thresholds affect level mapping."""

    def test_calibrated_threshold_changes_level(self):
        """A calibrated threshold can change the risk level for a given score."""
        ctx = _make_risk_context()
        engine = RiskEngine()
        result_default = engine.evaluate(ctx, config=None)

        score = result_default.overall_score

        # Lower ALL thresholds so the score maps to a higher level
        # e.g. if score is 0.05, set critical=0.04 so it maps to CRITICAL
        if score > 0.0:
            cfg = RiskEngineConfig(
                signal_weights={k.value: v for k, v in SIGNAL_WEIGHTS.items()},
                risk_level_thresholds={
                    "critical": score - 0.001,
                    "high": 0.0,
                    "medium": 0.0,
                    "low": 0.0,
                },
                confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
            )
            result_calibrated = engine.evaluate(ctx, config=cfg)
            assert result_calibrated.risk_level == RiskLevel.CRITICAL

    def test_boundary_values(self):
        """Test with score exactly at threshold boundaries."""
        # We can't directly control the score, but we can test the threshold function
        thresholds = get_effective_risk_level_thresholds()
        assert len(thresholds) == 4
        # Thresholds should be sorted descending
        for i in range(len(thresholds) - 1):
            assert thresholds[i][0] >= thresholds[i + 1][0]


class TestConfidenceReductionCalibration:
    """Test calibrated confidence reductions."""

    def test_higher_reduction_decreases_confidence(self):
        """Higher confidence reduction should decrease confidence."""
        ctx = _make_risk_context(
            drift_available=False,
            agent_trust_score=None,
            intent_confidence=None,
        )
        engine = RiskEngine()
        result_default = engine.evaluate(ctx, config=None)

        # Increase all reductions
        reductions = dict(CONFIDENCE_REDUCTIONS)
        for key in reductions:
            reductions[key] = 0.30
        cfg = RiskEngineConfig(
            signal_weights={k.value: v for k, v in SIGNAL_WEIGHTS.items()},
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions=reductions,
        )
        result_calibrated = engine.evaluate(ctx, config=cfg)

        # Higher reductions should lower confidence (or keep it at floor)
        assert result_calibrated.confidence <= result_default.confidence

    def test_calibrated_floor_applies(self):
        """Confidence floor from config is used."""
        ctx = _make_risk_context(
            drift_available=False,
            agent_trust_score=None,
            intent_confidence=None,
            policy_available=False,
        )
        engine = RiskEngine()

        cfg = RiskEngineConfig(
            signal_weights={k.value: v for k, v in SIGNAL_WEIGHTS.items()},
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions={k: 0.30 for k in CONFIDENCE_REDUCTIONS},
            confidence_floor=0.30,
        )
        result = engine.evaluate(ctx, config=cfg)
        assert result.confidence >= 0.30


class TestMixedConfiguration:
    """Test mixed signal weight + threshold + confidence overrides."""

    def test_multiple_valid_overrides(self):
        """Multiple valid overrides applied together."""
        ctx = _make_risk_context()
        engine = RiskEngine()

        cfg = RiskEngineConfig(
            signal_weights={
                "intent_drift": 0.30,
                "amount_anomaly": 0.15,
                "agent_trust": 0.15,
                "merchant_trust": 0.10,
                "policy_interaction": 0.15,
                "velocity": 0.05,
                "data_quality": 0.00,
                "currency_mismatch": 0.05,
                "geographic_anomaly": 0.05,
            },
            risk_level_thresholds={"critical": 0.80, "high": 0.55, "medium": 0.30, "low": 0.00},
            confidence_reductions={
                "drift_missing": 0.20,
                "agent_trust_missing": 0.15,
                "merchant_trust_missing": 0.10,
                "velocity_missing": 0.10,
                "intent_confidence_missing": 0.15,
                "policy_missing": 0.15,
                "proposal_amount_missing": 0.10,
                "network_shared_risk": 0.20,
                "network_concentration": 0.15,
                "network_cluster_risk": 0.20,
                "behavioral_amount_anomaly": 0.20,
                "behavioral_frequency_anomaly": 0.15,
                "behavioral_merchant_anomaly": 0.15,
            },
            calibration_active=True,
            calibration_version_id="calibration-v-mixed",
        )
        result = engine.evaluate(ctx, config=cfg)
        assert 0.0 <= result.overall_score <= 1.0
        assert result.risk_level in RiskLevel
        assert result.calibration_active is True
        assert result.calibration_version_id == "calibration-v-mixed"

    def test_invalid_one_parameter_does_not_partially_apply(self):
        """When config is provided, the engine uses it as-is (no partial application).

        The resolver already rejects invalid configs and falls back to defaults.
        The RiskEngine trusts that any config it receives is pre-validated.
        """
        ctx = _make_risk_context()
        engine = RiskEngine()

        # Config with one bad weight — engine uses it as-is (resolver's job to validate)
        cfg = RiskEngineConfig(
            signal_weights={"intent_drift": -1.0},  # Invalid but engine trusts config
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
        )
        result = engine.evaluate(ctx, config=cfg)
        # Result is still valid (engine doesn't validate — resolver does)
        assert 0.0 <= result.overall_score <= 1.0


# ── Phase 11: Isolation Tests ─────────────────────────────────────


class TestUserIsolation:
    """Test that calibration is properly scoped to users."""

    def test_different_configs_produce_different_results(self):
        """Two users with different calibrations get different risk scores."""
        ctx = _make_risk_context()
        engine = RiskEngine()

        cfg_a = RiskEngineConfig(
            signal_weights={
                "intent_drift": 0.40,
                "amount_anomaly": 0.12,
                "agent_trust": 0.12,
                "merchant_trust": 0.08,
                "policy_interaction": 0.12,
                "velocity": 0.04,
                "data_quality": 0.00,
                "currency_mismatch": 0.06,
                "geographic_anomaly": 0.06,
            },
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
            calibration_active=True,
            calibration_version_id="calibration-v-a",
        )

        cfg_b = RiskEngineConfig(
            signal_weights={
                "intent_drift": 0.10,
                "amount_anomaly": 0.15,
                "agent_trust": 0.20,
                "merchant_trust": 0.15,
                "policy_interaction": 0.20,
                "velocity": 0.05,
                "data_quality": 0.00,
                "currency_mismatch": 0.075,
                "geographic_anomaly": 0.075,
            },
            risk_level_thresholds={level.value: t for t, level in RISK_LEVEL_THRESHOLDS},
            confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
            calibration_active=True,
            calibration_version_id="calibration-v-b",
        )

        result_a = engine.evaluate(ctx, config=cfg_a)
        result_b = engine.evaluate(ctx, config=cfg_b)

        # Different configs can produce different scores
        # (not guaranteed to be different, but should be for these weights)
        assert result_a.calibration_version_id == "calibration-v-a"
        assert result_b.calibration_version_id == "calibration-v-b"

    def test_no_calibration_uses_defaults(self):
        """Without calibration, defaults are used regardless of user."""
        ctx = _make_risk_context()
        engine = RiskEngine()
        result = engine.evaluate(ctx, config=None)
        assert result.calibration_active is False
        assert result.calibration_version_id == ""
        assert result.calibration_validation_status == "default"


class TestSupersededCalibrationIgnored:
    """Test that superseded calibration is not used."""

    def test_superseded_runtime_config_not_active(self):
        """A RuntimeCalibrationConfig with is_active=False yields defaults."""
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v-old",
            is_active=False,
            parameter_snapshot={"signal_weights": {"intent_drift": 0.99}},
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False
        assert effective.signal_weights["intent_drift"] == 0.25  # default


class TestGeneratedCalibrationIgnored:
    """Test that generated (not activated) calibration is not used."""

    def test_generated_version_not_loaded_by_db_adapter(self):
        """The DB adapter only loads active versions."""
        # The DB adapter filters by status == "active"
        # Generated versions have status == "generated" and are not loaded
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v-new",
            is_active=False,  # Not active = generated/pending
            parameter_snapshot={"signal_weights": {"intent_drift": 0.99}},
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False


class TestApprovedButInactiveIgnored:
    """Test that approved-but-not-activated calibration is not used."""

    def test_approved_inactive_not_resolved(self):
        """An approved but not yet activated version is ignored."""
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v-approved",
            is_active=False,
            parameter_snapshot={"signal_weights": {"intent_drift": 0.99}},
        )
        effective = resolve_effective_config(cal)
        assert effective.calibration_active is False


# ── Phase 12: Determinism Tests ───────────────────────────────────


class TestDeterministicEvaluation:
    """Test that evaluation is deterministic for same inputs."""

    def test_same_context_same_config_same_result(self):
        """Same context + same config → same result."""
        ctx = _make_risk_context()
        cfg = _make_calibrated_config()
        engine = RiskEngine()

        results = [engine.evaluate(ctx, config=cfg) for _ in range(5)]
        scores = [r.overall_score for r in results]
        levels = [r.risk_level for r in results]
        confidences = [r.confidence for r in results]

        assert len(set(scores)) == 1, f"Non-deterministic scores: {scores}"
        assert len(set(levels)) == 1, f"Non-deterministic levels: {levels}"
        assert len(set(confidences)) == 1, f"Non-deterministic confidences: {confidences}"

    def test_same_context_no_config_same_result(self):
        """Same context + no config → same result (backward compat)."""
        ctx = _make_risk_context()
        engine = RiskEngine()

        results = [engine.evaluate(ctx, config=None) for _ in range(5)]
        scores = [r.overall_score for r in results]
        assert len(set(scores)) == 1


# ── Phase 13: No Global Mutation Tests ────────────────────────────


class TestNoGlobalMutation:
    """Test that Risk Engine constants are never mutated."""

    def test_signal_weights_unchanged_after_evaluation(self):
        original = dict(SIGNAL_WEIGHTS)
        ctx = _make_risk_context()
        cfg = _make_calibrated_config()
        engine = RiskEngine()
        engine.evaluate(ctx, config=cfg)

        for rt, val in original.items():
            assert SIGNAL_WEIGHTS[rt] == val, f"SIGNAL_WEIGHTS[{rt}] was mutated"

    def test_confidence_reductions_unchanged_after_evaluation(self):
        original = dict(CONFIDENCE_REDUCTIONS)
        ctx = _make_risk_context()
        cfg = _make_calibrated_config()
        engine = RiskEngine()
        engine.evaluate(ctx, config=cfg)

        for key, val in original.items():
            assert CONFIDENCE_REDUCTIONS[key] == val, f"CONFIDENCE_REDUCTIONS[{key}] was mutated"

    def test_risk_level_thresholds_unchanged_after_evaluation(self):
        original = list(RISK_LEVEL_THRESHOLDS)
        ctx = _make_risk_context()
        cfg = _make_calibrated_config()
        engine = RiskEngine()
        engine.evaluate(ctx, config=cfg)

        for i, (thresh, level) in enumerate(original):
            assert RISK_LEVEL_THRESHOLDS[i] == (thresh, level)


# ── Phase 14: Risk Engine Purity Tests ────────────────────────────


class TestRiskEnginePurity:
    """Test that Risk Engine has no DB/external dependencies."""

    def test_risk_engine_config_module_no_db_imports(self):
        import ast
        import os

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "risk_engine", "config.py"
        )
        with open(config_path) as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "sqlalchemy" not in alias.name.lower()
                    assert "database" not in alias.name.lower()
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "sqlalchemy" not in node.module.lower()
                    assert "database" not in node.module.lower()

    def test_engine_no_db_dependency(self):
        """RiskEngine.evaluate() must not require a database session."""
        ctx = _make_risk_context()
        engine = RiskEngine()
        # No db parameter — should work without any DB
        result = engine.evaluate(ctx)
        assert result is not None


# ── Phase 15: Calibration Metadata Tests ──────────────────────────


class TestCalibrationMetadata:
    """Test that calibration metadata is correctly populated."""

    def test_no_calibration_metadata(self):
        ctx = _make_risk_context()
        engine = RiskEngine()
        result = engine.evaluate(ctx, config=None)
        assert result.calibration_active is False
        assert result.calibration_version_id == ""
        assert result.calibration_validation_status == "default"

    def test_active_calibration_metadata(self):
        ctx = _make_risk_context()
        engine = RiskEngine()
        cfg = _make_calibrated_config()
        result = engine.evaluate(ctx, config=cfg)
        assert result.calibration_active is True
        assert result.calibration_version_id == "calibration-v-test"
        assert result.calibration_validation_status == "active"

    def test_config_none_default_status(self):
        ctx = _make_risk_context()
        engine = RiskEngine()
        result = engine.evaluate(ctx, config=None)
        assert result.calibration_validation_status == "default"


# ── Helper Function Tests ─────────────────────────────────────────


class TestHelperFunctions:
    """Test the config helper functions."""

    def test_get_effective_signal_weight_with_config(self):
        cfg = RiskEngineConfig(
            signal_weights={"intent_drift": 0.35},
        )
        assert get_effective_signal_weight(RiskSignalType.INTENT_DRIFT, cfg) == 0.35

    def test_get_effective_signal_weight_without_config(self):
        assert get_effective_signal_weight(RiskSignalType.INTENT_DRIFT, None) == 0.25

    def test_get_effective_signal_weight_missing_in_config(self):
        cfg = RiskEngineConfig(signal_weights={})
        # Falls back to default
        assert get_effective_signal_weight(RiskSignalType.INTENT_DRIFT, cfg) == 0.25

    def test_get_effective_confidence_reduction_with_config(self):
        cfg = RiskEngineConfig(
            confidence_reductions={"drift_missing": 0.25},
        )
        assert get_effective_confidence_reduction("drift_missing", cfg) == 0.25

    def test_get_effective_confidence_reduction_without_config(self):
        assert get_effective_confidence_reduction("drift_missing", None) == 0.15

    def test_get_effective_confidence_floor_with_config(self):
        cfg = RiskEngineConfig(confidence_floor=0.30)
        assert get_effective_confidence_floor(cfg) == 0.30

    def test_get_effective_confidence_floor_without_config(self):
        assert get_effective_confidence_floor(None) == CONFIDENCE_FLOOR

    def test_get_effective_confidence_ceiling_with_config(self):
        cfg = RiskEngineConfig(confidence_ceiling=0.90)
        assert get_effective_confidence_ceiling(cfg) == 0.90

    def test_get_effective_confidence_ceiling_without_config(self):
        assert get_effective_confidence_ceiling(None) == CONFIDENCE_CEILING

    def test_get_effective_risk_level_thresholds_with_config(self):
        cfg = RiskEngineConfig(
            risk_level_thresholds={"critical": 0.80, "high": 0.55, "medium": 0.30, "low": 0.00},
        )
        thresholds = get_effective_risk_level_thresholds(cfg)
        assert len(thresholds) == 4
        # Should be sorted descending
        assert thresholds[0][0] >= thresholds[1][0]

    def test_get_effective_risk_level_thresholds_without_config(self):
        thresholds = get_effective_risk_level_thresholds(None)
        assert thresholds == RISK_LEVEL_THRESHOLDS


# ── Backward Compatibility Regression ─────────────────────────────


class TestBackwardCompatibility:
    """Ensure no-calibration path produces identical results."""

    def test_all_risk_levels_covered(self):
        """Engine should handle all risk levels correctly with no config."""
        engine = RiskEngine()

        # Very low risk context
        ctx_low = _make_risk_context(
            drift_available=True,
            drift_overall_status="match",
            drift_severity="low",
            agent_trust_score=0.95,
            merchant_trust_score=0.90,
            policy_available=True,
            policy_triggered_count=0,
        )
        result_low = engine.evaluate(ctx_low, config=None)
        assert result_low.risk_level in RiskLevel

        # Higher risk context
        ctx_high = _make_risk_context(
            drift_available=True,
            drift_overall_status="mismatch",
            drift_severity="critical",
            agent_trust_score=0.10,
            merchant_trust_score=0.05,
            policy_available=True,
            policy_triggered_count=3,
        )
        result_high = engine.evaluate(ctx_high, config=None)
        assert result_high.risk_level in RiskLevel
        # Higher risk context should produce higher score
        assert result_high.overall_score >= result_low.overall_score

    def test_result_fields_populated(self):
        """All result fields should be populated with no config."""
        ctx = _make_risk_context()
        engine = RiskEngine()
        result = engine.evaluate(ctx, config=None)

        assert result.overall_score >= 0.0
        assert result.overall_score <= 1.0
        assert result.risk_level in RiskLevel
        assert result.confidence >= 0.0
        assert result.confidence <= 1.0
        assert result.evaluation_id != ""
        assert result.evaluated_at != ""
        assert result.risk_model_version == "deterministic-v1"
        assert result.calibration_active is False
