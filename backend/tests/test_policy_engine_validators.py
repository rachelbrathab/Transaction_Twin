"""Tests for Policy Engine validator."""

from __future__ import annotations

from app.services.policy_engine.models import (
    Operator,
    PolicyCondition,
    PolicyRule,
    PolicyRuleSet,
)
from app.services.policy_engine.validators import (
    validate_condition,
    validate_policy_structure,
    validate_rule,
    validate_rule_set,
)

# ── Condition Validation ───────────────────────────────────────────


class TestValidateCondition:
    def test_valid_equals(self) -> None:
        cond = PolicyCondition(
            field="amount", operator=Operator.EQUALS, value="100"
        )
        errors = validate_condition(cond)
        assert errors == []

    def test_numeric_operator_requires_value(self) -> None:
        cond = PolicyCondition(
            field="amount", operator=Operator.GREATER_THAN, value=None
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "requires a non-null value" in errors[0]

    def test_numeric_operator_requires_numeric_value(self) -> None:
        cond = PolicyCondition(
            field="amount",
            operator=Operator.LESS_THAN,
            value="not_a_number",
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "numeric value" in errors[0]

    def test_between_requires_list(self) -> None:
        cond = PolicyCondition(
            field="amount", operator=Operator.BETWEEN, value="100"
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "exactly two values" in errors[0]

    def test_between_requires_two_values(self) -> None:
        cond = PolicyCondition(
            field="amount",
            operator=Operator.BETWEEN,
            value=[100, 200, 300],
        )
        errors = validate_condition(cond)
        assert len(errors) == 1

    def test_between_valid(self) -> None:
        cond = PolicyCondition(
            field="amount",
            operator=Operator.BETWEEN,
            value=[100, 200],
        )
        errors = validate_condition(cond)
        assert errors == []

    def test_in_requires_list(self) -> None:
        cond = PolicyCondition(
            field="currency",
            operator=Operator.IN,
            value="not_a_list",
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "requires a list" in errors[0]

    def test_not_in_requires_list(self) -> None:
        cond = PolicyCondition(
            field="merchant",
            operator=Operator.NOT_IN,
            value=42,
        )
        errors = validate_condition(cond)
        assert len(errors) == 1

    def test_in_requires_value(self) -> None:
        cond = PolicyCondition(
            field="currency",
            operator=Operator.IN,
            value=None,
        )
        errors = validate_condition(cond)
        assert len(errors) == 1

    def test_matches_requires_string(self) -> None:
        cond = PolicyCondition(
            field="name",
            operator=Operator.MATCHES,
            value=None,
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "regex pattern" in errors[0]

    def test_matches_rejects_long_pattern(self) -> None:
        cond = PolicyCondition(
            field="name",
            operator=Operator.MATCHES,
            value="a" * 201,
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "maximum length" in errors[0]

    def test_matches_rejects_invalid_regex(self) -> None:
        cond = PolicyCondition(
            field="name",
            operator=Operator.MATCHES,
            value="[invalid",
        )
        errors = validate_condition(cond)
        assert len(errors) == 1
        assert "Invalid regex" in errors[0]

    def test_matches_valid_regex(self) -> None:
        cond = PolicyCondition(
            field="name",
            operator=Operator.MATCHES,
            value=r"^\d{4}$",
        )
        errors = validate_condition(cond)
        assert errors == []

    def test_contains_any_requires_list(self) -> None:
        cond = PolicyCondition(
            field="category",
            operator=Operator.CONTAINS_ANY,
            value="not_a_list",
        )
        errors = validate_condition(cond)
        assert len(errors) == 1

    def test_exists_requires_no_value(self) -> None:
        cond = PolicyCondition(
            field="amount", operator=Operator.EXISTS
        )
        errors = validate_condition(cond)
        assert errors == []


# ── Rule Validation ─────────────────────────────────────────────────


class TestValidateRule:
    def test_valid_rule(self) -> None:
        rule = PolicyRule(
            name="max_amount",
            conditions=[
                PolicyCondition(
                    field="amount",
                    operator=Operator.GREATER_THAN,
                    value="10000",
                )
            ],
        )
        errors = validate_rule(rule)
        assert errors == []

    def test_rule_with_invalid_condition(self) -> None:
        rule = PolicyRule(
            name="bad_rule",
            conditions=[
                PolicyCondition(
                    field="amount",
                    operator=Operator.GREATER_THAN,
                    value=None,
                )
            ],
        )
        errors = validate_rule(rule)
        assert len(errors) == 1
        assert "condition[0]" in errors[0]


# ── Rule Set Validation ─────────────────────────────────────────────


class TestValidateRuleSet:
    def test_valid_rule_set(self) -> None:
        rs = PolicyRuleSet(rules=[
            PolicyRule(
                name="r1",
                conditions=[
                    PolicyCondition(
                        field="a", operator=Operator.EXISTS
                    )
                ],
            )
        ])
        errors = validate_rule_set(rs)
        assert errors == []


# ── Policy Structure Validation ────────────────────────────────────


class TestValidatePolicyStructure:
    def test_none_rules(self) -> None:
        result = validate_policy_structure(None, None)
        assert result.valid is False
        assert "no rules" in result.errors[0]

    def test_invalid_rules_structure(self) -> None:
        result = validate_policy_structure(
            {"rules": "not_a_list"}, None
        )
        assert result.valid is False

    def test_valid_structure(self) -> None:
        rules = {
            "rules": [
                {
                    "name": "max_amount",
                    "conditions": [
                        {
                            "field": "proposal_amount",
                            "operator": "greater_than",
                            "value": "10000",
                        }
                    ],
                }
            ]
        }
        result = validate_policy_structure(rules, None)
        assert result.valid is True
        assert result.errors == []

    def test_valid_structure_with_scope(self) -> None:
        rules = {
            "rules": [
                {
                    "name": "rule1",
                    "conditions": [
                        {
                            "field": "proposal_amount",
                            "operator": "exists",
                        }
                    ],
                }
            ]
        }
        scope = {"transaction_types": ["purchase"]}
        result = validate_policy_structure(rules, scope)
        assert result.valid is True

    def test_invalid_scope_structure(self) -> None:
        rules = {
            "rules": [
                {
                    "name": "rule1",
                    "conditions": [
                        {"field": "a", "operator": "exists"}
                    ],
                }
            ]
        }
        scope = {"transaction_types": "not_a_list"}
        result = validate_policy_structure(rules, scope)
        assert result.valid is False
        assert any("scope" in e.lower() for e in result.errors)

    def test_rule_with_invalid_condition_structure(self) -> None:
        rules = {
            "rules": [
                {
                    "name": "bad",
                    "conditions": [
                        {
                            "field": "amount",
                            "operator": "greater_than",
                            "value": "not_a_number",
                        }
                    ],
                }
            ]
        }
        result = validate_policy_structure(rules, None)
        assert result.valid is False
