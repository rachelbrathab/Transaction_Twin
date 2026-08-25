"""Rule Evaluator — evaluates a single policy rule using AND/OR logic.

Implements the approved UNKNOWN semantics:

ALL (AND):
  ANY MISMATCH → TRIGGERED
  ELSE ANY UNKNOWN → UNKNOWN
  ELSE → PASS

ANY (OR):
  ANY MATCH → PASS
  ELSE ANY UNKNOWN → UNKNOWN
  ELSE → TRIGGERED
"""

from __future__ import annotations

from app.services.policy_engine.conditions import evaluate_condition
from app.services.policy_engine.models import (
    ConditionResult,
    ConditionStatus,
    EvaluationContext,
    LogicOperator,
    PolicyEvaluationStatus,
    PolicyRule,
    RuleResult,
)


def evaluate_rule(
    rule: PolicyRule,
    context: EvaluationContext,
) -> RuleResult:
    """Evaluate a single rule against the evaluation context.

    Returns RuleResult with status PASS, TRIGGERED, or UNKNOWN.
    """
    condition_results: list[ConditionResult] = []

    for condition in rule.conditions:
        result = evaluate_condition(condition, context)
        condition_results.append(result)

    # Determine rule status based on logic operator
    if rule.logic == LogicOperator.ALL:
        status = _evaluate_all(condition_results)
    else:
        status = _evaluate_any(condition_results)

    # Generate explanation
    explanation = _generate_rule_explanation(rule.name, status, condition_results)

    return RuleResult(
        name=rule.name,
        description=rule.description,
        category=rule.category.value,
        severity=rule.severity,
        status=status,
        condition_results=condition_results,
        explanation=explanation,
    )


def _evaluate_all(condition_results: list[ConditionResult]) -> PolicyEvaluationStatus:
    """Evaluate ALL (AND) logic.

    ANY MISMATCH → TRIGGERED
    ELSE ANY UNKNOWN → UNKNOWN
    ELSE → PASS
    """
    has_mismatch = False
    has_unknown = False

    for cr in condition_results:
        if cr.status == ConditionStatus.MISMATCH:
            has_mismatch = True
            break  # Can short-circuit: already TRIGGERED
        elif cr.status == ConditionStatus.UNKNOWN:
            has_unknown = True

    if has_mismatch:
        return PolicyEvaluationStatus.TRIGGERED
    if has_unknown:
        return PolicyEvaluationStatus.UNKNOWN
    return PolicyEvaluationStatus.PASS


def _evaluate_any(condition_results: list[ConditionResult]) -> PolicyEvaluationStatus:
    """Evaluate ANY (OR) logic.

    ANY MATCH → PASS
    ELSE ANY UNKNOWN → UNKNOWN
    ELSE → TRIGGERED
    """
    has_match = False
    has_unknown = False

    for cr in condition_results:
        if cr.status == ConditionStatus.MATCH:
            has_match = True
            break  # Can short-circuit: already PASS
        elif cr.status == ConditionStatus.UNKNOWN:
            has_unknown = True

    if has_match:
        return PolicyEvaluationStatus.PASS
    if has_unknown:
        return PolicyEvaluationStatus.UNKNOWN
    return PolicyEvaluationStatus.TRIGGERED


def _generate_rule_explanation(
    rule_name: str,
    status: PolicyEvaluationStatus,
    condition_results: list[ConditionResult],
) -> str:
    """Generate a human-readable explanation for the rule evaluation."""
    if status == PolicyEvaluationStatus.PASS:
        matched = [cr for cr in condition_results if cr.status == ConditionStatus.MATCH]
        if matched:
            return f"Rule '{rule_name}' passed: {matched[0].explanation}"
        return f"Rule '{rule_name}' passed all conditions"

    if status == PolicyEvaluationStatus.TRIGGERED:
        mismatched = [cr for cr in condition_results if cr.status == ConditionStatus.MISMATCH]
        if mismatched:
            parts = [cr.explanation for cr in mismatched]
            return f"Rule '{rule_name}' triggered: {'; '.join(parts)}"
        return f"Rule '{rule_name}' triggered"

    # UNKNOWN
    unknown = [cr for cr in condition_results if cr.status == ConditionStatus.UNKNOWN]
    if unknown:
        fields = [cr.field for cr in unknown]
        return f"Rule '{rule_name}' unknown: fields [{', '.join(fields)}] have no data"
    return f"Rule '{rule_name}' could not be fully evaluated"
