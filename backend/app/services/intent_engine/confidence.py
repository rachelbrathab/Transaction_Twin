"""Confidence calculation — deterministic post-hard-gate scoring.

Confidence is calculated ONLY after all hard gates pass.
Schema validity is NOT a confidence signal — it is a binary gate.

Formula:
    signal_sum = (
        extraction_completeness * 0.25 +
        amount_clarity * 0.15 +
        category_clarity * 0.15 +
        currency_clarity * 0.10 +
        normalization_quality * 0.10 +
        constraint_consistency * 0.10
    ) / 0.85

    ambiguity_multiplier = 1.0 - (
        missing_required * 0.25 +
        missing_recommended * 0.10 +
        missing_optional * 0.02
    )

    confidence = clamp(signal_sum * ambiguity_multiplier, 0.0, 1.0)

Deterministic fallback: maximum confidence = 0.70.
"""

from __future__ import annotations

from app.services.intent_engine.models import (
    Ambiguity,
    AmbiguitySeverity,
    StructuredIntent,
)

# Signal weights (must sum to 0.85 before normalization)
_WEIGHT_EXTRACTION_COMPLETENESS = 0.25
_WEIGHT_AMOUNT_CLARITY = 0.15
_WEIGHT_CATEGORY_CLARITY = 0.15
_WEIGHT_CURRENCY_CLARITY = 0.10
_WEIGHT_NORMALIZATION_QUALITY = 0.10
_WEIGHT_CONSTRAINT_CONSISTENCY = 0.10
_WEIGHT_SUM = (
    _WEIGHT_EXTRACTION_COMPLETENESS
    + _WEIGHT_AMOUNT_CLARITY
    + _WEIGHT_CATEGORY_CLARITY
    + _WEIGHT_CURRENCY_CLARITY
    + _WEIGHT_NORMALIZATION_QUALITY
    + _WEIGHT_CONSTRAINT_CONSISTENCY
)

# Ambiguity penalties
_PENALTY_REQUIRED = 0.25
_PENALTY_RECOMMENDED = 0.10
_PENALTY_OPTIONAL = 0.02

# Deterministic fallback confidence cap
DETERMINISTIC_CONFIDENCE_CAP = 0.70


def _extraction_completeness(intent: StructuredIntent) -> float:
    """How many fields were populated (0.0 to 1.0)."""
    fields = [
        (intent.amount.min is not None or intent.amount.max is not None
         or intent.amount.exact is not None),
        intent.category_constraints.items != [],
        intent.merchant_constraints.trust_required
        or bool(intent.merchant_constraints.preferred)
        or bool(intent.merchant_constraints.excluded),
        intent.geographic_constraints.country is not None
        or intent.geographic_constraints.city is not None,
        intent.temporal_constraints.deadline is not None
        or intent.temporal_constraints.duration is not None,
        intent.authorization_scope.value is not None,
    ]
    return sum(fields) / len(fields)


def _amount_clarity(intent: StructuredIntent) -> float:
    """Amount extraction clarity."""
    amt = intent.amount
    if amt.exact is not None:
        return 1.0
    if amt.min is not None and amt.max is not None:
        return 0.9
    if amt.max is not None:
        return 0.8
    if amt.min is not None:
        return 0.7
    return 0.0


def _category_clarity(intent: StructuredIntent) -> float:
    """Category extraction clarity."""
    cat = intent.category_constraints
    if cat.items and cat.attributes:
        return 1.0
    if cat.items:
        return 0.7
    return 0.0


def _currency_clarity(intent: StructuredIntent) -> float:
    """Currency extraction clarity."""
    if intent.currency.source.value == "explicit":
        return 1.0
    if intent.currency.source.value in ("user_default", "app_default"):
        return 0.8
    return 0.0


def _normalization_quality(intent: StructuredIntent) -> float:
    """How cleanly the NL mapped to structured fields.

    Heuristic based on evidence confidence averages.
    """
    evidences = [
        intent.amount.evidence,
        intent.category_constraints.evidence,
        intent.merchant_constraints.evidence,
    ]
    confidences = [e.confidence for e in evidences if e is not None]
    if not confidences:
        return 0.5
    return sum(confidences) / len(confidences)


def _constraint_consistency(intent: StructuredIntent) -> float:
    """How consistent the constraints are (0.0 to 1.0)."""
    score = 1.0

    # Amount consistency
    amt = intent.amount
    if amt.min is not None and amt.max is not None and amt.min > amt.max:
        score -= 0.4

    # Goal/type consistency
    if intent.goal.value != intent.transaction_type.value:
        score -= 0.2

    return max(0.0, score)


def calculate_confidence(
    intent: StructuredIntent,
    ambiguities: list[Ambiguity],
    was_modified: bool = False,
    is_deterministic: bool = False,
) -> float:
    """Calculate deterministic confidence score.

    Args:
        intent: The validated structured intent.
        ambiguities: Detected ambiguities.
        was_modified: Whether normalization changed the request.
        is_deterministic: Whether the deterministic fallback was used.
    """
    # Signal scores
    s_extraction = _extraction_completeness(intent)
    s_amount = _amount_clarity(intent)
    s_category = _category_clarity(intent)
    s_currency = _currency_clarity(intent)
    s_normalization = _normalization_quality(intent)
    s_consistency = _constraint_consistency(intent)

    # Normalize signals to 0-1 range
    signal_sum = (
        s_extraction * _WEIGHT_EXTRACTION_COMPLETENESS
        + s_amount * _WEIGHT_AMOUNT_CLARITY
        + s_category * _WEIGHT_CATEGORY_CLARITY
        + s_currency * _WEIGHT_CURRENCY_CLARITY
        + s_normalization * _WEIGHT_NORMALIZATION_QUALITY
        + s_consistency * _WEIGHT_CONSTRAINT_CONSISTENCY
    ) / _WEIGHT_SUM

    # Ambiguity multiplier
    missing_required = sum(
        1 for a in ambiguities if a.severity == AmbiguitySeverity.REQUIRED
    )
    missing_recommended = sum(
        1 for a in ambiguities if a.severity == AmbiguitySeverity.RECOMMENDED
    )
    missing_optional = sum(
        1 for a in ambiguities if a.severity == AmbiguitySeverity.OPTIONAL
    )

    ambiguity_multiplier = max(
        0.0,
        1.0
        - (
            missing_required * _PENALTY_REQUIRED
            + missing_recommended * _PENALTY_RECOMMENDED
            + missing_optional * _PENALTY_OPTIONAL
        ),
    )

    # Final confidence
    confidence = signal_sum * ambiguity_multiplier

    # Apply normalization penalty
    if was_modified:
        confidence *= 0.95

    # Clamp
    confidence = max(0.0, min(1.0, confidence))

    # Deterministic cap
    if is_deterministic:
        confidence = min(confidence, DETERMINISTIC_CONFIDENCE_CAP)

    return round(confidence, 2)
