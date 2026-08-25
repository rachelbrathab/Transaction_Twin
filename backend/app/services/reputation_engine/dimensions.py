"""Reputation Engine dimension scorers.

Each function takes a BehavioralContext and returns a DimensionScore.
All scorers are pure functions -- no I/O, no database, no side effects.
"""

from __future__ import annotations

from app.services.reputation_engine.constants import (
    DIMENSION_WEIGHTS,
)
from app.services.reputation_engine.features import (
    compute_account_age_days,
    compute_amount_outlier_ratio,
    compute_coefficient_of_variation,
    compute_consistency_confidence,
    compute_decision_confidence,
    compute_drift_rate,
    compute_success_rate,
    compute_transaction_confidence,
    compute_violation_rate,
    sigmoid,
)
from app.services.reputation_engine.models import (
    BehavioralContext,
    DimensionScore,
    ReputationDimension,
)


def score_success_rate(ctx: BehavioralContext) -> DimensionScore:
    """Score agent success rate from decision outcomes.

    Uses recent-weighted scoring: 60% recent, 40% historical.
    New agents with no history get neutral 0.5.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.SUCCESS_RATE]

    if ctx.total_decisions == 0:
        return DimensionScore(
            dimension=ReputationDimension.SUCCESS_RATE,
            score=0.5,
            weight=weight,
            weighted_contribution=round(0.5 * weight, 4),
            confidence=0.5,
            what="No decision history available",
            why="Cannot assess success rate -- no decisions recorded",
            evidence={"total_decisions": 0},
        )

    overall_rate, recent_rate = compute_success_rate(ctx)
    # Recent-weighted: 60% recent, 40% overall
    score = 0.6 * recent_rate + 0.4 * overall_rate
    score = round(max(0.0, min(1.0, score)), 4)

    confidence = compute_decision_confidence(ctx.total_decisions)

    recent_total = (
        ctx.recent_allow_count + ctx.recent_review_count + ctx.recent_block_count
    )

    return DimensionScore(
        dimension=ReputationDimension.SUCCESS_RATE,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=(
            f"Success rate: {overall_rate:.0%} overall "
            f"({ctx.allow_count}/{ctx.total_decisions}), "
            f"{recent_rate:.0%} recent ({ctx.recent_allow_count}/{recent_total})"
        ),
        why=(
            "Agent success rate measures how often transactions are "
            "allowed without review or block"
        ),
        evidence={
            "overall_rate": round(overall_rate, 4),
            "recent_rate": round(recent_rate, 4),
            "allow_count": ctx.allow_count,
            "review_count": ctx.review_count,
            "block_count": ctx.block_count,
            "total_decisions": ctx.total_decisions,
            "recent_allow_count": ctx.recent_allow_count,
            "recent_review_count": ctx.recent_review_count,
            "recent_block_count": ctx.recent_block_count,
        },
    )


def score_policy_compliance(ctx: BehavioralContext) -> DimensionScore:
    """Score agent policy compliance from violation history.

    Low violation rate = high score.
    Critical violations carry disproportionate penalty.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.POLICY_COMPLIANCE]

    if ctx.total_transactions == 0:
        return DimensionScore(
            dimension=ReputationDimension.POLICY_COMPLIANCE,
            score=0.5,
            weight=weight,
            weighted_contribution=round(0.5 * weight, 4),
            confidence=0.5,
            what="No transaction history available",
            why="Cannot assess policy compliance -- no transactions recorded",
            evidence={"total_transactions": 0},
        )

    violation_rate = compute_violation_rate(ctx)
    # Base score: 1.0 - (violation_rate * 5), clamped to [0, 1]
    score = max(0.0, 1.0 - min(violation_rate * 5, 1.0))

    # Critical violations penalize heavily
    if ctx.critical_violations > 0:
        score = max(0.0, score - 0.15 * min(ctx.critical_violations, 3))

    # Recent violations penalize
    if ctx.recent_policy_violations > 0:
        score = max(0.0, score - 0.10 * min(ctx.recent_policy_violations, 5))

    score = round(max(0.0, min(1.0, score)), 4)
    confidence = compute_transaction_confidence(ctx.total_transactions)

    return DimensionScore(
        dimension=ReputationDimension.POLICY_COMPLIANCE,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=(
            f"Policy compliance: {ctx.total_policy_violations} violations "
            f"in {ctx.total_transactions} transactions "
            f"({violation_rate:.1%} rate)"
        ),
        why=(
            "Policy compliance measures how well the agent adheres to "
            "explicit transaction policies"
        ),
        evidence={
            "violation_rate": round(violation_rate, 4),
            "total_policy_violations": ctx.total_policy_violations,
            "recent_policy_violations": ctx.recent_policy_violations,
            "critical_violations": ctx.critical_violations,
            "high_violations": ctx.high_violations,
            "total_transactions": ctx.total_transactions,
        },
    )


