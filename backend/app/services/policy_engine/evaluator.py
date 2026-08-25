"""Policy Evaluator — main orchestrator for policy evaluation.

Validates policy structure, checks scope applicability, evaluates rules,
and produces per-policy results. Deterministic — no DB/HTTP/LLM dependencies.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.services.policy_engine.models import (
    EvaluationContext,
    PolicyEvaluationResult,
    PolicyEvaluationStatus,
    PolicyResult,
    PolicySeverity,
)
from app.services.policy_engine.rules import evaluate_rule
from app.services.policy_engine.scope import is_policy_applicable
from app.services.policy_engine.validators import validate_policy_structure

logger = structlog.get_logger()

# Severity ordering for max computation
_SEVERITY_ORDER: list[PolicySeverity] = [
    PolicySeverity.NONE,
    PolicySeverity.LOW,
    PolicySeverity.MEDIUM,
    PolicySeverity.HIGH,
    PolicySeverity.CRITICAL,
]


def _max_severity(a: PolicySeverity, b: PolicySeverity) -> PolicySeverity:
    """Return the higher of two severities."""
    idx_a = _SEVERITY_ORDER.index(a)
    idx_b = _SEVERITY_ORDER.index(b)
    return a if idx_a >= idx_b else b


class PolicyEvaluator:
    """Core policy evaluator. No database, no HTTP, no LLM dependencies.

    Usage:
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(
            policies=policy_list,
            context=evaluation_context,
            intent_id="...",
            proposal_intent_id="...",
        )
    """

    def evaluate(
        self,
        policies: list[dict[str, Any]],
        context: EvaluationContext,
        *,
        intent_id: str,
        proposal_intent_id: str,
    ) -> PolicyEvaluationResult:
        """Evaluate all applicable policies against the context.

        Args:
            policies: List of raw policy dicts from the database.
                Each must have: id, name, version, status, rules, scope,
                effective_from, effective_until.
            context: Flat EvaluationContext built from intent + proposal + drift.
            intent_id: The intent being evaluated against.
            proposal_intent_id: Must match intent_id.

        Returns:
            PolicyEvaluationResult with per-policy results.
        """
        start_time = time.monotonic()
        evaluation_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC)

        log = logger.bind(
            evaluation_id=evaluation_id,
            intent_id=intent_id,
            user_id=context.user_id,
            agent_id=context.agent_id,
        )

        policy_results: list[PolicyResult] = []
        triggered_count = 0
        unknown_count = 0
        invalid_count = 0
        pass_count = 0
        highest_severity = PolicySeverity.NONE

        for policy in policies:
            # Lifecycle check — only evaluate active, non-expired policies
            status_str = policy.get("status", "draft")
            if status_str != "active":
                continue

            effective_from = policy.get("effective_from")
            effective_until = policy.get("effective_until")

            if effective_from is not None:
                if isinstance(effective_from, str):
                    try:
                        effective_from = datetime.fromisoformat(effective_from)
                    except ValueError:
                        continue
                if effective_from > now:
                    continue

            if effective_until is not None:
                if isinstance(effective_until, str):
                    try:
                        effective_until = datetime.fromisoformat(effective_until)
                    except ValueError:
                        continue
                if effective_until < now:
                    continue

            policy_result = self._evaluate_single_policy(policy, context)

            # Skip non-applicable policies
            if policy_result is None:
                continue

            # Count results
            if policy_result.status == PolicyEvaluationStatus.TRIGGERED:
                triggered_count += 1
            elif policy_result.status == PolicyEvaluationStatus.UNKNOWN:
                unknown_count += 1
            elif policy_result.status == PolicyEvaluationStatus.INVALID_POLICY:
                invalid_count += 1
            else:
                pass_count += 1

            # Track highest severity among triggered rules
            if policy_result.highest_triggered_severity != PolicySeverity.NONE:
                highest_severity = _max_severity(
                    highest_severity, policy_result.highest_triggered_severity
                )

            policy_results.append(policy_result)

        # Build summary
        summary = self._generate_summary(
            triggered_count, unknown_count, invalid_count, pass_count
        )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "policy_evaluation_completed",
            policy_count=len(policy_results),
            triggered_count=triggered_count,
            unknown_count=unknown_count,
            invalid_count=invalid_count,
            latency_ms=latency_ms,
            evaluator_version="policy-v1",
        )

        if triggered_count > 0:
            log.warning(
                "policy_triggered",
                triggered_policy_ids=[
                    pr.policy_id
                    for pr in policy_results
                    if pr.status == PolicyEvaluationStatus.TRIGGERED
                ],
            )

        if invalid_count > 0:
            log.warning(
                "invalid_policy_skipped",
                invalid_policy_ids=[
                    pr.policy_id
                    for pr in policy_results
                    if pr.status == PolicyEvaluationStatus.INVALID_POLICY
                ],
            )

        return PolicyEvaluationResult(
            intent_id=intent_id,
            proposal_intent_id=proposal_intent_id,
            evaluation_id=evaluation_id,
            policy_results=policy_results,
            total_policies=len(policy_results),
            triggered_count=triggered_count,
            unknown_count=unknown_count,
            invalid_count=invalid_count,
            pass_count=pass_count,
            highest_severity=highest_severity,
            summary=summary,
            evaluated_at=now.isoformat(),
            evaluator_version="policy-v1",
        )

    def _evaluate_single_policy(
        self,
        policy: dict[str, Any],
        context: EvaluationContext,
    ) -> PolicyResult:
        """Evaluate a single policy. Handles validation, scope, and rule evaluation."""
        policy_id = str(policy.get("id", "unknown"))
        policy_name = policy.get("name", "unknown")
        policy_version = int(policy.get("version", 1))
        now = datetime.now(UTC).isoformat()

        # Step 1: Validate policy structure
        rules_raw = policy.get("rules")
        scope_raw = policy.get("scope")

        validation = validate_policy_structure(rules_raw, scope_raw)
        if not validation.valid:
            return PolicyResult(
                policy_id=policy_id,
                policy_version=policy_version,
                policy_name=policy_name,
                status=PolicyEvaluationStatus.INVALID_POLICY,
                explanation=f"Policy validation failed: {'; '.join(validation.errors)}",
                evaluated_at=now,
            )

        # Step 2: Check scope applicability
        try:
            from app.services.policy_engine.models import PolicyScope
            scope = PolicyScope(**scope_raw) if scope_raw else None
        except Exception:
            scope = None

        if not is_policy_applicable(scope, context):
            # Policy doesn't apply — skip entirely
            return None

        # Step 3: Evaluate rules
        from app.services.policy_engine.models import PolicyRuleSet
        rule_set = PolicyRuleSet(**rules_raw)

        rule_results = []
        triggered_count = 0
        unknown_count = 0
        matched_count = 0
        highest_triggered_severity = PolicySeverity.NONE

        for rule in rule_set.rules:
            rule_result = evaluate_rule(rule, context)
            rule_results.append(rule_result)

            if rule_result.status == PolicyEvaluationStatus.TRIGGERED:
                triggered_count += 1
                highest_triggered_severity = _max_severity(
                    highest_triggered_severity, rule_result.severity
                )
            elif rule_result.status == PolicyEvaluationStatus.UNKNOWN:
                unknown_count += 1
            elif rule_result.status == PolicyEvaluationStatus.PASS:
                matched_count += 1

        # Step 4: Determine policy-level status
        if triggered_count > 0:
            policy_status = PolicyEvaluationStatus.TRIGGERED
        elif unknown_count > 0:
            policy_status = PolicyEvaluationStatus.UNKNOWN
        else:
            policy_status = PolicyEvaluationStatus.PASS

        # Generate policy-level explanation
        explanation = self._generate_policy_explanation(
            policy_name, policy_status, rule_results
        )

        return PolicyResult(
            policy_id=policy_id,
            policy_version=policy_version,
            policy_name=policy_name,
            status=policy_status,
            rule_results=rule_results,
            matched_rule_count=matched_count,
            triggered_rule_count=triggered_count,
            unknown_rule_count=unknown_count,
            highest_triggered_severity=highest_triggered_severity,
            explanation=explanation,
            evaluated_at=now,
            evaluator_version="policy-v1",
        )

    def _generate_policy_explanation(
        self,
        policy_name: str,
        status: PolicyEvaluationStatus,
        rule_results: list[Any],
    ) -> str:
        """Generate human-readable explanation for a policy."""
        if status == PolicyEvaluationStatus.TRIGGERED:
            triggered = [r for r in rule_results if r.status == PolicyEvaluationStatus.TRIGGERED]
            parts = [r.explanation for r in triggered]
            return f"Policy '{policy_name}' triggered: {'; '.join(parts)}"

        if status == PolicyEvaluationStatus.UNKNOWN:
            unknown = [r for r in rule_results if r.status == PolicyEvaluationStatus.UNKNOWN]
            parts = [r.explanation for r in unknown]
            return f"Policy '{policy_name}' unknown: {'; '.join(parts)}"

        return f"Policy '{policy_name}' passed all rules"

    def _generate_summary(
        self,
        triggered: int,
        unknown: int,
        invalid: int,
        passed: int,
    ) -> str:
        """Generate overall summary for the evaluation."""
        parts = []
        if triggered > 0:
            parts.append(f"{triggered} policy triggered")
        if unknown > 0:
            parts.append(f"{unknown} policy unknown")
        if invalid > 0:
            parts.append(f"{invalid} invalid policy skipped")
        if passed > 0:
            parts.append(f"{passed} policy passed")
        if not parts:
            return "No policies evaluated"
        return "; ".join(parts)
