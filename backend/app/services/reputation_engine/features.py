"""Reputation Engine feature extraction helpers.

Pure functions that compute derived features from BehavioralContext.
No I/O. No database. No side effects.
"""

from __future__ import annotations

import math

from app.services.reputation_engine.models import BehavioralContext


def compute_success_rate(ctx: BehavioralContext) -> tuple[float, float]:
    """Compute overall and recent success rates.

    Returns (overall_rate, recent_rate).
    Returns (0.5, 0.5) when no decision history exists.
    """
    if ctx.total_decisions == 0:
        return 0.5, 0.5

    overall = ctx.allow_count / ctx.total_decisions

    recent_total = (
        ctx.recent_allow_count + ctx.recent_review_count + ctx.recent_block_count
    )
    recent = ctx.recent_allow_count / recent_total if recent_total > 0 else overall

    return overall, recent


def compute_violation_rate(ctx: BehavioralContext) -> float:
    """Compute policy violation rate per transaction.

    Returns 0.0 when no transactions exist.
    """
    if ctx.total_transactions == 0:
        return 0.0
    return ctx.total_policy_violations / ctx.total_transactions


def compute_drift_rate(ctx: BehavioralContext) -> float:
    """Compute drift event rate per transaction.

    Returns 0.0 when no transactions exist.
    """
    if ctx.total_transactions == 0:
        return 0.0
    return ctx.total_drift_events / ctx.total_transactions


def compute_coefficient_of_variation(ctx: BehavioralContext) -> float | None:
    """Compute coefficient of variation for transaction amounts.

    Returns None when insufficient data.
    """
    if (
        ctx.amount_stddev is None
        or ctx.average_transaction_amount is None
        or ctx.average_transaction_amount <= 0
    ):
        return None
    return ctx.amount_stddev / ctx.average_transaction_amount


def compute_amount_outlier_ratio(ctx: BehavioralContext) -> float | None:
    """Compute ratio of max transaction to average.

    Returns None when insufficient data.
    """
    if (
        ctx.max_transaction_amount is None
        or ctx.average_transaction_amount is None
        or ctx.average_transaction_amount <= 0
    ):
        return None
    return ctx.max_transaction_amount / ctx.average_transaction_amount


def compute_account_age_days(ctx: BehavioralContext) -> int | None:
    """Return account age in days from context, or None."""
    return ctx.account_age_days


def sigmoid(x: float) -> float:
    """Standard sigmoid function for longevity scoring."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def compute_decision_confidence(total_decisions: int) -> float:
    """Compute confidence based on number of decisions.

    Full confidence at 20+ decisions.
    """
    return min(1.0, total_decisions / 20.0)


def compute_transaction_confidence(total_transactions: int) -> float:
    """Compute confidence based on number of transactions.

    Full confidence at 10+ transactions.
    """
    return min(1.0, total_transactions / 10.0)


def compute_consistency_confidence(total_transactions: int) -> float:
    """Compute confidence for consistency dimension.

    Full confidence at 15+ transactions.
    """
    return min(1.0, total_transactions / 15.0)
