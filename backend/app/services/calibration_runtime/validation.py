"""Calibration Runtime — safe parameter validation.

Pure deterministic validation of calibration parameters.
Every proposed value is validated against known bounds and allowed names.

Rules:
1. Never allow arbitrary parameter names.
2. Never allow negative weights.
3. Signal weights must remain valid (non-negative, sum within tolerance).
4. Risk thresholds must be ordered and within [0, 1].
5. Confidence reductions must be within safe bounds.
6. Unknown parameters are rejected.
7. Malformed values are rejected.
8. Validation is deterministic.
9. Existing defaults are always available as fallback.
10. Invalid calibration is rejected explicitly.
"""

from __future__ import annotations

from app.services.calibration_runtime.constants import (
    ALLOWED_CATEGORIES,
    ALLOWED_CONFIDENCE_BOUNDS,
    ALLOWED_CONFIDENCE_REDUCTION_PARAMS,
    ALLOWED_RISK_THRESHOLD_PARAMS,
    ALLOWED_SIGNAL_WEIGHT_PARAMS,
    CATEGORY_CONFIDENCE_BOUNDS,
    CATEGORY_CONFIDENCE_REDUCTIONS,
    CATEGORY_RISK_THRESHOLDS,
    CATEGORY_SIGNAL_WEIGHTS,
    DEFAULT_CONFIDENCE_CEILING,
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_CONFIDENCE_REDUCTIONS,
    DEFAULT_RISK_LEVEL_THRESHOLDS,
    DEFAULT_SIGNAL_WEIGHTS,
    MAX_CONFIDENCE_CEILING,
    MAX_CONFIDENCE_FLOOR,
    MAX_CONFIDENCE_REDUCTION,
    MAX_RISK_THRESHOLD,
    MAX_SIGNAL_WEIGHT,
    MIN_CONFIDENCE_CEILING,
    MIN_CONFIDENCE_FLOOR,
    MIN_CONFIDENCE_REDUCTION,
    MIN_RISK_THRESHOLD,
    MIN_SIGNAL_WEIGHT,
    SIGNAL_WEIGHT_SUM_TOLERANCE,
)
from app.services.calibration_runtime.models import ValidationOutcome


def validate_calibration_parameters(
    parameter_snapshot: dict,
) -> tuple[bool, list[ValidationOutcome], list[str]]:
    """Validate all calibration parameters in a parameter snapshot.

    Args:
        parameter_snapshot: The proposed calibration parameters from
            an active calibration version.

    Returns:
        (is_valid, validation_outcomes, summary_errors)
        - is_valid: True only if ALL parameters pass validation
        - validation_outcomes: Detailed per-parameter validation results
        - summary_errors: High-level error messages for failed validations
    """
    if not parameter_snapshot:
        # Empty snapshot is valid — means no calibration overrides
        return True, [], []

    outcomes: list[ValidationOutcome] = []
    all_errors: list[str] = []

    # Validate categories
    for category in parameter_snapshot:
        if category not in ALLOWED_CATEGORIES:
            outcomes.append(ValidationOutcome(
                parameter_name=category,
                category="unknown",
                is_valid=False,
                error=f"Unknown calibration category: {category}",
            ))
            all_errors.append(
                f"Unknown calibration category: {category}"
            )

    # Validate signal weights
    sw = parameter_snapshot.get(CATEGORY_SIGNAL_WEIGHTS, {})
    if sw:
        valid, sw_outcomes, sw_errors = _validate_signal_weights(sw)
        outcomes.extend(sw_outcomes)
        all_errors.extend(sw_errors)
    else:
        valid = True

    # Validate risk thresholds
    rt = parameter_snapshot.get(CATEGORY_RISK_THRESHOLDS, {})
    if rt:
        valid, rt_outcomes, rt_errors = _validate_risk_thresholds(rt)
        outcomes.extend(rt_outcomes)
        all_errors.extend(rt_errors)

    # Validate confidence reductions
    cr = parameter_snapshot.get(CATEGORY_CONFIDENCE_REDUCTIONS, {})
    if cr:
        valid, cr_outcomes, cr_errors = _validate_confidence_reductions(cr)
        outcomes.extend(cr_outcomes)
        all_errors.extend(cr_errors)

    # Validate confidence bounds
    cb = parameter_snapshot.get(CATEGORY_CONFIDENCE_BOUNDS, {})
    if cb:
        valid, cb_outcomes, cb_errors = _validate_confidence_bounds(cb)
        outcomes.extend(cb_outcomes)
        all_errors.extend(cb_errors)

    is_valid = len(all_errors) == 0
    return is_valid, outcomes, all_errors


