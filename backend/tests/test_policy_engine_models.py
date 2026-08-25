"""Tests for Policy Engine domain models."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.services.policy_engine.models import (
    ConditionResult,
    ConditionStatus,
    EvaluationContext,
    LogicOperator,
    Operator,
    PolicyCategory,
    PolicyCondition,
    PolicyEvaluationResult,
    PolicyEvaluationStatus,
    PolicyResult,
    PolicyRule,
    PolicyRuleSet,
    PolicyScope,
    PolicySeverity,
    ValueType,
)

# ── Operator Enum ──────────────────────────────────────────────────


class TestOperatorEnum:
    def test_all_operators_present(self) -> None:
        expected = {
            "equals", "not_equals", "greater_than",
            "greater_than_or_equal", "less_than",
            "less_than_or_equal", "in", "not_in",
            "contains", "contains_any", "matches",
            "between", "exists", "not_exists",
        }
        actual = {op.value for op in Operator}
        assert actual == expected

    def test_operator_count(self) -> None:
        assert len(Operator) == 14


# ── ValueType Enum ─────────────────────────────────────────────────


class TestValueTypeEnum:
    def test_all_types(self) -> None:
        expected = {"string", "decimal", "boolean", "list", "datetime"}
        actual = {vt.value for vt in ValueType}
        assert actual == expected


# ── PolicySeverity Enum ────────────────────────────────────────────


class TestPolicySeverityEnum:
    def test_severity_ordering(self) -> None:
        assert PolicySeverity.NONE.value == "none"
        assert PolicySeverity.LOW.value == "low"
        assert PolicySeverity.MEDIUM.value == "medium"
        assert PolicySeverity.HIGH.value == "high"
        assert PolicySeverity.CRITICAL.value == "critical"


# ── PolicyCategory Enum ───────────────────────────────────────────


class TestPolicyCategoryEnum:
    def test_all_categories(self) -> None:
        categories = {c.value for c in PolicyCategory}
        assert "amount_limit" in categories
        assert "merchant_restriction" in categories
        assert "category_restriction" in categories
        assert "geographic_restriction" in categories
        assert "frequency_limit" in categories


# ── PolicyCondition Model ──────────────────────────────────────────


class TestPolicyConditionModel:
    def test_valid_condition(self) -> None:
        cond = PolicyCondition(
            field="proposal_amount",
            operator=Operator.GREATER_THAN,
            value="10000",
            value_type=ValueType.DECIMAL,
        )
        assert cond.field == "proposal_amount"
        assert cond.operator == Operator.GREATER_THAN

    def test_condition_requires_field(self) -> None:
        with pytest.raises(ValidationError):
            PolicyCondition(operator=Operator.EQUALS, value="test")

    def test_condition_requires_operator(self) -> None:
        with pytest.raises(ValidationError):
            PolicyCondition(field="amount", value="100")

    def test_condition_default_value_type(self) -> None:
        cond = PolicyCondition(
            field="test", operator=Operator.EQUALS, value="x"
        )
        assert cond.value_type == ValueType.STRING

    def test_condition_empty_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PolicyCondition(field="", operator=Operator.EQUALS, value="x")


# ── PolicyRule Model ───────────────────────────────────────────────


class TestPolicyRuleModel:
    def test_valid_rule(self) -> None:
        rule = PolicyRule(
            name="max_amount",
            conditions=[
                PolicyCondition(
                    field="proposal_amount",
                    operator=Operator.GREATER_THAN,
                    value="10000",
                )
            ],
        )
        assert rule.name == "max_amount"
        assert rule.logic == LogicOperator.ALL
        assert rule.severity == PolicySeverity.MEDIUM

    def test_rule_requires_conditions(self) -> None:
        with pytest.raises(ValidationError):
            PolicyRule(name="empty", conditions=[])

    def test_rule_max_conditions(self) -> None:
        conds = [
            PolicyCondition(field=f"f{i}", operator=Operator.EXISTS)
            for i in range(10)
        ]
        rule = PolicyRule(name="max", conditions=conds)
        assert len(rule.conditions) == 10

    def test_rule_too_many_conditions(self) -> None:
        conds = [
            PolicyCondition(field=f"f{i}", operator=Operator.EXISTS)
            for i in range(11)
        ]
        with pytest.raises(ValidationError):
            PolicyRule(name="too_many", conditions=conds)


# ── PolicyRuleSet Model ────────────────────────────────────────────


class TestPolicyRuleSetModel:
    def test_valid_rule_set(self) -> None:
        rs = PolicyRuleSet(rules=[
            PolicyRule(
                name="rule1",
                conditions=[
                    PolicyCondition(
                        field="amount", operator=Operator.EXISTS
                    )
                ],
            )
        ])
        assert len(rs.rules) == 1

    def test_empty_rules_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PolicyRuleSet(rules=[])


# ── PolicyScope Model ──────────────────────────────────────────────


class TestPolicyScopeModel:
    def test_empty_scope(self) -> None:
        scope = PolicyScope()
        assert scope.transaction_types is None
        assert scope.agent_ids is None

    def test_full_scope(self) -> None:
        scope = PolicyScope(
            transaction_types=["purchase"],
            agent_ids=["agent-1"],
            categories=["shoes"],
            countries=["IN"],
            currencies=["INR"],
            merchant_names=["Amazon"],
            exclude_agent_ids=["agent-2"],
            exclude_merchant_names=["EvilCorp"],
        )
        assert scope.transaction_types == ["purchase"]
        assert scope.exclude_agent_ids == ["agent-2"]


# ── EvaluationContext Model ─────────────────────────────────────────


class TestEvaluationContextModel:
    def test_empty_context(self) -> None:
        ctx = EvaluationContext()
        assert ctx.proposal_amount is None

    def test_full_context(self) -> None:
        ctx = EvaluationContext(
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            user_id="user-1",
            agent_id="agent-1",
        )
        assert ctx.proposal_amount == Decimal("5000")
        assert ctx.user_id == "user-1"

    def test_get_field_value_existing(self) -> None:
        ctx = EvaluationContext(proposal_amount=Decimal("100"))
        assert ctx.get_field_value("proposal_amount") == Decimal("100")

    def test_get_field_value_missing(self) -> None:
        ctx = EvaluationContext()
        assert ctx.get_field_value("nonexistent_field") is None

    def test_get_field_value_none(self) -> None:
        ctx = EvaluationContext(proposal_amount=None)
        assert ctx.get_field_value("proposal_amount") is None


# ── ConditionResult Model ───────────────────────────────────────────


class TestConditionResultModel:
    def test_valid_result(self) -> None:
        cr = ConditionResult(
            field="amount",
            operator="greater_than",
            expected_value="10000",
            observed_value="12000",
            status=ConditionStatus.MATCH,
            explanation="Value is greater",
        )
        assert cr.status == ConditionStatus.MATCH


# ── RuleResult Model ───────────────────────────────────────────────


class TestRuleResultModel:
    def test_valid_rule_result(self) -> None:
        rr = PolicyResult(
            policy_id="p1",
            policy_version=1,
            policy_name="test",
            status=PolicyEvaluationStatus.PASS,
        )
        assert rr.status == PolicyEvaluationStatus.PASS
        assert rr.highest_triggered_severity == PolicySeverity.NONE


# ── PolicyEvaluationResult Model ───────────────────────────────────


class TestPolicyEvaluationResultModel:
    def test_empty_result(self) -> None:
        per = PolicyEvaluationResult(
            intent_id="i1",
            proposal_intent_id="i1",
            evaluation_id="e1",
        )
        assert per.total_policies == 0
        assert per.triggered_count == 0
        assert per.highest_severity == PolicySeverity.NONE
        assert per.evaluator_version == "policy-v1"

    def test_result_with_counts(self) -> None:
        per = PolicyEvaluationResult(
            intent_id="i1",
            proposal_intent_id="i1",
            evaluation_id="e1",
            total_policies=5,
            triggered_count=2,
            unknown_count=1,
            invalid_count=0,
            pass_count=2,
        )
        assert per.total_policies == 5


# ── PolicyEvaluationStatus Enum ────────────────────────────────────


class TestPolicyEvaluationStatusEnum:
    def test_statuses(self) -> None:
        statuses = {s.value for s in PolicyEvaluationStatus}
        assert statuses == {"pass", "triggered", "unknown", "invalid_policy"}


# ── ConditionStatus Enum ────────────────────────────────────────────


class TestConditionStatusEnum:
    def test_statuses(self) -> None:
        statuses = {s.value for s in ConditionStatus}
        assert statuses == {"match", "mismatch", "unknown", "not_applicable"}


# ── LogicOperator Enum ──────────────────────────────────────────────


class TestLogicOperatorEnum:
    def test_operators(self) -> None:
        assert LogicOperator.ALL.value == "all"
        assert LogicOperator.ANY.value == "any"
