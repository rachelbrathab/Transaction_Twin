"""Tests for Policy Engine evaluator — full orchestration."""

from __future__ import annotations

from decimal import Decimal

from app.services.policy_engine.evaluator import PolicyEvaluator
from app.services.policy_engine.models import (
    EvaluationContext,
    PolicyEvaluationStatus,
    PolicySeverity,
)


def _make_policy(
    policy_id: str,
    name: str,
    rules: list[dict],
    *,
    status: str = "active",
    version: int = 1,
    scope: dict | None = None,
    effective_from: str | None = None,
    effective_until: str | None = None,
) -> dict:
    return {
        "id": policy_id,
        "name": name,
        "version": version,
        "status": status,
        "rules": {"rules": rules},
        "scope": scope,
        "effective_from": effective_from,
        "effective_until": effective_until,
    }


def _amount_rule(
    name: str = "max_amount",
    max_value: str = "10000",
    *,
    severity: str = "high",
) -> dict:
    return {
        "name": name,
        "severity": severity,
        "category": "amount_limit",
        "logic": "all",
        "conditions": [
            {
                "field": "proposal_amount",
                "operator": "less_than_or_equal",
                "value": max_value,
                "value_type": "decimal",
            }
        ],
    }


def _currency_rule(
    name: str = "currency_check",
    allowed: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "severity": "medium",
        "category": "currency_restriction",
        "logic": "all",
        "conditions": [
            {
                "field": "proposal_currency",
                "operator": "in",
                "value": allowed or ["INR"],
                "value_type": "list",
            }
        ],
    }


def _merchant_rule() -> dict:
    return {
        "name": "trusted_merchants",
        "severity": "high",
        "category": "merchant_restriction",
        "logic": "all",
        "conditions": [
            {
                "field": "proposal_merchant_trusted",
                "operator": "equals",
                "value": True,
                "value_type": "boolean",
            }
        ],
    }


DEFAULT_CONTEXT = EvaluationContext(
    proposal_amount=Decimal("5000"),
    proposal_currency="INR",
    proposal_transaction_type="purchase",
    proposal_category="shoes",
    proposal_merchant_name="Amazon",
    proposal_merchant_trusted=True,
    proposal_country="IN",
    user_id="user-1",
    agent_id="agent-1",
)


# ── Basic Evaluation ──────────────────────────────────────────────


