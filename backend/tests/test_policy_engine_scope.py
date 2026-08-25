"""Tests for Policy Engine scope matcher."""

from __future__ import annotations

from app.services.policy_engine.models import EvaluationContext, PolicyScope
from app.services.policy_engine.scope import is_policy_applicable


class TestPolicyScopeMatcher:
    def test_no_scope_applies_to_all(self) -> None:
        ctx = EvaluationContext(proposal_transaction_type="purchase")
        assert is_policy_applicable(None, ctx) is True

    def test_empty_scope_applies_to_all(self) -> None:
        scope = PolicyScope()
        ctx = EvaluationContext(proposal_transaction_type="purchase")
        assert is_policy_applicable(scope, ctx) is True

    def test_transaction_type_match(self) -> None:
        scope = PolicyScope(transaction_types=["purchase", "booking"])
        ctx = EvaluationContext(proposal_transaction_type="purchase")
        assert is_policy_applicable(scope, ctx) is True

    def test_transaction_type_mismatch(self) -> None:
        scope = PolicyScope(transaction_types=["transfer"])
        ctx = EvaluationContext(proposal_transaction_type="purchase")
        assert is_policy_applicable(scope, ctx) is False

    def test_agent_id_match(self) -> None:
        scope = PolicyScope(agent_ids=["agent-1", "agent-2"])
        ctx = EvaluationContext(agent_id="agent-1")
        assert is_policy_applicable(scope, ctx) is True

    def test_agent_id_mismatch(self) -> None:
        scope = PolicyScope(agent_ids=["agent-99"])
        ctx = EvaluationContext(agent_id="agent-1")
        assert is_policy_applicable(scope, ctx) is False

    def test_category_match(self) -> None:
        scope = PolicyScope(categories=["shoes", "clothing"])
        ctx = EvaluationContext(proposal_category="shoes")
        assert is_policy_applicable(scope, ctx) is True

    def test_category_mismatch(self) -> None:
        scope = PolicyScope(categories=["laptops"])
        ctx = EvaluationContext(proposal_category="shoes")
        assert is_policy_applicable(scope, ctx) is False

    def test_country_match(self) -> None:
        scope = PolicyScope(countries=["IN", "US"])
        ctx = EvaluationContext(proposal_country="IN")
        assert is_policy_applicable(scope, ctx) is True

    def test_country_mismatch(self) -> None:
        scope = PolicyScope(countries=["US"])
        ctx = EvaluationContext(proposal_country="IN")
        assert is_policy_applicable(scope, ctx) is False

    def test_currency_match(self) -> None:
        scope = PolicyScope(currencies=["INR"])
        ctx = EvaluationContext(proposal_currency="INR")
        assert is_policy_applicable(scope, ctx) is True

    def test_merchant_match(self) -> None:
        scope = PolicyScope(merchant_names=["Amazon", "Flipkart"])
        ctx = EvaluationContext(proposal_merchant_name="Amazon")
        assert is_policy_applicable(scope, ctx) is True

    def test_merchant_mismatch(self) -> None:
        scope = PolicyScope(merchant_names=["EvilCorp"])
        ctx = EvaluationContext(proposal_merchant_name="Amazon")
        assert is_policy_applicable(scope, ctx) is False

    def test_exclude_agent(self) -> None:
        scope = PolicyScope(exclude_agent_ids=["agent-1"])
        ctx = EvaluationContext(agent_id="agent-1")
        assert is_policy_applicable(scope, ctx) is False

    def test_exclude_merchant(self) -> None:
        scope = PolicyScope(exclude_merchant_names=["Amazon"])
        ctx = EvaluationContext(proposal_merchant_name="Amazon")
        assert is_policy_applicable(scope, ctx) is False

    def test_scope_with_null_context_fields(self) -> None:
        scope = PolicyScope(transaction_types=["purchase"])
        ctx = EvaluationContext(proposal_transaction_type=None)
        # If the context field is None, scope filter is skipped (passes)
        assert is_policy_applicable(scope, ctx) is True

    def test_multiple_filters_all_match(self) -> None:
        scope = PolicyScope(
            transaction_types=["purchase"],
            currencies=["INR"],
        )
        ctx = EvaluationContext(
            proposal_transaction_type="purchase",
            proposal_currency="INR",
        )
        assert is_policy_applicable(scope, ctx) is True

    def test_multiple_filters_one_mismatch(self) -> None:
        scope = PolicyScope(
            transaction_types=["purchase"],
            currencies=["USD"],
        )
        ctx = EvaluationContext(
            proposal_transaction_type="purchase",
            proposal_currency="INR",
        )
        assert is_policy_applicable(scope, ctx) is False