def score_drift_behavior(ctx: BehavioralContext) -> DimensionScore:
    """Score agent drift behavior from drift event history.

    Low drift rate = high score.
    Critical drift events carry disproportionate penalty.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.DRIFT_BEHAVIOR]

    if ctx.total_transactions == 0:
        return DimensionScore(
            dimension=ReputationDimension.DRIFT_BEHAVIOR,
            score=0.5,
            weight=weight,
            weighted_contribution=round(0.5 * weight, 4),
            confidence=0.5,
            what="No transaction history available",
            why="Cannot assess drift behavior -- no transactions recorded",
            evidence={"total_transactions": 0},
        )

    drift_rate = compute_drift_rate(ctx)
    # Base score: 1.0 - (drift_rate * 3), clamped to [0, 1]
    score = max(0.0, 1.0 - min(drift_rate * 3, 1.0))

    # Critical drift penalized heavily
    if ctx.critical_drift_count > 0:
        score = max(0.0, score - 0.20 * min(ctx.critical_drift_count, 3))

    score = round(max(0.0, min(1.0, score)), 4)
    confidence = compute_transaction_confidence(ctx.total_transactions)

    return DimensionScore(
        dimension=ReputationDimension.DRIFT_BEHAVIOR,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=(
            f"Drift behavior: {ctx.total_drift_events} drift events "
            f"in {ctx.total_transactions} transactions ({drift_rate:.1%} rate)"
        ),
        why=(
            "Drift behavior measures how often the agent proposes "
            "transactions that deviate from authorized intent"
        ),
        evidence={
            "drift_rate": round(drift_rate, 4),
            "total_drift_events": ctx.total_drift_events,
            "critical_drift_count": ctx.critical_drift_count,
            "high_drift_count": ctx.high_drift_count,
            "total_transactions": ctx.total_transactions,
        },
    )


def score_risk_profile(ctx: BehavioralContext) -> DimensionScore:
    """Score agent risk profile from risk assessment history.

    Low risk scores = high reputation.
    Unknown risk = neutral with reduced confidence.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.RISK_PROFILE]

    if ctx.average_risk_score is None:
        return DimensionScore(
            dimension=ReputationDimension.RISK_PROFILE,
            score=0.5,
            weight=weight,
            weighted_contribution=round(0.5 * weight, 4),
            confidence=0.3 if not ctx.risk_history_available else 0.5,
            what="No risk assessment history available",
            why="Cannot assess risk profile -- no risk scores recorded",
            evidence={"risk_history_available": ctx.risk_history_available},
        )

    # Invert risk: low risk -> high reputation
    score = 1.0 - ctx.average_risk_score

    # Max risk spike penalizes
    if ctx.max_risk_score is not None and ctx.max_risk_score > 0.75:
        score = max(0.0, score - 0.15)

    # Critical risk events
    if ctx.critical_risk_count > 0:
        score = max(0.0, score - 0.10 * min(ctx.critical_risk_count, 3))

    score = round(max(0.0, min(1.0, score)), 4)
    confidence = 0.8 if ctx.risk_history_available else 0.4

    return DimensionScore(
        dimension=ReputationDimension.RISK_PROFILE,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=(
            f"Risk profile: average risk score {ctx.average_risk_score:.2f}, "
            f"max {ctx.max_risk_score:.2f}" if ctx.max_risk_score is not None
            else f"Risk profile: average risk score {ctx.average_risk_score:.2f}"
        ),
        why=(
            "Risk profile measures the agent's historical risk assessment pattern"
        ),
        evidence={
            "average_risk_score": ctx.average_risk_score,
            "max_risk_score": ctx.max_risk_score,
            "critical_risk_count": ctx.critical_risk_count,
            "risk_history_available": ctx.risk_history_available,
        },
    )


