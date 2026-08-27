"""Calibration Runtime — pure configuration resolver.

Resolves the EFFECTIVE risk-engine configuration from defaults
and an active calibration version. Pure function — no database,
no external calls, no mutable global state.

CRITICAL SAFETY:
- NEVER mutates existing Risk Engine constants.
- Falls back to safe defaults when calibration is invalid.
- Fail-closed: invalid calibration → use defaults entirely.
"""

from __future__ import annotations

from app.services.calibration_runtime.constants import (
    CATEGORY_CONFIDENCE_BOUNDS,
    CATEGORY_CONFIDENCE_REDUCTIONS,
    CATEGORY_RISK_THRESHOLDS,
    CATEGORY_SIGNAL_WEIGHTS,
    DEFAULT_CONFIDENCE_CEILING,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_CONFIDENCE_REDUCTIONS,
    DEFAULT_RISK_LEVEL_THRESHOLDS,
    DEFAULT_SIGNAL_WEIGHTS,
)
from app.services.calibration_runtime.models import (
    EffectiveCalibrationConfig,
    RuntimeCalibrationConfig,
)
from app.services.calibration_runtime.validation import (
    validate_calibration_parameters,
)


def resolve_effective_config(
    active_calibration: RuntimeCalibrationConfig | None = None,
) -> EffectiveCalibrationConfig:
    """Resolve the effective risk-engine configuration.

    When no active calibration exists, returns the exact existing
    Risk Engine defaults. When calibration is active but invalid,
    returns defaults with calibration_active=False.

    Args:
        active_calibration: The active calibration version, or None
            if no calibration is active.

    Returns:
        EffectiveCalibrationConfig with the resolved parameters.
    """
    # No active calibration → exact defaults
    if active_calibration is None or not active_calibration.is_active:
        return EffectiveCalibrationConfig(
            calibration_active=False,
            source_version_id="",
            signal_weights=dict(DEFAULT_SIGNAL_WEIGHTS),
            risk_level_thresholds=dict(DEFAULT_RISK_LEVEL_THRESHOLDS),
            confidence_reductions=dict(DEFAULT_CONFIDENCE_REDUCTIONS),
            confidence_floor=DEFAULT_CONFIDENCE_FLOOR,
            confidence_ceiling=DEFAULT_CONFIDENCE_CEILING,
            validation_passed=True,
        )

    # Active calibration exists — validate and resolve
    snapshot = active_calibration.parameter_snapshot or {}

    is_valid, outcomes, errors = validate_calibration_parameters(snapshot)

    if not is_valid:
        # FAIL CLOSED: invalid calibration → use safe defaults
        return EffectiveCalibrationConfig(
            calibration_active=False,
            source_version_id=active_calibration.version_id,
            signal_weights=dict(DEFAULT_SIGNAL_WEIGHTS),
            risk_level_thresholds=dict(DEFAULT_RISK_LEVEL_THRESHOLDS),
            confidence_reductions=dict(DEFAULT_CONFIDENCE_REDUCTIONS),
            confidence_floor=DEFAULT_CONFIDENCE_FLOOR,
            confidence_ceiling=DEFAULT_CONFIDENCE_CEILING,
            validation_passed=False,
            validation_errors=errors,
            parameters_rejected=[
                o.parameter_name for o in outcomes if not o.is_valid
            ],
        )

    # Validation passed — apply calibrated values over defaults
    resolved_weights = _apply_signal_weights(
        snapshot.get(CATEGORY_SIGNAL_WEIGHTS, {}),
    )
    resolved_thresholds = _apply_risk_thresholds(
        snapshot.get(CATEGORY_RISK_THRESHOLDS, {}),
    )
    resolved_reductions = _apply_confidence_reductions(
        snapshot.get(CATEGORY_CONFIDENCE_REDUCTIONS, {}),
    )
    resolved_floor, resolved_ceiling = _apply_confidence_bounds(
        snapshot.get(CATEGORY_CONFIDENCE_BOUNDS, {}),
    )

    return EffectiveCalibrationConfig(
        calibration_active=True,
        source_version_id=active_calibration.version_id,
        signal_weights=resolved_weights,
        risk_level_thresholds=resolved_thresholds,
        confidence_reductions=resolved_reductions,
        confidence_floor=resolved_floor,
        confidence_ceiling=resolved_ceiling,
        validation_passed=True,
        parameters_applied=[
            o.parameter_name for o in outcomes if o.is_valid
        ],
    )


def _apply_signal_weights(overrides: dict) -> dict[str, float]:
    """Apply validated signal weight overrides over defaults."""
    result = dict(DEFAULT_SIGNAL_WEIGHTS)
    for name, value in overrides.items():
        if name in DEFAULT_SIGNAL_WEIGHTS and isinstance(value, (int, float)):
            result[name] = value
    return result


def _apply_risk_thresholds(overrides: dict) -> dict[str, float]:
    """Apply validated risk threshold overrides over defaults."""
    result = dict(DEFAULT_RISK_LEVEL_THRESHOLDS)
    for name, value in overrides.items():
        if name in DEFAULT_RISK_LEVEL_THRESHOLDS and isinstance(value, (int, float)):
            result[name] = value
    return result


def _apply_confidence_reductions(overrides: dict) -> dict[str, float]:
    """Apply validated confidence reduction overrides over defaults."""
    result = dict(DEFAULT_CONFIDENCE_REDUCTIONS)
    for name, value in overrides.items():
        if name in DEFAULT_CONFIDENCE_REDUCTIONS and isinstance(value, (int, float)):
            result[name] = value
    return result


def _apply_confidence_bounds(bounds: dict) -> tuple[float, float]:
    """Apply validated confidence bounds over defaults."""
    floor = bounds.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR)
    ceiling = bounds.get("confidence_ceiling", DEFAULT_CONFIDENCE_CEILING)
    if not isinstance(floor, (int, float)):
        floor = DEFAULT_CONFIDENCE_FLOOR
    if not isinstance(ceiling, (int, float)):
        ceiling = DEFAULT_CONFIDENCE_CEILING
    return float(floor), float(ceiling)
