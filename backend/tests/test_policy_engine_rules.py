"""Tests for Policy Engine rule evaluator — AND/OR logic and UNKNOWN semantics."""

from __future__ import annotations

from decimal import Decimal

from app.services.policy_engine.models import (
    EvaluationContext,
    LogicOperator,
    Operator,
    PolicyCondition,
    PolicyEvaluationStatus,
    PolicyRule,
)
from app.services.policy_engine.rules import evaluate_rule


def _make_rule(
    name: str,
    conditions: list[PolicyCondition],
    logic: LogicOperator = LogicOperator.ALL,
) -> PolicyRule:
    return PolicyRule(name=name, conditions=conditions, logic=logic)


# ── ALL / AND Logic ───────────────────────────────────────────────


class TestAllLogic:
    def test_all_match(self) -> None:
        rule = _make_rule("all_match", [
            PolicyCondition(
                field="proposal_currency", operator=Operator.EQUALS,
                value="INR",
            ),
            PolicyCondition(
                field="proposal_transaction_type",
                operator=Operator.EQUALS,
                value="purchase",
            ),
        ])
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_transaction_type="purchase",
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.PASS

    def test_one_mismatch_triggers(self) -> None:
        rule = _make_rule("one_mismatch", [
            PolicyCondition(
                field="proposal_currency",
                operator=Operator.EQUALS,
                value="INR",
            ),
            PolicyCondition(
                field="proposal_transaction_type",
                operator=Operator.EQUALS,
                value="transfer",
            ),
        ])
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_transaction_type="purchase",
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.TRIGGERED

    # CRITICAL UNKNOWN SEMANTICS:
    # ALL: MISMATCH + UNKNOWN → TRIGGERED
    def test_all_mismatch_plus_unknown_triggers(self) -> None:
        rule = _make_rule("mismatch_unknown", [
            PolicyCondition(
                field="proposal_currency",
                operator=Operator.EQUALS,
                value="USD",
            ),
            PolicyCondition(
                field="proposal_category",
                operator=Operator.EQUALS,
                value="shoes",
            ),
        ])
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category=None,
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.TRIGGERED

    # ALL: MATCH + UNKNOWN → UNKNOWN
    def test_all_match_plus_unknown_is_unknown(self) -> None:
        rule = _make_rule("match_unknown", [
            PolicyCondition(
                field="proposal_currency",
                operator=Operator.EQUALS,
                value="INR",
            ),
            PolicyCondition(
                field="proposal_category",
                operator=Operator.EQUALS,
                value="shoes",
            ),
        ])
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category=None,
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.UNKNOWN

    def test_all_all_unknown(self) -> None:
        rule = _make_rule("all_unknown", [
            PolicyCondition(
                field="proposal_currency",
                operator=Operator.EQUALS,
                value="INR",
            ),
            PolicyCondition(
                field="proposal_category",
                operator=Operator.EQUALS,
                value="shoes",
            ),
        ])
        ctx = EvaluationContext(
            proposal_currency=None,
            proposal_category=None,
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.UNKNOWN


# ── ANY / OR Logic ────────────────────────────────────────────────


class TestAnyLogic:
    def test_any_one_match_passes(self) -> None:
        rule = _make_rule(
            "any_match",
            [
                PolicyCondition(
                    field="proposal_currency",
                    operator=Operator.EQUALS,
                    value="INR",
                ),
                PolicyCondition(
                    field="proposal_category",
                    operator=Operator.EQUALS,
                    value="shoes",
                ),
            ],
            logic=LogicOperator.ANY,
        )
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category="laptops",
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.PASS

    def test_any_none_match_triggers(self) -> None:
        rule = _make_rule(
            "any_trigger",
            [
                PolicyCondition(
                    field="proposal_currency",
                    operator=Operator.EQUALS,
                    value="USD",
                ),
                PolicyCondition(
                    field="proposal_category",
                    operator=Operator.EQUALS,
                    value="shoes",
                ),
            ],
            logic=LogicOperator.ANY,
        )
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category="laptops",
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.TRIGGERED

    # ANY: MATCH + UNKNOWN → PASS
    def test_any_match_plus_unknown_passes(self) -> None:
        rule = _make_rule(
            "any_match_unknown",
            [
                PolicyCondition(
                    field="proposal_currency",
                    operator=Operator.EQUALS,
                    value="INR",
                ),
                PolicyCondition(
                    field="proposal_category",
                    operator=Operator.EQUALS,
                    value="shoes",
                ),
            ],
            logic=LogicOperator.ANY,
        )
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category=None,
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.PASS

    # ANY: MISMATCH + UNKNOWN → UNKNOWN
    def test_any_mismatch_plus_unknown_is_unknown(self) -> None:
        rule = _make_rule(
            "any_mismatch_unknown",
            [
                PolicyCondition(
                    field="proposal_currency",
                    operator=Operator.EQUALS,
                    value="USD",
                ),
                PolicyCondition(
                    field="proposal_category",
                    operator=Operator.EQUALS,
                    value="shoes",
                ),
            ],
            logic=LogicOperator.ANY,
        )
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category=None,
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.UNKNOWN

    # ANY: MISMATCH + MISMATCH → TRIGGERED
    def test_any_mismatch_mismatch_triggers(self) -> None:
        rule = _make_rule(
            "any_mismatch_mismatch",
            [
                PolicyCondition(
                    field="proposal_currency",
                    operator=Operator.EQUALS,
                    value="USD",
                ),
                PolicyCondition(
                    field="proposal_category",
                    operator=Operator.EQUALS,
                    value="shoes",
                ),
            ],
            logic=LogicOperator.ANY,
        )
        ctx = EvaluationContext(
            proposal_currency="INR",
            proposal_category="laptops",
        )
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.TRIGGERED


# ── Rule Metadata ─────────────────────────────────────────────────


class TestRuleMetadata:
    def test_severity_preserved(self) -> None:
        from app.services.policy_engine.models import PolicySeverity
        rule = PolicyRule(
            name="critical_rule",
            severity=PolicySeverity.CRITICAL,
            conditions=[
                PolicyCondition(
                    field="proposal_amount",
                    operator=Operator.GREATER_THAN,
                    value="50000",
                )
            ],
        )
        ctx = EvaluationContext(
            proposal_amount=Decimal("60000"),
        )
        result = evaluate_rule(rule, ctx)
        assert result.severity == PolicySeverity.CRITICAL

    def test_condition_results_preserved(self) -> None:
        rule = _make_rule("with_conditions", [
            PolicyCondition(
                field="proposal_currency",
                operator=Operator.EQUALS,
                value="INR",
            ),
        ])
        ctx = EvaluationContext(proposal_currency="INR")
        result = evaluate_rule(rule, ctx)
        assert len(result.condition_results) == 1
        assert result.condition_results[0].field == "proposal_currency"

    def test_explanation_generated(self) -> None:
        rule = _make_rule("explained", [
            PolicyCondition(
                field="proposal_currency",
                operator=Operator.EQUALS,
                value="INR",
            ),
        ])
        ctx = EvaluationContext(proposal_currency="INR")
        result = evaluate_rule(rule, ctx)
        assert len(result.explanation) > 0


# ── Single Condition Rules ─────────────────────────────────────────


class TestSingleConditionRules:
    def test_single_amount_exceeded(self) -> None:
        rule = _make_rule("amount_check", [
            PolicyCondition(
                field="proposal_amount",
                operator=Operator.LESS_THAN_OR_EQUAL,
                value="10000",
            ),
        ])
        ctx = EvaluationContext(proposal_amount=Decimal("12000"))
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.TRIGGERED

    def test_single_amount_within_limit(self) -> None:
        rule = _make_rule("amount_check", [
            PolicyCondition(
                field="proposal_amount",
                operator=Operator.LESS_THAN_OR_EQUAL,
                value="10000",
            ),
        ])
        ctx = EvaluationContext(proposal_amount=Decimal("8000"))
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.PASS

    def test_unknown_amount(self) -> None:
        rule = _make_rule("amount_check", [
            PolicyCondition(
                field="proposal_amount",
                operator=Operator.LESS_THAN_OR_EQUAL,
                value="10000",
            ),
        ])
        ctx = EvaluationContext(proposal_amount=None)
        result = evaluate_rule(rule, ctx)
        assert result.status == PolicyEvaluationStatus.UNKNOWN