def score_consistency(ctx: BehavioralContext) -> DimensionScore:
    """Score agent consistency from amount variation.

    Low coefficient of variation = high consistency.
    Unknown variation = neutral.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.CONSISTENCY]

    cv = compute_coefficient_of_variation(ctx)
    if cv is None or ctx.total_transactions < 3:
        return DimensionScore(
            dimension=ReputationDimension.CONSISTENCY,
            score=0.5,
            weight=weight,
            weighted_contribution=round(0.5 * weight, 4),
            confidence=0.3,
            what="Insufficient data for consistency analysis",
            why="Cannot assess consistency -- need at least 3 transactions with amount data",
            evidence={
                "total_transactions": ctx.total_transactions,
                "amount_stddev": ctx.amount_stddev,
                "average_transaction_amount": ctx.average_transaction_amount,
            },
        )

    # Low variation = high consistency
    score = max(0.0, 1.0 - min(cv / 2.0, 1.0))
    score = round(max(0.0, min(1.0, score)), 4)
    confidence = compute_consistency_confidence(ctx.total_transactions)

    return DimensionScore(
        dimension=ReputationDimension.CONSISTENCY,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=f"Amount coefficient of variation: {cv:.2f}",
        why=(
            "Consistency measures how stable the agent's transaction amounts are"
        ),
        evidence={
            "coefficient_of_variation": round(cv, 4),
            "amount_stddev": ctx.amount_stddev,
            "average_transaction_amount": ctx.average_transaction_amount,
            "total_transactions": ctx.total_transactions,
        },
    )


def score_longevity(ctx: BehavioralContext) -> DimensionScore:
    """Score agent longevity from account age.

    Uses a sigmoid curve: full score around 180 days.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.LONGEVITY]

    age_days = compute_account_age_days(ctx)
    if age_days is None:
        return DimensionScore(
            dimension=ReputationDimension.LONGEVITY,
            score=0.3,
            weight=weight,
            weighted_contribution=round(0.3 * weight, 4),
            confidence=0.3,
            what="Account age is unknown",
            why="Cannot assess longevity -- account age not available",
            evidence={},
        )

    # Sigmoid: center at 60 days, steepness 0.02
    score = sigmoid(0.02 * (age_days - 60))
    score = round(max(0.0, min(1.0, score)), 4)
    confidence = 0.9

    return DimensionScore(
        dimension=ReputationDimension.LONGEVITY,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=f"Account age: {age_days} days",
        why=(
            "Longevity measures how established the agent is -- "
            "older accounts have more observable history"
        ),
        evidence={
            "account_age_days": age_days,
            "first_transaction_at": ctx.first_transaction_at,
        },
    )


def score_amount_behavior(ctx: BehavioralContext) -> DimensionScore:
    """Score agent amount behavior from outlier patterns.

    Normal max/avg ratio = high score.
    Extreme outliers = low score.
    """
    weight = DIMENSION_WEIGHTS[ReputationDimension.AMOUNT_BEHAVIOR]

    ratio = compute_amount_outlier_ratio(ctx)
    if ratio is None or ctx.total_transactions < 3:
        return DimensionScore(
            dimension=ReputationDimension.AMOUNT_BEHAVIOR,
            score=0.5,
            weight=weight,
            weighted_contribution=round(0.5 * weight, 4),
            confidence=0.3,
            what="Insufficient data for amount behavior analysis",
            why="Cannot assess amount behavior -- need at least 3 transactions",
            evidence={
                "total_transactions": ctx.total_transactions,
                "max_transaction_amount": ctx.max_transaction_amount,
                "average_transaction_amount": ctx.average_transaction_amount,
            },
        )

    # Ratio > 3.0 starts penalizing, capped at 13.0 (ratio=13 -> score 0.0)
    score = max(0.0, 1.0 - min((ratio - 3.0) / 10.0, 1.0))
    score = round(max(0.0, min(1.0, score)), 4)
    confidence = compute_transaction_confidence(ctx.total_transactions)

    return DimensionScore(
        dimension=ReputationDimension.AMOUNT_BEHAVIOR,
        score=score,
        weight=weight,
        weighted_contribution=round(score * weight, 4),
        confidence=confidence,
        what=(
            f"Max/avg amount ratio: {ratio:.1f}x "
            f"(max: {ctx.max_transaction_amount}, "
            f"avg: {ctx.average_transaction_amount:.2f})"
        ),
        why=(
            "Amount behavior measures whether the agent's transaction "
            "amounts are consistent or contain extreme outliers"
        ),
        evidence={
            "max_avg_ratio": round(ratio, 4),
            "max_transaction_amount": ctx.max_transaction_amount,
            "average_transaction_amount": ctx.average_transaction_amount,
            "total_transactions": ctx.total_transactions,
        },
    )