def _validate_signal_weights(
    weights: dict,
) -> tuple[bool, list[ValidationOutcome], list[str]]:
    """Validate signal weights."""
    outcomes: list[ValidationOutcome] = []
    errors: list[str] = []

    for name, value in weights.items():
        if name not in ALLOWED_SIGNAL_WEIGHT_PARAMS:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_SIGNAL_WEIGHTS,
                is_valid=False,
                proposed_value=value if isinstance(value, (int, float)) else None,
                error=f"Unknown signal weight parameter: {name}",
            ))
            errors.append(f"Unknown signal weight: {name}")
            continue

        if not isinstance(value, (int, float)):
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_SIGNAL_WEIGHTS,
                is_valid=False,
                error=f"Signal weight must be numeric, got {type(value).__name__}",
            ))
            errors.append(f"Signal weight '{name}' is not numeric")
            continue

        if value < MIN_SIGNAL_WEIGHT:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_SIGNAL_WEIGHTS,
                is_valid=False,
                current_value=DEFAULT_SIGNAL_WEIGHTS.get(name),
                proposed_value=value,
                error=f"Signal weight must be >= {MIN_SIGNAL_WEIGHT}, got {value}",
            ))
            errors.append(f"Signal weight '{name}' is negative: {value}")
            continue

        if value > MAX_SIGNAL_WEIGHT:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_SIGNAL_WEIGHTS,
                is_valid=False,
                current_value=DEFAULT_SIGNAL_WEIGHTS.get(name),
                proposed_value=value,
                error=f"Signal weight must be <= {MAX_SIGNAL_WEIGHT}, got {value}",
            ))
            errors.append(f"Signal weight '{name}' exceeds maximum: {value}")
            continue

        outcomes.append(ValidationOutcome(
            parameter_name=name,
            category=CATEGORY_SIGNAL_WEIGHTS,
            is_valid=True,
            current_value=DEFAULT_SIGNAL_WEIGHTS.get(name),
            proposed_value=value,
        ))

    # Validate weight sum (excluding data_quality which is 0.0)
    positive_weights = [
        v for k, v in weights.items()
        if k in ALLOWED_SIGNAL_WEIGHT_PARAMS and isinstance(v, (int, float))
    ]
    weight_sum = sum(positive_weights)
    # We only validate the sum if we have all expected weights
    expected_names = {n for n in ALLOWED_SIGNAL_WEIGHT_PARAMS if n != "data_quality"}
    provided_names = {
        n for n in weights
        if n in ALLOWED_SIGNAL_WEIGHT_PARAMS and isinstance(weights[n], (int, float))
    }
    if expected_names.issubset(provided_names) and weight_sum > 0:
        deviation = abs(weight_sum - 1.0)
        if deviation > SIGNAL_WEIGHT_SUM_TOLERANCE:
            errors.append(
                f"Signal weights must sum to ~1.0, got {weight_sum:.6f} "
                f"(deviation: {deviation:.6f})"
            )

    return len(errors) == 0, outcomes, errors


def _validate_risk_thresholds(
    thresholds: dict,
) -> tuple[bool, list[ValidationOutcome], list[str]]:
    """Validate risk level thresholds."""
    outcomes: list[ValidationOutcome] = []
    errors: list[str] = []

    for name, value in thresholds.items():
        if name not in ALLOWED_RISK_THRESHOLD_PARAMS:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_RISK_THRESHOLDS,
                is_valid=False,
                proposed_value=value if isinstance(value, (int, float)) else None,
                error=f"Unknown risk threshold parameter: {name}",
            ))
            errors.append(f"Unknown risk threshold: {name}")
            continue

        if not isinstance(value, (int, float)):
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_RISK_THRESHOLDS,
                is_valid=False,
                error=f"Risk threshold must be numeric, got {type(value).__name__}",
            ))
            errors.append(f"Risk threshold '{name}' is not numeric")
            continue

        if value < MIN_RISK_THRESHOLD or value > MAX_RISK_THRESHOLD:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_RISK_THRESHOLDS,
                is_valid=False,
                current_value=DEFAULT_RISK_LEVEL_THRESHOLDS.get(name),
                proposed_value=value,
                error=f"Risk threshold in [0, 1], got {value}",
            ))
            errors.append(
                f"Risk threshold '{name}' out of range: {value}"
            )
            continue

        outcomes.append(ValidationOutcome(
            parameter_name=name,
            category=CATEGORY_RISK_THRESHOLDS,
            is_valid=True,
            current_value=DEFAULT_RISK_LEVEL_THRESHOLDS.get(name),
            proposed_value=value,
        ))

    # Validate threshold ordering: critical > high > medium > low
    provided_thresholds = {
        k: v for k, v in thresholds.items()
        if k in ALLOWED_RISK_THRESHOLD_PARAMS and isinstance(v, (int, float))
    }
    if len(provided_thresholds) == 4:
        critical = provided_thresholds.get("critical", 0.75)
        high = provided_thresholds.get("high", 0.50)
        medium = provided_thresholds.get("medium", 0.25)
        low = provided_thresholds.get("low", 0.00)
        if not (critical > high > medium >= low):
            errors.append(
                f"Risk thresholds must be ordered: critical > high > medium >= low. "
                f"Got critical={critical}, high={high}, medium={medium}, low={low}"
            )

    return len(errors) == 0, outcomes, errors


