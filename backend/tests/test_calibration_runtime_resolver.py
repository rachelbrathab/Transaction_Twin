"""Calibration Runtime — resolver and validation tests.

All tests in this file are DATABASE-FREE.
Pure function testing of the validation layer and resolver.
"""

from __future__ import annotations

import pytest

from app.services.calibration_runtime.constants import (
    DEFAULT_CONFIDENCE_CEILING,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_CONFIDENCE_REDUCTIONS,
    DEFAULT_RISK_LEVEL_THRESHOLDS,
    DEFAULT_SIGNAL_WEIGHTS,
)
from app.services.calibration_runtime.models import (
    EffectiveCalibrationConfig,
    RuntimeCalibrationConfig,
    ValidationOutcome,
)
from app.services.calibration_runtime.resolver import resolve_effective_config
from app.services.calibration_runtime.validation import (
    validate_calibration_parameters,
)

# ══════════════════════════════════════════════════════════════════
# Validation Tests
# ══════════════════════════════════════════════════════════════════


class TestValidateSignalWeights:
    def test_valid_weights_pass(self):
        is_valid, outcomes, errors = validate_calibration_parameters(
            {"signal_weights": {"intent_drift": 0.30, "amount_anomaly": 0.10}}
        )
        assert is_valid is True
        assert len(errors) == 0
        assert len(outcomes) == 2
        assert all(o.is_valid for o in outcomes)

    def test_negative_weight_rejected(self):
        is_valid, outcomes, errors = validate_calibration_parameters(
            {"signal_weights": {"intent_drift": -0.10}}
        )
        assert is_valid is False
        assert any("negative" in e.lower() or ">=" in e for e in errors)

    def test_excessive_weight_rejected(self):
        is_valid, outcomes, errors = validate_calibration_parameters(
            {"signal_weights": {"intent_drift": 2.0}}
        )
        assert is_valid is False
        assert any("maximum" in e.lower() or "<=" in e for e in errors)

    def test_unknown_signal_weight_rejected(self):
        is_valid, outcomes, errors = validate_calibration_parameters(
            {"signal_weights": {"unknown_signal": 0.5}}
        )
        assert is_valid is False
        assert any("unknown" in e.lower() for e in errors)

    def test_non_numeric_weight_rejected(self):
        is_valid, outcomes, errors = validate_calibration_parameters(
            {"signal_weights": {"intent_drift": "high"}}
        )
        assert is_valid is False
        assert any("numeric" in e.lower() for e in errors)

    def test_zero_weight_allowed(self):
        is_valid, outcomes, errors = validate_calibration_parameters(
            {"signal_weights": {"velocity": 0.0}}
        )
        assert is_valid is True

    def test_weight_sum_deviation_rejected(self):
        # Provide all weights but sum to wrong value
        is_valid, outcomes, errors = validate_calibration_parameters(
            {
                "signal_weights": {
                    "intent_drift": 0.50,
                    "amount_anomaly": 0.50,
                    "agent_trust": 0.50,
                    "merchant_trust": 0.50,
                    "policy_interaction": 0.50,
                    "velocity": 0.50,
                    "data_quality": 0.00,
                    "currency_mismatch": 0.50,
                    "geographic_anomaly": 0.50,
                }
            }
        )
        assert is_valid is False
        assert any("sum" in e.lower() for e in errors)


class TestValidateRiskThresholds:
    def test_valid_thresholds_pass(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"risk_level_thresholds": {"critical": 0.80, "high": 0.55}}
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_out_of_range_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"risk_level_thresholds": {"critical": 1.5}}
        )
        assert is_valid is False

    def test_negative_threshold_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"risk_level_thresholds": {"low": -0.1}}
        )
        assert is_valid is False

    def test_unknown_threshold_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"risk_level_thresholds": {"ultra_critical": 0.99}}
        )
        assert is_valid is False

    def test_non_numeric_threshold_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"risk_level_thresholds": {"high": "medium_high"}}
        )
        assert is_valid is False

    def test_invalid_ordering_rejected(self):
        # critical must be > high > medium >= low
        is_valid, _, errors = validate_calibration_parameters(
            {
                "risk_level_thresholds": {
                    "critical": 0.40,
                    "high": 0.50,
                    "medium": 0.25,
                    "low": 0.00,
                }
            }
        )
        assert is_valid is False
        assert any("ordered" in e.lower() for e in errors)


