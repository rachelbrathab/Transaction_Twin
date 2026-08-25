"""Condition Evaluator — deterministic evaluation of individual policy conditions.

Implements all 14 operators via an explicit operator registry.
No eval(), no exec(), no dynamic imports, no arbitrary code execution.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.policy_engine.models import (
    MAX_REGEX_LENGTH,
    ConditionResult,
    ConditionStatus,
    EvaluationContext,
    Operator,
    PolicyCondition,
)


def _get_field_value(context: EvaluationContext, field_name: str) -> tuple[Any, bool]:
    """Get field value from context.

    Returns (value, exists).
    exists=False means the field is not in the context at all.
    exists=True with value=None means the field exists but is null.
    """
    if not hasattr(context, field_name):
        return None, False
    return getattr(context, field_name), True


def _coerce_decimal(value: Any) -> Decimal | None:
    """Safely coerce a value to Decimal. Returns None if impossible."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    """Safely coerce a value to datetime. Returns None if impossible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


# ── Operator Implementations ───────────────────────────────────────


def _op_equals(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if str(observed).lower() == str(expected).lower():
        return ConditionStatus.MATCH, f"Value equals {expected}"
    return ConditionStatus.MISMATCH, f"Value '{observed}' does not equal '{expected}'"


def _op_not_equals(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if str(observed).lower() != str(expected).lower():
        return ConditionStatus.MATCH, f"Value does not equal {expected}"
    return ConditionStatus.MISMATCH, f"Value '{observed}' equals '{expected}'"


def _compare_numeric(
    observed: Any, expected: Any, op_str: str
) -> tuple[ConditionStatus, str]:
    """Compare two values numerically."""
    obs_dec = _coerce_decimal(observed)
    exp_dec = _coerce_decimal(expected)

    if obs_dec is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if exp_dec is None:
        return ConditionStatus.UNKNOWN, f"Expected value is not numeric: {expected}"

    return obs_dec, exp_dec


def _op_greater_than(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    result = _compare_numeric(observed, expected, ">")
    if isinstance(result[0], ConditionStatus):
        return result  # type: ignore[return-value]
    obs_dec, exp_dec = result  # type: ignore[misc]
    if obs_dec > exp_dec:
        return ConditionStatus.MATCH, f"Value {obs_dec} is greater than {exp_dec}"
    return ConditionStatus.MISMATCH, f"Value {obs_dec} is not greater than {exp_dec}"


def _op_greater_than_or_equal(
    observed: Any, expected: Any, _field: str
) -> tuple[ConditionStatus, str]:
    result = _compare_numeric(observed, expected, ">=")
    if isinstance(result[0], ConditionStatus):
        return result  # type: ignore[return-value]
    obs_dec, exp_dec = result  # type: ignore[misc]
    if obs_dec >= exp_dec:
        return ConditionStatus.MATCH, f"Value {obs_dec} >= {exp_dec}"
    return ConditionStatus.MISMATCH, f"Value {obs_dec} < {exp_dec}"


def _op_less_than(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    result = _compare_numeric(observed, expected, "<")
    if isinstance(result[0], ConditionStatus):
        return result  # type: ignore[return-value]
    obs_dec, exp_dec = result  # type: ignore[misc]
    if obs_dec < exp_dec:
        return ConditionStatus.MATCH, f"Value {obs_dec} < {exp_dec}"
    return ConditionStatus.MISMATCH, f"Value {obs_dec} >= {exp_dec}"


def _op_less_than_or_equal(
    observed: Any, expected: Any, _field: str
) -> tuple[ConditionStatus, str]:
    result = _compare_numeric(observed, expected, "<=")
    if isinstance(result[0], ConditionStatus):
        return result  # type: ignore[return-value]
    obs_dec, exp_dec = result  # type: ignore[misc]
    if obs_dec <= exp_dec:
        return ConditionStatus.MATCH, f"Value {obs_dec} <= {exp_dec}"
    return ConditionStatus.MISMATCH, f"Value {obs_dec} > {exp_dec}"


def _op_in(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if not isinstance(expected, list):
        return ConditionStatus.UNKNOWN, "Expected value is not a list"
    if str(observed).lower() in [str(v).lower() for v in expected]:
        return ConditionStatus.MATCH, f"Value '{observed}' is in allowed list"
    return ConditionStatus.MISMATCH, f"Value '{observed}' is not in allowed list"


def _op_not_in(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if not isinstance(expected, list):
        return ConditionStatus.UNKNOWN, "Expected value is not a list"
    if str(observed).lower() not in [str(v).lower() for v in expected]:
        return ConditionStatus.MATCH, f"Value '{observed}' is not in excluded list"
    return ConditionStatus.MISMATCH, f"Value '{observed}' is in excluded list"


def _op_contains(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if expected is None:
        return ConditionStatus.UNKNOWN, "Expected value is null"
    if str(expected).lower() in str(observed).lower():
        return ConditionStatus.MATCH, f"Value contains '{expected}'"
    return ConditionStatus.MISMATCH, f"Value does not contain '{expected}'"


def _op_contains_any(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if not isinstance(expected, list):
        return ConditionStatus.UNKNOWN, "Expected value is not a list"
    obs_lower = str(observed).lower()
    for item in expected:
        if str(item).lower() in obs_lower:
            return ConditionStatus.MATCH, f"Value contains '{item}'"
    return ConditionStatus.MISMATCH, "Value does not contain any of the expected items"


def _op_matches(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if not isinstance(expected, str):
        return ConditionStatus.UNKNOWN, "Expected value is not a string pattern"
    if len(expected) > MAX_REGEX_LENGTH:
        return ConditionStatus.UNKNOWN, "Regex pattern too long"
    try:
        pattern = re.compile(expected, re.IGNORECASE)
    except re.error:
        return ConditionStatus.UNKNOWN, f"Invalid regex pattern: {expected}"
    if pattern.search(str(observed)):
        return ConditionStatus.MATCH, f"Value matches pattern '{expected}'"
    return ConditionStatus.MISMATCH, f"Value does not match pattern '{expected}'"


def _op_between(observed: Any, expected: Any, _field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.UNKNOWN, "Field value is unknown"
    if not isinstance(expected, list) or len(expected) != 2:
        return ConditionStatus.UNKNOWN, "Expected value must be [min, max]"
    obs_dec = _coerce_decimal(observed)
    min_dec = _coerce_decimal(expected[0])
    max_dec = _coerce_decimal(expected[1])
    if obs_dec is None:
        return ConditionStatus.UNKNOWN, "Field value is not numeric"
    if min_dec is None or max_dec is None:
        return ConditionStatus.UNKNOWN, "Range bounds are not numeric"
    if min_dec <= obs_dec <= max_dec:
        return ConditionStatus.MATCH, f"Value {obs_dec} is between {min_dec} and {max_dec}"
    return ConditionStatus.MISMATCH, f"Value {obs_dec} is not between {min_dec} and {max_dec}"


def _op_exists(observed: Any, _expected: Any, field: str) -> tuple[ConditionStatus, str]:
    """Check if field exists in context (not necessarily non-null).

    Note: This uses the raw observed value. If the field is not in the context,
    the caller should have already handled that. Here we check if the value is non-None.
    """
    # The get_field_value already returned exists=True for known fields.
    # Here we just check if the value itself is non-None.
    if observed is not None:
        return ConditionStatus.MATCH, f"Field '{field}' exists and has a value"
    return ConditionStatus.UNKNOWN, f"Field '{field}' is null"


def _op_not_exists(observed: Any, _expected: Any, field: str) -> tuple[ConditionStatus, str]:
    if observed is None:
        return ConditionStatus.MATCH, f"Field '{field}' has no value"
    return ConditionStatus.MISMATCH, f"Field '{field}' has a value: {observed}"


# ── Operator Registry ──────────────────────────────────────────────

OPERATOR_REGISTRY: dict[Operator, Callable[[Any, Any, str], tuple[ConditionStatus, str]]] = {
    Operator.EQUALS: _op_equals,
    Operator.NOT_EQUALS: _op_not_equals,
    Operator.GREATER_THAN: _op_greater_than,
    Operator.GREATER_THAN_OR_EQUAL: _op_greater_than_or_equal,
    Operator.LESS_THAN: _op_less_than,
    Operator.LESS_THAN_OR_EQUAL: _op_less_than_or_equal,
    Operator.IN: _op_in,
    Operator.NOT_IN: _op_not_in,
    Operator.CONTAINS: _op_contains,
    Operator.CONTAINS_ANY: _op_contains_any,
    Operator.MATCHES: _op_matches,
    Operator.BETWEEN: _op_between,
    Operator.EXISTS: _op_exists,
    Operator.NOT_EXISTS: _op_not_exists,
}


# ── Condition Evaluator ────────────────────────────────────────────


def evaluate_condition(
    condition: PolicyCondition,
    context: EvaluationContext,
) -> ConditionResult:
    """Evaluate a single policy condition against the context.

    Returns a ConditionResult with status MATCH, MISMATCH, or UNKNOWN.
    Never throws — malformed conditions return UNKNOWN.
    """
    observed_value, field_exists = _get_field_value(context, condition.field)

    # If field doesn't exist in context at all
    if not field_exists:
        return ConditionResult(
            field=condition.field,
            operator=condition.operator,
            expected_value=condition.value,
            observed_value=None,
            status=ConditionStatus.UNKNOWN,
            explanation=f"Field '{condition.field}' is not available in the context",
        )

    # Get the operator function
    try:
        op = Operator(condition.operator)
    except ValueError:
        return ConditionResult(
            field=condition.field,
            operator=condition.operator,
            expected_value=condition.value,
            observed_value=observed_value,
            status=ConditionStatus.UNKNOWN,
            explanation=f"Unknown operator: {condition.operator}",
        )

    op_func = OPERATOR_REGISTRY.get(op)
    if op_func is None:
        return ConditionResult(
            field=condition.field,
            operator=condition.operator,
            expected_value=condition.value,
            observed_value=observed_value,
            status=ConditionStatus.UNKNOWN,
            explanation=f"Operator not implemented: {condition.operator}",
        )

    # Evaluate
    try:
        status, explanation = op_func(observed_value, condition.value, condition.field)
    except Exception as e:
        return ConditionResult(
            field=condition.field,
            operator=condition.operator,
            expected_value=condition.value,
            observed_value=observed_value,
            status=ConditionStatus.UNKNOWN,
            explanation=f"Evaluation error: {e}",
        )

    return ConditionResult(
        field=condition.field,
        operator=condition.operator,
        expected_value=condition.value,
        observed_value=observed_value,
        status=status,
        explanation=explanation,
    )
