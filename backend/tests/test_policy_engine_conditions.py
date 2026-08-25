"""Tests for Policy Engine condition evaluator — all 14 operators."""

from __future__ import annotations

from decimal import Decimal

from app.services.policy_engine.conditions import evaluate_condition
from app.services.policy_engine.models import (
    ConditionResult,
    ConditionStatus,
    EvaluationContext,
    Operator,
    PolicyCondition,
)

# ── Helper ─────────────────────────────────────────────────────────


def _eval(
    field: str,
    operator: Operator,
    value=None,
    **ctx_kwargs,
) -> ConditionResult:
    """Evaluate a condition with a fresh context."""
    ctx = EvaluationContext(**ctx_kwargs)
    cond = PolicyCondition(field=field, operator=operator, value=value)
    return evaluate_condition(cond, ctx)

# ── EQUALS ─────────────────────────────────────────────────────────


class TestEqualsOperator:
    def test_match(self) -> None:
        r = _eval("proposal_currency", Operator.EQUALS, "INR",
                   proposal_currency="INR")
        assert r.status == ConditionStatus.MATCH

    def test_case_insensitive_match(self) -> None:
        r = _eval("proposal_currency", Operator.EQUALS, "inr",
                   proposal_currency="INR")
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval("proposal_currency", Operator.EQUALS, "USD",
                   proposal_currency="INR")
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval("proposal_currency", Operator.EQUALS, "INR",
                   proposal_currency=None)
        assert r.status == ConditionStatus.UNKNOWN


# ── NOT_EQUALS ─────────────────────────────────────────────────────


class TestNotEqualsOperator:
    def test_match(self) -> None:
        r = _eval("proposal_currency", Operator.NOT_EQUALS, "USD",
                   proposal_currency="INR")
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval("proposal_currency", Operator.NOT_EQUALS, "INR",
                   proposal_currency="INR")
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval("proposal_currency", Operator.NOT_EQUALS, "USD",
                   proposal_currency=None)
        assert r.status == ConditionStatus.UNKNOWN


# ── GREATER_THAN ───────────────────────────────────────────────────


class TestGreaterThanOperator:
    def test_match(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN, "10000",
                   proposal_amount=Decimal("12000"))
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN, "10000",
                   proposal_amount=Decimal("8000"))
        assert r.status == ConditionStatus.MISMATCH

    def test_equal_is_mismatch(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN, "10000",
                   proposal_amount=Decimal("10000"))
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN, "10000",
                   proposal_amount=None)
        assert r.status == ConditionStatus.UNKNOWN


# ── GREATER_THAN_OR_EQUAL ─────────────────────────────────────────


class TestGreaterThanOrEqualOperator:
    def test_match_greater(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN_OR_EQUAL,
                   "10000", proposal_amount=Decimal("12000"))
        assert r.status == ConditionStatus.MATCH

    def test_match_equal(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN_OR_EQUAL,
                   "10000", proposal_amount=Decimal("10000"))
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval("proposal_amount", Operator.GREATER_THAN_OR_EQUAL,
                   "10000", proposal_amount=Decimal("8000"))
        assert r.status == ConditionStatus.MISMATCH


# ── LESS_THAN ──────────────────────────────────────────────────────


class TestLessThanOperator:
    def test_match(self) -> None:
        r = _eval("proposal_amount", Operator.LESS_THAN, "10000",
                   proposal_amount=Decimal("5000"))
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval("proposal_amount", Operator.LESS_THAN, "10000",
                   proposal_amount=Decimal("15000"))
        assert r.status == ConditionStatus.MISMATCH

    def test_equal_is_mismatch(self) -> None:
        r = _eval("proposal_amount", Operator.LESS_THAN, "10000",
                   proposal_amount=Decimal("10000"))
        assert r.status == ConditionStatus.MISMATCH


# ── LESS_THAN_OR_EQUAL ────────────────────────────────────────────


class TestLessThanOrEqualOperator:
    def test_match_less(self) -> None:
        r = _eval("proposal_amount", Operator.LESS_THAN_OR_EQUAL,
                   "10000", proposal_amount=Decimal("5000"))
        assert r.status == ConditionStatus.MATCH

    def test_match_equal(self) -> None:
        r = _eval("proposal_amount", Operator.LESS_THAN_OR_EQUAL,
                   "10000", proposal_amount=Decimal("10000"))
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval("proposal_amount", Operator.LESS_THAN_OR_EQUAL,
                   "10000", proposal_amount=Decimal("15000"))
        assert r.status == ConditionStatus.MISMATCH


# ── IN ─────────────────────────────────────────────────────────────