class TestValidateConfidenceReductions:
    def test_valid_reductions_pass(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_reductions": {"drift_missing": 0.20}}
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_excessive_reduction_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_reductions": {"drift_missing": 0.60}}
        )
        assert is_valid is False

    def test_negative_reduction_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_reductions": {"drift_missing": -0.10}}
        )
        assert is_valid is False

    def test_unknown_reduction_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_reductions": {"unknown_context": 0.10}}
        )
        assert is_valid is False


class TestValidateConfidenceBounds:
    def test_valid_bounds_pass(self):
        is_valid, _, errors = validate_calibration_parameters(
            {
                "confidence_bounds": {
                    "confidence_floor": 0.15,
                    "confidence_ceiling": 0.95,
                }
            }
        )
        assert is_valid is True

    def test_floor_exceeds_ceiling_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {
                "confidence_bounds": {
                    "confidence_floor": 0.90,
                    "confidence_ceiling": 0.50,
                }
            }
        )
        assert is_valid is False
        assert any("floor" in e.lower() and "ceiling" in e.lower() for e in errors)

    def test_floor_out_of_range_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_bounds": {"confidence_floor": 0.8}}
        )
        assert is_valid is False

    def test_ceiling_out_of_range_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_bounds": {"confidence_ceiling": 0.3}}
        )
        assert is_valid is False

    def test_unknown_bound_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"confidence_bounds": {"unknown_bound": 0.5}}
        )
        assert is_valid is False


class TestValidateUnknownCategories:
    def test_unknown_category_rejected(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"unknown_category": {"key": "value"}}
        )
        assert is_valid is False
        assert any("unknown" in e.lower() and "category" in e.lower() for e in errors)

    def test_multiple_unknown_categories(self):
        is_valid, _, errors = validate_calibration_parameters(
            {"cat_a": {}, "cat_b": {}}
        )
        assert is_valid is False
        assert len(errors) == 2


class TestValidateEmptySnapshot:
    def test_empty_snapshot_valid(self):
        is_valid, outcomes, errors = validate_calibration_parameters({})
        assert is_valid is True
        assert outcomes == []
        assert errors == []


# ══════════════════════════════════════════════════════════════════
# Resolver Tests
# ══════════════════════════════════════════════════════════════════