def _validate_confidence_reductions(
    reductions: dict,
) -> tuple[bool, list[ValidationOutcome], list[str]]:
    """Validate confidence reductions."""
    outcomes: list[ValidationOutcome] = []
    errors: list[str] = []

    for name, value in reductions.items():
        if name not in ALLOWED_CONFIDENCE_REDUCTION_PARAMS:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_CONFIDENCE_REDUCTIONS,
                is_valid=False,
                proposed_value=value if isinstance(value, (int, float)) else None,
                error=f"Unknown confidence reduction parameter: {name}",
            ))
            errors.append(f"Unknown confidence reduction: {name}")
            continue

        if not isinstance(value, (int, float)):
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_CONFIDENCE_REDUCTIONS,
                is_valid=False,
                error=f"Confidence reduction must be numeric, got {type(value).__name__}",
            ))
            errors.append(f"Confidence reduction '{name}' is not numeric")
            continue

        if value < MIN_CONFIDENCE_REDUCTION or value > MAX_CONFIDENCE_REDUCTION:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_CONFIDENCE_REDUCTIONS,
                is_valid=False,
                current_value=DEFAULT_CONFIDENCE_REDUCTIONS.get(name),
                proposed_value=value,
                error=f"Confidence reduction in [0, 0.5], got {value}",
            ))
            errors.append(
                f"Confidence reduction '{name}' out of range: {value}"
            )
            continue

        outcomes.append(ValidationOutcome(
            parameter_name=name,
            category=CATEGORY_CONFIDENCE_REDUCTIONS,
            is_valid=True,
            current_value=DEFAULT_CONFIDENCE_REDUCTIONS.get(name),
            proposed_value=value,
        ))

    return len(errors) == 0, outcomes, errors


def _validate_confidence_bounds(
    bounds: dict,
) -> tuple[bool, list[ValidationOutcome], list[str]]:
    """Validate confidence bounds (floor and ceiling)."""
    outcomes: list[ValidationOutcome] = []
    errors: list[str] = []

    for name, value in bounds.items():
        if name not in ALLOWED_CONFIDENCE_BOUNDS:
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_CONFIDENCE_BOUNDS,
                is_valid=False,
                proposed_value=value if isinstance(value, (int, float)) else None,
                error=f"Unknown confidence bound parameter: {name}",
            ))
            errors.append(f"Unknown confidence bound: {name}")
            continue

        if not isinstance(value, (int, float)):
            outcomes.append(ValidationOutcome(
                parameter_name=name,
                category=CATEGORY_CONFIDENCE_BOUNDS,
                is_valid=False,
                error=f"Confidence bound must be numeric, got {type(value).__name__}",
            ))
            errors.append(f"Confidence bound '{name}' is not numeric")
            continue

        if name == "confidence_floor":
            if value < MIN_CONFIDENCE_FLOOR or value > MAX_CONFIDENCE_FLOOR:
                outcomes.append(ValidationOutcome(
                    parameter_name=name,
                    category=CATEGORY_CONFIDENCE_BOUNDS,
                    is_valid=False,
                    current_value=DEFAULT_CONFIDENCE_FLOOR,
                    proposed_value=value,
                    error=f"Confidence floor in [0, 0.5], got {value}",
                ))
                errors.append(f"Confidence floor out of range: {value}")
                continue
        elif name == "confidence_ceiling":
            if value < MIN_CONFIDENCE_CEILING or value > MAX_CONFIDENCE_CEILING:
                outcomes.append(ValidationOutcome(
                    parameter_name=name,
                    category=CATEGORY_CONFIDENCE_BOUNDS,
                    is_valid=False,
                    current_value=DEFAULT_CONFIDENCE_CEILING,
                    proposed_value=value,
                    error=f"Confidence ceiling in [0.5, 1], got {value}",
                ))
                errors.append(f"Confidence ceiling out of range: {value}")
                continue

        outcomes.append(ValidationOutcome(
            parameter_name=name,
            category=CATEGORY_CONFIDENCE_BOUNDS,
            is_valid=True,
            proposed_value=value,
        ))

    # Validate floor < ceiling
    floor_val = bounds.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR)
    ceiling_val = bounds.get("confidence_ceiling", DEFAULT_CONFIDENCE_CEILING)
    if isinstance(floor_val, (int, float)) and isinstance(ceiling_val, (int, float)):
        if floor_val >= ceiling_val:
            errors.append(
                f"Confidence floor ({floor_val}) must be less than "
                f"ceiling ({ceiling_val})"
            )

    return len(errors) == 0, outcomes, errors