class TestInOperator:
    def test_match(self) -> None:
        r = _eval(
            "proposal_currency", Operator.IN,
            ["INR", "USD", "EUR"],
            proposal_currency="INR",
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval(
            "proposal_currency", Operator.IN,
            ["USD", "EUR"],
            proposal_currency="INR",
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_case_insensitive(self) -> None:
        r = _eval(
            "proposal_currency", Operator.IN,
            ["inr", "usd"],
            proposal_currency="INR",
        )
        assert r.status == ConditionStatus.MATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_currency", Operator.IN,
            ["INR", "USD"],
            proposal_currency=None,
        )
        assert r.status == ConditionStatus.UNKNOWN


# ── NOT_IN ─────────────────────────────────────────────────────────


class TestNotInOperator:
    def test_match(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.NOT_IN,
            ["EvilCorp", "ScamCo"],
            proposal_merchant_name="Amazon",
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.NOT_IN,
            ["EvilCorp", "Amazon"],
            proposal_merchant_name="Amazon",
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.NOT_IN,
            ["EvilCorp"],
            proposal_merchant_name=None,
        )
        assert r.status == ConditionStatus.UNKNOWN


# ── CONTAINS ───────────────────────────────────────────────────────


class TestContainsOperator:
    def test_match(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS, "shoes",
            proposal_category="black running shoes",
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS, "laptop",
            proposal_category="black running shoes",
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS, "shoes",
            proposal_category=None,
        )
        assert r.status == ConditionStatus.UNKNOWN

    def test_case_insensitive(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS, "SHOES",
            proposal_category="Black Running Shoes",
        )
        assert r.status == ConditionStatus.MATCH


# ── CONTAINS_ANY ──────────────────────────────────────────────────


class TestContainsAnyOperator:
    def test_match(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS_ANY,
            ["shoes", "boots"],
            proposal_category="running shoes",
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS_ANY,
            ["laptop", "phone"],
            proposal_category="running shoes",
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_category", Operator.CONTAINS_ANY,
            ["shoes"],
            proposal_category=None,
        )
        assert r.status == ConditionStatus.UNKNOWN


# ── MATCHES ────────────────────────────────────────────────────────


class TestMatchesOperator:
    def test_match(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.MATCHES,
            r"^Amazon.*",
            proposal_merchant_name="Amazon India",
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.MATCHES,
            r"^Flipkart",
            proposal_merchant_name="Amazon",
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.MATCHES,
            r".*",
            proposal_merchant_name=None,
        )
        assert r.status == ConditionStatus.UNKNOWN

    def test_invalid_pattern_returns_unknown(self) -> None:
        r = _eval(
            "proposal_merchant_name", Operator.MATCHES,
            "[invalid",
            proposal_merchant_name="Amazon",
        )
        assert r.status == ConditionStatus.UNKNOWN


# ── BETWEEN ────────────────────────────────────────────────────────


class TestBetweenOperator:
    def test_match(self) -> None:
        r = _eval(
            "proposal_amount", Operator.BETWEEN,
            ["1000", "5000"],
            proposal_amount=Decimal("3000"),
        )
        assert r.status == ConditionStatus.MATCH

    def test_match_boundary(self) -> None:
        r = _eval(
            "proposal_amount", Operator.BETWEEN,
            ["1000", "5000"],
            proposal_amount=Decimal("1000"),
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch_above(self) -> None:
        r = _eval(
            "proposal_amount", Operator.BETWEEN,
            ["1000", "5000"],
            proposal_amount=Decimal("6000"),
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_mismatch_below(self) -> None:
        r = _eval(
            "proposal_amount", Operator.BETWEEN,
            ["1000", "5000"],
            proposal_amount=Decimal("500"),
        )
        assert r.status == ConditionStatus.MISMATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_amount", Operator.BETWEEN,
            ["1000", "5000"],
            proposal_amount=None,
        )
        assert r.status == ConditionStatus.UNKNOWN


# ── EXISTS ─────────────────────────────────────────────────────────


class TestExistsOperator:
    def test_match_when_value_present(self) -> None:
        r = _eval(
            "proposal_amount", Operator.EXISTS,
            proposal_amount=Decimal("5000"),
        )
        assert r.status == ConditionStatus.MATCH

    def test_unknown_when_null(self) -> None:
        r = _eval(
            "proposal_amount", Operator.EXISTS,
            proposal_amount=None,
        )
        assert r.status == ConditionStatus.UNKNOWN


# ── NOT_EXISTS ─────────────────────────────────────────────────────


class TestNotExistsOperator:
    def test_match_when_null(self) -> None:
        r = _eval(
            "proposal_amount", Operator.NOT_EXISTS,
            proposal_amount=None,
        )
        assert r.status == ConditionStatus.MATCH

    def test_mismatch_when_present(self) -> None:
        r = _eval(
            "proposal_amount", Operator.NOT_EXISTS,
            proposal_amount=Decimal("5000"),
        )
        assert r.status == ConditionStatus.MISMATCH


# ── Field Not In Context ──────────────────────────────────────────


class TestFieldNotInContext:
    def test_nonexistent_field_returns_unknown(self) -> None:
        r = _eval(
            "totally_nonexistent_field", Operator.EQUALS, "test",
        )
        assert r.status == ConditionStatus.UNKNOWN
        assert "not available" in r.explanation
