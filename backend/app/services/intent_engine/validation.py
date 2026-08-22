"""Hard validation — deterministic checks after schema validation.

Schema failures are hard gates.
Constraint contradictions produce rejected or needs_clarification.
This module does NOT evaluate policy — only structural validity.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.intent_engine.models import (
    StructuredIntent,
    TransactionType,
)


class ValidationResult:
    """Result of hard validation."""

    def __init__(
        self,
        valid: bool,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []


def validate_structured_intent(intent: StructuredIntent) -> ValidationResult:
    """Run deterministic constraint validation on a structured intent.

    Returns ValidationResult with valid=True if all checks pass,
    or valid=False with specific error messages.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Transaction type must be in allowed set
    try:
        TransactionType(intent.transaction_type)
    except ValueError:
        errors.append(f"Invalid transaction_type: {intent.transaction_type}")

    # 2. Currency format validation
    if intent.currency.code is not None:
        if len(intent.currency.code) != 3:
            errors.append(f"Currency code must be 3 characters: {intent.currency.code}")
        if not intent.currency.code.isalpha():
            errors.append(f"Currency code must be alphabetic: {intent.currency.code}")

    # 3. Amount relationships
    amt = intent.amount
    if amt.exact is not None:
        if amt.min is not None and amt.exact < amt.min:
            errors.append(
                f"Exact amount ({amt.exact}) is less than min_amount ({amt.min})"
            )
        if amt.max is not None and amt.exact > amt.max:
            errors.append(
                f"Exact amount ({amt.exact}) is greater than max_amount ({amt.max})"
            )
    if amt.min is not None and amt.max is not None:
        if amt.min > amt.max:
            errors.append(
                f"min_amount ({amt.min}) exceeds max_amount ({amt.max})"
            )

    # 4. Date consistency
    temporal = intent.temporal_constraints
    if temporal.deadline is not None:
        if temporal.deadline < datetime.now(UTC):
            errors.append("Temporal deadline is in the past")

    # 5. Goal/transaction_type consistency
    if intent.goal.value != intent.transaction_type.value:
        warnings.append(
            f"goal ({intent.goal}) differs from transaction_type ({intent.transaction_type})"
        )

    # 6. Authorization scope validation
    if intent.authorization_scope.value is not None:
        if intent.authorization_scope.evidence is None:
            warnings.append(
                "authorization_scope has value but no evidence — may be inferred"
            )

    # 7. Currency unknown with amount present
    if intent.currency.code is None:
        has_amount = (
            amt.min is not None or amt.max is not None or amt.exact is not None
        )
        if has_amount:
            warnings.append(
                "Amount present but currency is unknown — downstream may need clarification"
            )

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
