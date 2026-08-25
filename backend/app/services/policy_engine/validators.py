"""Policy Validator — validates policy structure before evaluation.

Rejects malformed policies with INVALID_POLICY.
Does not silently accept invalid definitions.
"""

from __future__ import annotations

import re

from app.services.policy_engine.models import (
    MAX_CONDITIONS_PER_RULE,
    MAX_REGEX_LENGTH,
    MAX_RULES_PER_POLICY,
    Operator,
    PolicyCondition,
    PolicyRule,
    PolicyRuleSet,
    ValueType,
)


class ValidationResult:
    """Result of policy validation."""

    def __init__(self, valid: bool, errors: list[str] | None = None) -> None:
        self.valid = valid
        self.errors: list[str] = errors or []


def validate_condition(condition: PolicyCondition) -> list[str]:
    """Validate a single condition. Returns list of error messages."""
    errors: list[str] = []

    # Validate operator is supported
    try:
        Operator(condition.operator)
    except ValueError:
        errors.append(f"Unsupported operator: {condition.operator}")

    # Validate value_type
    try:
        ValueType(condition.value_type)
    except ValueError:
        errors.append(f"Unsupported value_type: {condition.value_type}")

    # Validate value based on operator type
    if condition.operator in (Operator.GREATER_THAN, Operator.LESS_THAN,
                              Operator.GREATER_THAN_OR_EQUAL, Operator.LESS_THAN_OR_EQUAL):
        if condition.value is None:
            errors.append(f"Operator '{condition.operator}' requires a non-null value")
        else:
            try:
                Decimal(str(condition.value))
            except (InvalidOperation, ValueError):
                errors.append(
                    f"Operator '{condition.operator}' requires a numeric value, "
                    f"got: {condition.value}"
                )

    elif condition.operator == Operator.BETWEEN:
        if condition.value is None:
            errors.append("Operator 'between' requires a list of two values [min, max]")
        elif not isinstance(condition.value, list) or len(condition.value) != 2:
            errors.append("Operator 'between' requires a list of exactly two values [min, max]")
        else:
            try:
                Decimal(str(condition.value[0]))
                Decimal(str(condition.value[1]))
            except (InvalidOperation, ValueError, IndexError):
                errors.append("Operator 'between' requires numeric values")

    elif condition.operator in (Operator.IN, Operator.NOT_IN):
        if condition.value is None:
            errors.append(f"Operator '{condition.operator}' requires a list value")
        elif not isinstance(condition.value, list):
            type_name = type(condition.value).__name__
            errors.append(
                f"Operator '{condition.operator}' requires"
                f" a list, got: {type_name}"
            )

    elif condition.operator == Operator.MATCHES:
        if condition.value is None:
            errors.append("Operator 'matches' requires a regex pattern string")
        elif not isinstance(condition.value, str):
            errors.append("Operator 'matches' requires a string pattern")
        elif len(condition.value) > MAX_REGEX_LENGTH:
            errors.append(f"Regex pattern exceeds maximum length of {MAX_REGEX_LENGTH}")
        else:
            try:
                re.compile(condition.value)
            except re.error as e:
                errors.append(f"Invalid regex pattern: {e}")

    elif condition.operator == Operator.CONTAINS_ANY:
        if condition.value is None or not isinstance(condition.value, list):
            errors.append("Operator 'contains_any' requires a list of strings")

    return errors


def validate_rule(rule: PolicyRule) -> list[str]:
    """Validate a single rule. Returns list of error messages."""
    errors: list[str] = []

    if not rule.conditions:
        errors.append("Rule must have at least one condition")

    if len(rule.conditions) > MAX_CONDITIONS_PER_RULE:
        errors.append(
            f"Rule has {len(rule.conditions)} conditions, "
            f"maximum is {MAX_CONDITIONS_PER_RULE}"
        )

    for i, condition in enumerate(rule.conditions):
        condition_errors = validate_condition(condition)
        for err in condition_errors:
            errors.append(f"Rule '{rule.name}' condition[{i}]: {err}")

    return errors


def validate_rule_set(rule_set: PolicyRuleSet) -> list[str]:
    """Validate a complete rule set. Returns list of error messages."""
    errors: list[str] = []

    if not rule_set.rules:
        errors.append("Policy must have at least one rule")

    if len(rule_set.rules) > MAX_RULES_PER_POLICY:
        errors.append(
            f"Policy has {len(rule_set.rules)} rules, "
            f"maximum is {MAX_RULES_PER_POLICY}"
        )

    for i, rule in enumerate(rule_set.rules):
        rule_errors = validate_rule(rule)
        for err in rule_errors:
            errors.append(f"Rule[{i}] '{rule.name}': {err}")

    return errors


def validate_policy_structure(rules_raw: dict | None, scope_raw: dict | None) -> ValidationResult:
    """Validate policy JSON structure from database.

    Returns ValidationResult with valid=True or valid=False with error list.
    """
    if rules_raw is None:
        return ValidationResult(valid=False, errors=["Policy has no rules"])

    # Parse rule set
    try:
        rule_set = PolicyRuleSet(**rules_raw)
    except Exception as e:
        return ValidationResult(valid=False, errors=[f"Invalid policy rules structure: {e}"])

    errors = validate_rule_set(rule_set)

    # Validate scope if provided
    if scope_raw is not None:
        try:
            from app.services.policy_engine.models import PolicyScope
            PolicyScope(**scope_raw)
        except Exception as e:
            errors.append(f"Invalid policy scope structure: {e}")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    return ValidationResult(valid=True)


# Need Decimal import for validate_condition
from decimal import Decimal, InvalidOperation  # noqa: E402
