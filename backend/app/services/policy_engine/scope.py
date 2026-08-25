"""Policy Scope Matcher — determines whether a policy applies to a transaction.

A policy with no scope applies to all transactions for that user.
Scope matching is deterministic and uses inclusion/exclusion lists.
"""

from __future__ import annotations

from app.services.policy_engine.models import EvaluationContext, PolicyScope


def is_policy_applicable(
    scope: PolicyScope | None,
    context: EvaluationContext,
) -> bool:
    """Determine whether a policy applies to the given evaluation context.

    Returns True if the policy should be evaluated.
    A None scope means the policy applies to all transactions.
    """
    if scope is None:
        return True

    # Check exclusions first — if excluded, policy does not apply
    if not _check_exclusions(scope, context):
        return False

    # Check inclusions — if scope has filters, context must match at least one
    return _check_inclusions(scope, context)


def _check_exclusions(scope: PolicyScope, context: EvaluationContext) -> bool:
    """Check if the context triggers any exclusion rule.

    Returns True if NOT excluded (policy still applies).
    """
    if scope.exclude_agent_ids and context.agent_id:
        if context.agent_id in scope.exclude_agent_ids:
            return False

    if scope.exclude_merchant_names and context.proposal_merchant_name:
        if context.proposal_merchant_name in scope.exclude_merchant_names:
            return False

    return True


def _check_inclusions(scope: PolicyScope, context: EvaluationContext) -> bool:
    """Check if the context matches inclusion filters.

    If a scope list is non-empty, the context must match at least that filter.
    An empty/None scope list means no filter on that dimension.
    """
    # Transaction type
    if scope.transaction_types is not None and context.proposal_transaction_type:
        if context.proposal_transaction_type not in scope.transaction_types:
            return False

    # Agent IDs
    if scope.agent_ids is not None and context.agent_id:
        if context.agent_id not in scope.agent_ids:
            return False

    # Categories
    if scope.categories is not None and context.proposal_category:
        if context.proposal_category not in scope.categories:
            return False

    # Countries
    if scope.countries is not None and context.proposal_country:
        if context.proposal_country not in scope.countries:
            return False

    # Currencies
    if scope.currencies is not None and context.proposal_currency:
        if context.proposal_currency not in scope.currencies:
            return False

    # Merchant names
    if scope.merchant_names is not None and context.proposal_merchant_name:
        if context.proposal_merchant_name not in scope.merchant_names:
            return False

    return True