class TestBasicEvaluation:
    def test_no_policies(self) -> None:
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0
        assert result.triggered_count == 0
        assert result.pass_count == 0

    def test_single_passing_policy(self) -> None:
        policy = _make_policy("p1", "amount_ok", [_amount_rule()])
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 1
        assert result.pass_count == 1
        assert result.triggered_count == 0

    def test_single_triggered_policy(self) -> None:
        context = EvaluationContext(
            proposal_amount=Decimal("15000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            user_id="user-1",
            agent_id="agent-1",
        )
        policy = _make_policy("p1", "amount_limit", [_amount_rule()])
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=context,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 1
        assert result.triggered_count == 1
        assert result.pass_count == 0

    def test_multiple_policies_mixed(self) -> None:
        policies = [
            _make_policy("p1", "amount_ok", [_amount_rule()]),
            _make_policy("p2", "amount_fail", [_amount_rule("fail", "1000")]),
        ]
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=policies, context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 2
        assert result.triggered_count == 1
        assert result.pass_count == 1


# ── Policy Lifecycle ──────────────────────────────────────────────


class TestPolicyLifecycle:
    def test_draft_policy_skipped(self) -> None:
        policy = _make_policy("p1", "draft", [_amount_rule()], status="draft")
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0

    def test_suspended_policy_skipped(self) -> None:
        policy = _make_policy(
            "p1", "suspended", [_amount_rule()], status="suspended"
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0

    def test_archived_policy_skipped(self) -> None:
        policy = _make_policy(
            "p1", "archived", [_amount_rule()], status="archived"
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0


# ── Invalid Policy Handling ───────────────────────────────────────


class TestInvalidPolicyHandling:
    def test_invalid_policy_produces_invalid_status(self) -> None:
        policy = _make_policy(
            "p1", "bad_policy", [{"name": "r1", "conditions": []}]
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 1
        assert result.invalid_count == 1
        pr = result.policy_results[0]
        assert pr.status == PolicyEvaluationStatus.INVALID_POLICY

    def test_invalid_does_not_stop_valid(self) -> None:
        policies = [
            _make_policy("p1", "good", [_amount_rule()]),
            _make_policy(
                "p2", "bad", [{"name": "r1", "conditions": []}]
            ),
            _make_policy(
                "p3", "good2",
                [_amount_rule("fail", "1000")],
            ),
        ]
        # Amount is 5000 — passes p1 (max 10000), triggers p3 (max 1000)
        context = EvaluationContext(
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            user_id="user-1",
            agent_id="agent-1",
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=policies, context=context,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 3
        assert result.invalid_count == 1
        assert result.triggered_count == 1
        assert result.pass_count == 1

    def test_null_rules_is_invalid(self) -> None:
        policy = {
            "id": "p1",
            "name": "no_rules",
            "version": 1,
            "status": "active",
            "rules": None,
            "scope": None,
        }
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 1
        assert result.invalid_count == 1


# ── Severity ──────────────────────────────────────────────────────


class TestSeverity:
    def test_highest_triggered_severity(self) -> None:
        policies = [
            _make_policy(
                "p1", "medium",
                [_amount_rule("r1", "1000", severity="medium")],
            ),
            _make_policy(
                "p2", "critical",
                [_amount_rule("r2", "1000", severity="critical")],
            ),
        ]
        context = EvaluationContext(
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            user_id="user-1",
            agent_id="agent-1",
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=policies, context=context,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.highest_severity == PolicySeverity.CRITICAL

    def test_no_trigger_means_none_severity(self) -> None:
        policy = _make_policy("p1", "ok", [_amount_rule()])
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.highest_severity == PolicySeverity.NONE


# ── Policy Versioning ─────────────────────────────────────────────


class TestPolicyVersioning:
    def test_version_preserved_in_result(self) -> None:
        policy = _make_policy(
            "p1", "versioned", [_amount_rule()], version=3
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.policy_results[0].policy_version == 3


# ── Scope Filtering ───────────────────────────────────────────────


class TestScopeFiltering:
    def test_scope_matches(self) -> None:
        policy = _make_policy(
            "p1", "scoped",
            [_amount_rule()],
            scope={"transaction_types": ["purchase"]},
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 1

    def test_scope_excludes(self) -> None:
        policy = _make_policy(
            "p1", "scoped",
            [_amount_rule()],
            scope={"transaction_types": ["transfer"]},
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0

    def test_agent_exclusion(self) -> None:
        policy = _make_policy(
            "p1", "agent_excluded",
            [_amount_rule()],
            scope={"exclude_agent_ids": ["agent-1"]},
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0

    def test_merchant_exclusion(self) -> None:
        policy = _make_policy(
            "p1", "merchant_excluded",
            [_amount_rule()],
            scope={"exclude_merchant_names": ["Amazon"]},
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.total_policies == 0


# ── Summary ───────────────────────────────────────────────────────


class TestSummary:
    def test_summary_text(self) -> None:
        policies = [
            _make_policy("p1", "ok", [_amount_rule()]),
            _make_policy(
                "p2", "fail", [_amount_rule("r", "1000")]
            ),
        ]
        context = EvaluationContext(
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            user_id="user-1",
            agent_id="agent-1",
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=policies, context=context,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert "triggered" in result.summary.lower()
        assert "passed" in result.summary.lower()


# ── Evaluation Metadata ──────────────────────────────────────────


class TestEvaluationMetadata:
    def test_evaluator_version(self) -> None:
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.evaluator_version == "policy-v1"

    def test_evaluation_id_generated(self) -> None:
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert len(result.evaluation_id) > 0

    def test_evaluated_at_populated(self) -> None:
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[], context=DEFAULT_CONTEXT,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert len(result.evaluated_at) > 0


# ── Drift Integration ─────────────────────────────────────────────


class TestDriftIntegration:
    def test_drift_policy_triggered(self) -> None:
        # Policy says: drift_overall_status must be "match" (no drift)
        # When drift IS detected → condition MISMATCHES → rule TRIGGERED
        drift_rule = {
            "name": "drift_check",
            "severity": "high",
            "category": "drift_threshold",
            "logic": "all",
            "conditions": [
                {
                    "field": "drift_overall_status",
                    "operator": "equals",
                    "value": "match",
                }
            ],
        }
        policy = _make_policy("p1", "drift_policy", [drift_rule])
        context = EvaluationContext(
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            drift_overall_status="drift_detected",
            user_id="user-1",
            agent_id="agent-1",
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=context,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.triggered_count == 1

    def test_drift_policy_passes(self) -> None:
        # Policy says: drift_overall_status must be "match" (no drift)
        # When drift is NOT detected → condition MATCHES → rule PASSES
        drift_rule = {
            "name": "drift_check",
            "severity": "high",
            "category": "drift_threshold",
            "logic": "all",
            "conditions": [
                {
                    "field": "drift_overall_status",
                    "operator": "equals",
                    "value": "match",
                }
            ],
        }
        policy = _make_policy("p1", "drift_policy", [drift_rule])
        context = EvaluationContext(
            proposal_amount=Decimal("5000"),
            proposal_currency="INR",
            proposal_transaction_type="purchase",
            drift_overall_status="match",
            user_id="user-1",
            agent_id="agent-1",
        )
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=[policy], context=context,
            intent_id="i1", proposal_intent_id="i1",
        )
        assert result.pass_count == 1
