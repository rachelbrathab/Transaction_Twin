"""Ambiguity detection — identifies missing required/recommended/optional fields."""

from __future__ import annotations

from app.services.intent_engine.models import (
    Ambiguity,
    AmbiguitySeverity,
    StructuredIntent,
)

# Per-transaction-type required field definitions
_REQUIRED_FIELDS: dict[str, dict[str, list[str]]] = {
    "purchase": {
        "required": ["category_constraints"],
        "recommended": ["amount"],
        "optional": ["merchant_constraints", "geographic_constraints", "temporal_constraints"],
    },
    "booking": {
        "required": ["category_constraints", "geographic_constraints"],
        "recommended": ["amount", "temporal_constraints"],
        "optional": ["merchant_constraints"],
    },
    "refund": {
        "required": ["category_constraints"],
        "recommended": ["amount"],
        "optional": [],
    },
    "subscription": {
        "required": ["category_constraints", "temporal_constraints"],
        "recommended": ["amount", "merchant_constraints"],
        "optional": ["geographic_constraints"],
    },
    "transfer": {
        "required": ["category_constraints"],
        "recommended": ["amount"],
        "optional": ["geographic_constraints"],
    },
}

# Human-readable field names
_FIELD_LABELS: dict[str, str] = {
    "category_constraints": "category or product description",
    "amount": "budget or amount range",
    "merchant_constraints": "merchant preference",
    "geographic_constraints": "location",
    "temporal_constraints": "timing or dates",
    "currency": "currency",
}


def _is_field_present(intent: StructuredIntent, field: str) -> bool:
    """Check if a constraint field has meaningful content."""
    if field == "category_constraints":
        return bool(intent.category_constraints.items)
    if field == "amount":
        return (
            intent.amount.min is not None
            or intent.amount.max is not None
            or intent.amount.exact is not None
        )
    if field == "merchant_constraints":
        return (
            intent.merchant_constraints.trust_required
            or bool(intent.merchant_constraints.preferred)
            or bool(intent.merchant_constraints.excluded)
        )
    if field == "geographic_constraints":
        return (
            intent.geographic_constraints.country is not None
            or intent.geographic_constraints.city is not None
            or intent.geographic_constraints.radius_km is not None
        )
    if field == "temporal_constraints":
        return (
            intent.temporal_constraints.deadline is not None
            or intent.temporal_constraints.duration is not None
            or intent.temporal_constraints.recurring
        )
    if field == "currency":
        return intent.currency.code is not None
    return False


def detect_ambiguities(intent: StructuredIntent) -> list[Ambiguity]:
    """Detect missing fields and classify severity.

    Returns a list of Ambiguity objects for each missing field.
    """
    goal = intent.transaction_type.value
    field_defs = _REQUIRED_FIELDS.get(goal, _REQUIRED_FIELDS["purchase"])

    ambiguities: list[Ambiguity] = []

    # Check currency (special case — needed when amount is present)
    has_amount = (
        intent.amount.min is not None
        or intent.amount.max is not None
        or intent.amount.exact is not None
    )
    if has_amount and intent.currency.code is None:
        ambiguities.append(
            Ambiguity(
                field="currency",
                severity=AmbiguitySeverity.REQUIRED,
                message="What currency should this transaction use?",
            )
        )

    for severity_name in ["required", "recommended", "optional"]:
        severity = AmbiguitySeverity(severity_name)
        for field in field_defs[severity_name]:
            if not _is_field_present(intent, field):
                label = _FIELD_LABELS.get(field, field)
                ambiguities.append(
                    Ambiguity(
                        field=field,
                        severity=severity,
                        message=f"What {label} are you looking for?",
                    )
                )

    return ambiguities


def has_required_ambiguities(ambiguities: list[Ambiguity]) -> bool:
    """Check if any required ambiguities exist."""
    return any(a.severity == AmbiguitySeverity.REQUIRED for a in ambiguities)