class TestResolveNoCalibration:
    def test_none_calibration_returns_defaults(self):
        config = resolve_effective_config(None)
        assert config.calibration_active is False
        assert config.source_version_id == ""
        assert config.signal_weights == DEFAULT_SIGNAL_WEIGHTS
        assert config.risk_level_thresholds == DEFAULT_RISK_LEVEL_THRESHOLDS
        assert config.confidence_reductions == DEFAULT_CONFIDENCE_REDUCTIONS
        assert config.confidence_floor == DEFAULT_CONFIDENCE_FLOOR
        assert config.confidence_ceiling == DEFAULT_CONFIDENCE_CEILING
        assert config.validation_passed is True

    def test_inactive_calibration_returns_defaults(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=False,
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is False
        assert config.signal_weights == DEFAULT_SIGNAL_WEIGHTS

    def test_empty_snapshot_returns_defaults(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={},
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.validation_passed is True
        assert config.signal_weights == DEFAULT_SIGNAL_WEIGHTS


class TestResolveWithValidCalibration:
    def test_signal_weight_override(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {"intent_drift": 0.35},
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.signal_weights["intent_drift"] == 0.35
        # Other weights remain default
        assert config.signal_weights["amount_anomaly"] == 0.15

    def test_risk_threshold_override(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "risk_level_thresholds": {"critical": 0.80},
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.risk_level_thresholds["critical"] == 0.80
        assert config.risk_level_thresholds["high"] == 0.50  # default

    def test_confidence_reduction_override(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "confidence_reductions": {"drift_missing": 0.20},
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.confidence_reductions["drift_missing"] == 0.20
        assert config.confidence_reductions["agent_trust_missing"] == 0.10

    def test_confidence_bounds_override(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "confidence_bounds": {
                    "confidence_floor": 0.15,
                    "confidence_ceiling": 0.95,
                },
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.confidence_floor == 0.15
        assert config.confidence_ceiling == 0.95

    def test_multiple_categories_override(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {"intent_drift": 0.30},
                "risk_level_thresholds": {"critical": 0.80},
                "confidence_reductions": {"drift_missing": 0.20},
                "confidence_bounds": {
                    "confidence_floor": 0.15,
                    "confidence_ceiling": 0.90,
                },
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is True
        assert config.signal_weights["intent_drift"] == 0.30
        assert config.risk_level_thresholds["critical"] == 0.80
        assert config.confidence_reductions["drift_missing"] == 0.20
        assert config.confidence_floor == 0.15
        assert config.confidence_ceiling == 0.90

    def test_source_version_populated(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v-abc123",
            is_active=True,
            parameter_snapshot={},
        )
        config = resolve_effective_config(cal)
        assert config.source_version_id == "calibration-v-abc123"

    def test_parameters_applied_listed(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {"intent_drift": 0.30, "amount_anomaly": 0.10},
            },
        )
        config = resolve_effective_config(cal)
        assert "intent_drift" in config.parameters_applied
        assert "amount_anomaly" in config.parameters_applied


class TestResolveWithInvalidCalibration:
    def test_invalid_signal_weight_fails_closed(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {"intent_drift": -0.10},
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is False
        assert config.validation_passed is False
        assert len(config.validation_errors) > 0
        assert config.signal_weights == DEFAULT_SIGNAL_WEIGHTS

    def test_invalid_category_fails_closed(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "unknown_stuff": {"x": 1},
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is False
        assert config.validation_passed is False

    def test_mixed_valid_and_invalid_fails_closed(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {
                    "intent_drift": 0.30,  # valid
                    "unknown_signal": 0.50,  # invalid
                },
            },
        )
        config = resolve_effective_config(cal)
        assert config.calibration_active is False
        assert config.validation_passed is False
        # Defaults are preserved
        assert config.signal_weights == DEFAULT_SIGNAL_WEIGHTS

    def test_parameters_rejected_listed(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {"intent_drift": -0.10},
            },
        )
        config = resolve_effective_config(cal)
        assert "intent_drift" in config.parameters_rejected


class TestResolveDeterministic:
    def test_same_inputs_same_output(self):
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {"intent_drift": 0.35},
            },
        )
        c1 = resolve_effective_config(cal)
        c2 = resolve_effective_config(cal)
        assert c1.model_dump() == c2.model_dump()

    def test_different_inputs_different_output(self):
        cal1 = RuntimeCalibrationConfig(
            version_id="v1",
            is_active=True,
            parameter_snapshot={"signal_weights": {"intent_drift": 0.30}},
        )
        cal2 = RuntimeCalibrationConfig(
            version_id="v2",
            is_active=True,
            parameter_snapshot={"signal_weights": {"intent_drift": 0.40}},
        )
        c1 = resolve_effective_config(cal1)
        c2 = resolve_effective_config(cal2)
        assert c1.signal_weights["intent_drift"] != c2.signal_weights["intent_drift"]


class TestFailClosedBehavior:
    def test_partial_override_not_applied(self):
        """If validation fails, NO overrides should be applied."""
        cal = RuntimeCalibrationConfig(
            version_id="calibration-v1",
            is_active=True,
            parameter_snapshot={
                "signal_weights": {
                    "intent_drift": 0.30,  # valid
                    "unknown": 0.50,  # invalid — causes failure
                },
            },
        )
        config = resolve_effective_config(cal)
        # The valid override is NOT applied because validation failed entirely
        assert config.calibration_active is False
        assert config.signal_weights["intent_drift"] == DEFAULT_SIGNAL_WEIGHTS["intent_drift"]


class TestModelBehavior:
    def test_effective_config_is_frozen(self):
        config = EffectiveCalibrationConfig()
        with pytest.raises(Exception):
            config.calibration_active = True  # type: ignore[misc]

    def test_runtime_config_is_frozen(self):
        config = RuntimeCalibrationConfig(version_id="v1")
        with pytest.raises(Exception):
            config.version_id = "v2"  # type: ignore[misc]

    def test_validation_outcome_is_frozen(self):
        outcome = ValidationOutcome(
            parameter_name="test", category="test", is_valid=True,
        )
        with pytest.raises(Exception):
            outcome.is_valid = False  # type: ignore[misc]
