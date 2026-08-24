"""Field-by-field comparators for the Transaction Twin.

Each comparator is a pure function — no database, no LLM, no side effects.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from typing import Any

from app.services.comparison_engine.models import (
    AmountDrift,
    DriftCategory,
    DriftSeverity,
    FieldComparisonResult,
    FieldStatus,
    TransactionProposal,
)
from app.services.intent_engine.models import (
    AuthorizationScopeValue,
    StructuredIntent,
)


def _severity_from_deviation_percent(pct: Decimal) -> DriftSeverity:
    """Map amount deviation percentage to drift severity.

    These are DRIFT SEVERITY thresholds, not risk thresholds.
    """
    if pct <= Decimal("0"):
        return DriftSeverity.NONE
    if pct < Decimal("10"):
        return DriftSeverity.LOW
    if pct < Decimal("25"):
        return DriftSeverity.MEDIUM
    if pct < Decimal("50"):
        return DriftSeverity.HIGH
    return DriftSeverity.CRITICAL


# ── Transaction Type ───────────────────────────────────────────────


def compare_transaction_type(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare transaction type. Mismatch is CRITICAL."""
    intent_val = intent.transaction_type.value
    proposal_val = proposal.transaction_type.value

    if intent_val == proposal_val:
        return FieldComparisonResult(
            field="transaction_type",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.TRANSACTION_TYPE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_val,
            proposal_value=proposal_val,
            explanation=f"Transaction type matches authorized intent ({intent_val})",
        )

    return FieldComparisonResult(
        field="transaction_type",
        status=FieldStatus.MISMATCH,
        drift_category=DriftCategory.TRANSACTION_TYPE_DRIFT,
        severity=DriftSeverity.CRITICAL,
        intent_value=intent_val,
        proposal_value=proposal_val,
        explanation=(
            f"Proposed transaction type '{proposal_val}' does not match "
            f"authorized type '{intent_val}'"
        ),
    )


# ── Amount ─────────────────────────────────────────────────────────


def compare_amount(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare amount against intent constraints using Decimal arithmetic.

    Supports exact, min, max, range, and no-constraint scenarios.
    """
    intent_amt = intent.amount

    # Intent has no amount constraint
    has_intent_amount = (
        intent_amt.exact is not None
        or intent_amt.min is not None
        or intent_amt.max is not None
    )
    if not has_intent_amount:
        return FieldComparisonResult(
            field="amount",
            status=FieldStatus.NOT_APPLICABLE,
            drift_category=DriftCategory.AMOUNT_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=None,
            intent_evidence=_extract_evidence(intent_amt.evidence),
            proposal_value=str(proposal.amount) if proposal.amount is not None else None,
            explanation="No amount constraint in user intent",
        )

    # Proposal has no amount
    if proposal.amount is None:
        return FieldComparisonResult(
            field="amount",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.AMOUNT_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=_intent_amount_dict(intent_amt),
            intent_evidence=_extract_evidence(intent_amt.evidence),
            proposal_value=None,
            explanation="Proposed amount is not specified",
        )

    proposed = proposal.amount

    # Exact match check
    if intent_amt.exact is not None:
        exact = Decimal(str(intent_amt.exact))
        if proposed == exact:
            return FieldComparisonResult(
                field="amount",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.AMOUNT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=_intent_amount_dict(intent_amt),
                intent_evidence=_extract_evidence(intent_amt.evidence),
                proposal_value=str(proposed),
                explanation=f"Proposed amount {proposed} matches exact authorized amount {exact}",
            )
        # Deviation from exact
        deviation_abs = abs(proposed - exact)
        deviation_pct = (deviation_abs / exact * 100) if exact != 0 else Decimal("0")
        within = False
        return _amount_mismatch(
            intent_amt=intent_amt,
            proposed=proposed,
            boundary="exact",
            boundary_value=exact,
            deviation_abs=deviation_abs,
            deviation_pct=deviation_pct,
            within=within,
        )

    # Range check (min and max)
    if intent_amt.min is not None and intent_amt.max is not None:
        min_val = Decimal(str(intent_amt.min))
        max_val = Decimal(str(intent_amt.max))
        if min_val <= proposed <= max_val:
            return FieldComparisonResult(
                field="amount",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.AMOUNT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=_intent_amount_dict(intent_amt),
                intent_evidence=_extract_evidence(intent_amt.evidence),
                proposal_value=str(proposed),
                explanation=(
                    f"Proposed amount {proposed} is within authorized range "
                    f"{min_val}–{max_val}"
                ),
            )
        # Deviation from nearest boundary
        if proposed < min_val:
            deviation_abs = min_val - proposed
            boundary = "min"
            boundary_val = min_val
        else:
            deviation_abs = proposed - max_val
            boundary = "max"
            boundary_val = max_val
        deviation_pct = (
            (deviation_abs / boundary_val * 100) if boundary_val != 0 else Decimal("0")
        )
        return _amount_mismatch(
            intent_amt=intent_amt,
            proposed=proposed,
            boundary=boundary,
            boundary_value=boundary_val,
            deviation_abs=deviation_abs,
            deviation_pct=deviation_pct,
            within=False,
        )

    # Max only
    if intent_amt.max is not None:
        max_val = Decimal(str(intent_amt.max))
        if proposed <= max_val:
            return FieldComparisonResult(
                field="amount",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.AMOUNT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=_intent_amount_dict(intent_amt),
                intent_evidence=_extract_evidence(intent_amt.evidence),
                proposal_value=str(proposed),
                explanation=f"Proposed amount {proposed} is within authorized maximum {max_val}",
            )
        deviation_abs = proposed - max_val
        deviation_pct = (deviation_abs / max_val * 100) if max_val != 0 else Decimal("0")
        return _amount_mismatch(
            intent_amt=intent_amt,
            proposed=proposed,
            boundary="max",
            boundary_value=max_val,
            deviation_abs=deviation_abs,
            deviation_pct=deviation_pct,
            within=False,
        )

    # Min only
    if intent_amt.min is not None:
        min_val = Decimal(str(intent_amt.min))
        if proposed >= min_val:
            return FieldComparisonResult(
                field="amount",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.AMOUNT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=_intent_amount_dict(intent_amt),
                intent_evidence=_extract_evidence(intent_amt.evidence),
                proposal_value=str(proposed),
                explanation=f"Proposed amount {proposed} meets authorized minimum {min_val}",
            )
        deviation_abs = min_val - proposed
        deviation_pct = (deviation_abs / min_val * 100) if min_val != 0 else Decimal("0")
        return _amount_mismatch(
            intent_amt=intent_amt,
            proposed=proposed,
            boundary="min",
            boundary_value=min_val,
            deviation_abs=deviation_abs,
            deviation_pct=deviation_pct,
            within=False,
        )

    # Should not reach here if has_intent_amount is True
    return FieldComparisonResult(
        field="amount",
        status=FieldStatus.UNKNOWN,
        drift_category=DriftCategory.AMOUNT_DRIFT,
        severity=DriftSeverity.NONE,
        intent_value=_intent_amount_dict(intent_amt),
        intent_evidence=_extract_evidence(intent_amt.evidence),
        proposal_value=str(proposed),
        explanation="Unable to evaluate amount constraint",
    )


def _amount_mismatch(
    *,
    intent_amt: object,
    proposed: Decimal,
    boundary: str,
    boundary_value: Decimal,
    deviation_abs: Decimal,
    deviation_pct: Decimal,
    within: bool,
) -> FieldComparisonResult:
    """Build an amount mismatch result with drift details."""
    severity = _severity_from_deviation_percent(deviation_pct)

    # Build explanation
    if boundary == "exact":
        explanation = (
            f"Proposed amount {proposed} deviates from exact authorized amount "
            f"{boundary_value} by {deviation_abs} ({deviation_pct:.1f}%)"
        )
    elif boundary == "max":
        explanation = (
            f"Proposed amount {proposed} exceeds authorized maximum "
            f"{boundary_value} by {deviation_abs} ({deviation_pct:.1f}%)"
        )
    else:
        explanation = (
            f"Proposed amount {proposed} is below authorized minimum "
            f"{boundary_value} by {deviation_abs} ({deviation_pct:.1f}%)"
        )

    return FieldComparisonResult(
        field="amount",
        status=FieldStatus.MISMATCH,
        drift_category=DriftCategory.AMOUNT_DRIFT,
        severity=severity,
        intent_value=_intent_amount_dict(intent_amt),
        intent_evidence=_extract_evidence(getattr(intent_amt, "evidence", None)),
        proposal_value=str(proposed),
        explanation=explanation,
        drift=AmountDrift(
            authorized_boundary=boundary,
            authorized_value=boundary_value,
            proposed_amount=proposed,
            deviation_absolute=deviation_abs,
            deviation_percent=deviation_pct,
            within_boundary=within,
        ),
    )


def _intent_amount_dict(amt: object) -> dict[str, str | None]:
    """Serialize intent amount constraints for comparison output."""
    return {
        "exact": str(amt.exact) if amt.exact is not None else None,
        "min": str(amt.min) if amt.min is not None else None,
        "max": str(amt.max) if amt.max is not None else None,
    }


def _extract_evidence(evidence: object) -> dict[str, Any] | None:
    """Extract evidence dict from Intent Engine Evidence model."""
    if evidence is None:
        return None
    return {"text_span": evidence.text_span, "confidence": evidence.confidence}


# ── Currency ───────────────────────────────────────────────────────


def compare_currency(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare currency codes. No conversion. INR vs INR → MATCH."""
    intent_code = intent.currency.code
    proposal_code = proposal.currency

    if intent_code is None:
        return FieldComparisonResult(
            field="currency",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.CURRENCY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=None,
            intent_evidence=_extract_evidence(intent.currency.evidence),
            proposal_value=proposal_code,
            explanation="Currency was unknown in user intent",
        )

    if proposal_code is None:
        return FieldComparisonResult(
            field="currency",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.CURRENCY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_code,
            intent_evidence=_extract_evidence(intent.currency.evidence),
            proposal_value=None,
            explanation="Proposed currency is not specified",
        )

    if intent_code.upper() == proposal_code.upper():
        return FieldComparisonResult(
            field="currency",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.CURRENCY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_code,
            intent_evidence=_extract_evidence(intent.currency.evidence),
            proposal_value=proposal_code,
            explanation=f"Currency matches authorized intent ({intent_code})",
        )

    return FieldComparisonResult(
        field="currency",
        status=FieldStatus.MISMATCH,
        drift_category=DriftCategory.CURRENCY_DRIFT,
        severity=DriftSeverity.HIGH,
        intent_value=intent_code,
        intent_evidence=_extract_evidence(intent.currency.evidence),
        proposal_value=proposal_code,
        explanation=(
            f"Proposed currency '{proposal_code}' does not match "
            f"authorized currency '{intent_code}'"
        ),
    )


# ── Category / Product ─────────────────────────────────────────────


def compare_category(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare category/product using deterministic string matching."""
    intent_items = intent.category_constraints.items
    proposal_cat = proposal.category

    # No category constraint in intent
    if not intent_items:
        if proposal_cat is None:
            return FieldComparisonResult(
                field="category",
                status=FieldStatus.NOT_APPLICABLE,
                drift_category=DriftCategory.CATEGORY_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=[],
                intent_evidence=_extract_evidence(intent.category_constraints.evidence),
                proposal_value=None,
                explanation="No category constraint in user intent",
            )
        return FieldComparisonResult(
            field="category",
            status=FieldStatus.NOT_APPLICABLE,
            drift_category=DriftCategory.CATEGORY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=[],
            intent_evidence=_extract_evidence(intent.category_constraints.evidence),
            proposal_value=proposal_cat,
            explanation="No category constraint in user intent",
        )

    # Agent didn't specify category
    if proposal_cat is None:
        return FieldComparisonResult(
            field="category",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.CATEGORY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_items,
            intent_evidence=_extract_evidence(intent.category_constraints.evidence),
            proposal_value=None,
            explanation="Proposed category is not specified",
        )

    # Normalize for comparison
    normalized_intent = [_normalize_text(c) for c in intent_items]
    normalized_proposal = _normalize_text(proposal_cat)

    # Exact match
    if normalized_proposal in normalized_intent:
        return FieldComparisonResult(
            field="category",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.CATEGORY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_items,
            intent_evidence=_extract_evidence(intent.category_constraints.evidence),
            proposal_value=proposal_cat,
            explanation=f"Category '{proposal_cat}' matches authorized intent",
        )

    # Containment: proposal is a more specific version of an intent category
    # e.g., intent="running shoes", proposal="nike running shoes"
    for ic in normalized_intent:
        if ic in normalized_proposal:
            return FieldComparisonResult(
                field="category",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.CATEGORY_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=intent_items,
                intent_evidence=_extract_evidence(
                    intent.category_constraints.evidence
                ),
                proposal_value=proposal_cat,
                explanation=(
                    f"Category '{proposal_cat}' is a specific instance of "
                    f"authorized category '{ic}'"
                ),
            )

    # Intent is broader: proposal category is a substring of an intent category
    # e.g., intent="running shoes", proposal="shoes" → conservative MISMATCH
    # because the intent was more specific
    return FieldComparisonResult(
        field="category",
        status=FieldStatus.MISMATCH,
        drift_category=DriftCategory.CATEGORY_DRIFT,
        severity=DriftSeverity.MEDIUM,
        intent_value=intent_items,
        intent_evidence=_extract_evidence(intent.category_constraints.evidence),
        proposal_value=proposal_cat,
        explanation=(
            f"Proposed category '{proposal_cat}' does not match "
            f"authorized categories {intent_items}"
        ),
    )


# ── Product Attributes ─────────────────────────────────────────────


def compare_product_attributes(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare product attributes (color, size, etc.)."""
    intent_attrs = intent.category_constraints.attributes
    proposal_attrs = proposal.product_attributes

    if not intent_attrs:
        return FieldComparisonResult(
            field="product_attributes",
            status=FieldStatus.NOT_APPLICABLE,
            drift_category=DriftCategory.PRODUCT_ATTRIBUTE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value={},
            proposal_value=proposal_attrs,
            explanation="No attribute constraints in user intent",
        )

    if not proposal_attrs:
        return FieldComparisonResult(
            field="product_attributes",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.PRODUCT_ATTRIBUTE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_attrs,
            intent_evidence=_extract_evidence(intent.category_constraints.evidence),
            proposal_value=None,
            explanation="Proposed product attributes are not specified",
        )

    # Compare each required attribute
    mismatches = []
    matches = []
    for key, intent_val in intent_attrs.items():
        proposal_val = proposal_attrs.get(key)
        if proposal_val is None:
            mismatches.append(f"{key}: not specified (expected '{intent_val}')")
        elif _normalize_text(proposal_val) == _normalize_text(intent_val):
            matches.append(key)
        else:
            mismatches.append(f"{key}: '{proposal_val}' ≠ '{intent_val}'")

    if not mismatches:
        return FieldComparisonResult(
            field="product_attributes",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.PRODUCT_ATTRIBUTE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_attrs,
            intent_evidence=_extract_evidence(intent.category_constraints.evidence),
            proposal_value=proposal_attrs,
            explanation="All product attributes match authorized intent",
        )

    return FieldComparisonResult(
        field="product_attributes",
        status=FieldStatus.MISMATCH,
        drift_category=DriftCategory.PRODUCT_ATTRIBUTE_DRIFT,
        severity=DriftSeverity.MEDIUM,
        intent_value=intent_attrs,
        intent_evidence=_extract_evidence(intent.category_constraints.evidence),
        proposal_value=proposal_attrs,
        explanation=f"Attribute mismatches: {'; '.join(mismatches)}",
    )


# ── Merchant ───────────────────────────────────────────────────────


def compare_merchant(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare merchant constraints (trust, preferred, excluded)."""
    mc = intent.merchant_constraints
    has_constraint = mc.trust_required or mc.preferred or mc.excluded

    if not has_constraint:
        return FieldComparisonResult(
            field="merchant",
            status=FieldStatus.NOT_APPLICABLE,
            drift_category=DriftCategory.MERCHANT_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value={
                "trust_required": mc.trust_required,
                "preferred": mc.preferred,
                "excluded": mc.excluded,
            },
            proposal_value={
                "name": proposal.merchant_name,
                "trusted": proposal.merchant_trusted,
            },
            explanation="No merchant constraint in user intent",
        )

    # Trust required
    if mc.trust_required:
        if proposal.merchant_trusted is None:
            return FieldComparisonResult(
                field="merchant",
                status=FieldStatus.UNKNOWN,
                drift_category=DriftCategory.MERCHANT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"trust_required": True},
                intent_evidence=_extract_evidence(mc.evidence),
                proposal_value={
                    "name": proposal.merchant_name,
                    "trusted": None,
                },
                explanation="Merchant trust status is unknown",
            )
        if proposal.merchant_trusted:
            return FieldComparisonResult(
                field="merchant",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.MERCHANT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"trust_required": True},
                intent_evidence=_extract_evidence(mc.evidence),
                proposal_value={
                    "name": proposal.merchant_name,
                    "trusted": True,
                },
                explanation="Merchant is trusted as required by user intent",
            )
        return FieldComparisonResult(
            field="merchant",
            status=FieldStatus.MISMATCH,
            drift_category=DriftCategory.MERCHANT_DRIFT,
            severity=DriftSeverity.HIGH,
            intent_value={"trust_required": True},
            intent_evidence=_extract_evidence(mc.evidence),
            proposal_value={
                "name": proposal.merchant_name,
                "trusted": False,
            },
            explanation="Merchant is not trusted — user intent requires trusted seller",
        )

    # Excluded merchants
    if mc.excluded:
        if proposal.merchant_name is None:
            return FieldComparisonResult(
                field="merchant",
                status=FieldStatus.UNKNOWN,
                drift_category=DriftCategory.MERCHANT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"excluded": mc.excluded},
                intent_evidence=_extract_evidence(mc.evidence),
                proposal_value=None,
                explanation="Proposed merchant is not specified",
            )
        normalized_excluded = [m.lower().strip() for m in mc.excluded]
        if proposal.merchant_name.lower().strip() in normalized_excluded:
            return FieldComparisonResult(
                field="merchant",
                status=FieldStatus.MISMATCH,
                drift_category=DriftCategory.MERCHANT_DRIFT,
                severity=DriftSeverity.MEDIUM,
                intent_value={"excluded": mc.excluded},
                intent_evidence=_extract_evidence(mc.evidence),
                proposal_value=proposal.merchant_name,
                explanation=(
                    f"Merchant '{proposal.merchant_name}' is excluded "
                    f"by user intent {mc.excluded}"
                ),
            )
        return FieldComparisonResult(
            field="merchant",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.MERCHANT_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value={"excluded": mc.excluded},
            intent_evidence=_extract_evidence(mc.evidence),
            proposal_value=proposal.merchant_name,
            explanation=f"Merchant '{proposal.merchant_name}' is not in excluded list",
        )

    # Preferred merchants
    if mc.preferred:
        if proposal.merchant_name is None:
            return FieldComparisonResult(
                field="merchant",
                status=FieldStatus.UNKNOWN,
                drift_category=DriftCategory.MERCHANT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"preferred": mc.preferred},
                intent_evidence=_extract_evidence(mc.evidence),
                proposal_value=None,
                explanation="Proposed merchant is not specified",
            )
        normalized_preferred = [m.lower().strip() for m in mc.preferred]
        if proposal.merchant_name.lower().strip() in normalized_preferred:
            return FieldComparisonResult(
                field="merchant",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.MERCHANT_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"preferred": mc.preferred},
                intent_evidence=_extract_evidence(mc.evidence),
                proposal_value=proposal.merchant_name,
                explanation=(
                    f"Merchant '{proposal.merchant_name}' is in preferred list"
                ),
            )
        return FieldComparisonResult(
            field="merchant",
            status=FieldStatus.MISMATCH,
            drift_category=DriftCategory.MERCHANT_DRIFT,
            severity=DriftSeverity.MEDIUM,
            intent_value={"preferred": mc.preferred},
            intent_evidence=_extract_evidence(mc.evidence),
            proposal_value=proposal.merchant_name,
            explanation=(
                f"Merchant '{proposal.merchant_name}' is not in preferred list "
                f"{mc.preferred}"
            ),
        )

    return FieldComparisonResult(
        field="merchant",
        status=FieldStatus.UNKNOWN,
        drift_category=DriftCategory.MERCHANT_DRIFT,
        severity=DriftSeverity.NONE,
        intent_value=None,
        proposal_value={
            "name": proposal.merchant_name,
            "trusted": proposal.merchant_trusted,
        },
        explanation="Unable to evaluate merchant constraint",
    )


# ── Geographic ─────────────────────────────────────────────────────


def compare_geographic(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare geographic constraints (country, city)."""
    gc = intent.geographic_constraints
    has_constraint = gc.country is not None or gc.city is not None

    if not has_constraint:
        return FieldComparisonResult(
            field="geographic",
            status=FieldStatus.NOT_APPLICABLE,
            drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=None,
            proposal_value={"country": proposal.country, "city": proposal.city},
            explanation="No geographic constraint in user intent",
        )

    # Country comparison
    if gc.country is not None:
        if proposal.country is None:
            return FieldComparisonResult(
                field="geographic",
                status=FieldStatus.UNKNOWN,
                drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"country": gc.country, "city": gc.city},
                intent_evidence=_extract_evidence(gc.evidence),
                proposal_value={"country": None, "city": proposal.city},
                explanation="Proposed country is not specified",
            )
        if gc.country.upper() != proposal.country.upper():
            return FieldComparisonResult(
                field="geographic",
                status=FieldStatus.MISMATCH,
                drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                severity=DriftSeverity.MEDIUM,
                intent_value={"country": gc.country, "city": gc.city},
                intent_evidence=_extract_evidence(gc.evidence),
                proposal_value={"country": proposal.country, "city": proposal.city},
                explanation=(
                    f"Proposed country '{proposal.country}' does not match "
                    f"authorized country '{gc.country}'"
                ),
            )
        # Country matches — also check city if specified
        if gc.city is not None:
            if proposal.city is None:
                return FieldComparisonResult(
                    field="geographic",
                    status=FieldStatus.UNKNOWN,
                    drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                    severity=DriftSeverity.NONE,
                    intent_value={"country": gc.country, "city": gc.city},
                    intent_evidence=_extract_evidence(gc.evidence),
                    proposal_value={"country": proposal.country, "city": None},
                    explanation="Proposed city is not specified",
                )
            if gc.city.lower().strip() == proposal.city.lower().strip():
                return FieldComparisonResult(
                    field="geographic",
                    status=FieldStatus.MATCH,
                    drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                    severity=DriftSeverity.NONE,
                    intent_value={"country": gc.country, "city": gc.city},
                    intent_evidence=_extract_evidence(gc.evidence),
                    proposal_value={"country": proposal.country, "city": proposal.city},
                    explanation=(
                        f"Location {proposal.country}/{proposal.city} matches "
                        f"authorized intent"
                    ),
                )
            return FieldComparisonResult(
                field="geographic",
                status=FieldStatus.MISMATCH,
                drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                severity=DriftSeverity.MEDIUM,
                intent_value={"country": gc.country, "city": gc.city},
                intent_evidence=_extract_evidence(gc.evidence),
                proposal_value={"country": proposal.country, "city": proposal.city},
                explanation=(
                    f"Proposed city '{proposal.city}' does not match "
                    f"authorized city '{gc.city}'"
                ),
            )
        # Country matches, no city constraint
        return FieldComparisonResult(
            field="geographic",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value={"country": gc.country, "city": gc.city},
            intent_evidence=_extract_evidence(gc.evidence),
            proposal_value={"country": proposal.country, "city": proposal.city},
            explanation=f"Country '{proposal.country}' matches authorized intent",
        )

    # Only city specified (no country)
    if gc.city is not None:
        if proposal.city is None:
            return FieldComparisonResult(
                field="geographic",
                status=FieldStatus.UNKNOWN,
                drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"city": gc.city},
                intent_evidence=_extract_evidence(gc.evidence),
                proposal_value={"city": None},
                explanation="Proposed city is not specified",
            )
        if gc.city.lower().strip() == proposal.city.lower().strip():
            return FieldComparisonResult(
                field="geographic",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value={"city": gc.city},
                intent_evidence=_extract_evidence(gc.evidence),
                proposal_value={"city": proposal.city},
                explanation=f"City '{proposal.city}' matches authorized intent",
            )
        return FieldComparisonResult(
            field="geographic",
            status=FieldStatus.MISMATCH,
            drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
            severity=DriftSeverity.MEDIUM,
            intent_value={"city": gc.city},
            intent_evidence=_extract_evidence(gc.evidence),
            proposal_value={"city": proposal.city},
            explanation=(
                f"Proposed city '{proposal.city}' does not match "
                f"authorized city '{gc.city}'"
            ),
        )

    return FieldComparisonResult(
        field="geographic",
        status=FieldStatus.UNKNOWN,
        drift_category=DriftCategory.GEOGRAPHIC_DRIFT,
        severity=DriftSeverity.NONE,
        intent_value=None,
        proposal_value={"country": proposal.country, "city": proposal.city},
        explanation="Unable to evaluate geographic constraint",
    )


# ── Temporal ───────────────────────────────────────────────────────


def compare_temporal(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare temporal constraints using timezone-aware datetime."""
    tc = intent.temporal_constraints
    has_constraint = (
        tc.deadline is not None or tc.duration is not None or tc.recurring
    )

    if not has_constraint:
        return FieldComparisonResult(
            field="temporal",
            status=FieldStatus.NOT_APPLICABLE,
            drift_category=DriftCategory.TEMPORAL_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=None,
            proposal_value=(
                proposal.scheduled_at.isoformat() if proposal.scheduled_at else None
            ),
            explanation="No temporal constraint in user intent",
        )

    if proposal.scheduled_at is None:
        return FieldComparisonResult(
            field="temporal",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.TEMPORAL_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=_temporal_intent_dict(tc),
            intent_evidence=_extract_evidence(tc.evidence),
            proposal_value=None,
            explanation="Proposed transaction time is not specified",
        )

    # Ensure both datetimes are timezone-aware for comparison
    proposed_dt = proposal.scheduled_at
    if proposed_dt.tzinfo is None:
        proposed_dt = proposed_dt.replace(tzinfo=UTC)

    # Deadline check
    if tc.deadline is not None:
        deadline = tc.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)

        if proposed_dt <= deadline:
            return FieldComparisonResult(
                field="temporal",
                status=FieldStatus.MATCH,
                drift_category=DriftCategory.TEMPORAL_DRIFT,
                severity=DriftSeverity.NONE,
                intent_value=_temporal_intent_dict(tc),
                intent_evidence=_extract_evidence(tc.evidence),
                proposal_value=proposed_dt.isoformat(),
                explanation=(
                    f"Proposed time {proposed_dt.isoformat()} is before "
                    f"deadline {deadline.isoformat()}"
                ),
            )
        return FieldComparisonResult(
            field="temporal",
            status=FieldStatus.MISMATCH,
            drift_category=DriftCategory.TEMPORAL_DRIFT,
            severity=DriftSeverity.LOW,
            intent_value=_temporal_intent_dict(tc),
            intent_evidence=_extract_evidence(tc.evidence),
            proposal_value=proposed_dt.isoformat(),
            explanation=(
                f"Proposed time {proposed_dt.isoformat()} exceeds "
                f"deadline {deadline.isoformat()}"
            ),
        )

    # Recurring constraint — cannot fully evaluate from timestamp alone
    if tc.recurring:
        return FieldComparisonResult(
            field="temporal",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.TEMPORAL_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=_temporal_intent_dict(tc),
            intent_evidence=_extract_evidence(tc.evidence),
            proposal_value=proposed_dt.isoformat(),
            explanation="Recurring constraint cannot be evaluated from a single timestamp",
        )

    return FieldComparisonResult(
        field="temporal",
        status=FieldStatus.UNKNOWN,
        drift_category=DriftCategory.TEMPORAL_DRIFT,
        severity=DriftSeverity.NONE,
        intent_value=_temporal_intent_dict(tc),
        intent_evidence=_extract_evidence(tc.evidence),
        proposal_value=proposed_dt.isoformat(),
        explanation="Unable to evaluate temporal constraint",
    )


def _temporal_intent_dict(tc: object) -> dict[str, str | bool | None]:
    """Serialize temporal constraints for comparison output."""
    return {
        "deadline": tc.deadline.isoformat() if tc.deadline else None,
        "duration": tc.duration,
        "recurring": tc.recurring,
    }


# ── Authorization Scope ────────────────────────────────────────────


def compare_authorization_scope(
    intent: StructuredIntent,
    proposal: TransactionProposal,
) -> FieldComparisonResult:
    """Compare authorization scope."""
    intent_scope = intent.authorization_scope.value
    proposal_scope = proposal.authorization_scope

    if intent_scope is None:
        return FieldComparisonResult(
            field="authorization_scope",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.AUTHORIZATION_SCOPE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=None,
            proposal_value=proposal_scope.value if proposal_scope else None,
            explanation="Authorization scope was not specified in user intent",
        )

    if proposal_scope is None:
        return FieldComparisonResult(
            field="authorization_scope",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.AUTHORIZATION_SCOPE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_scope.value,
            proposal_value=None,
            explanation="Proposed authorization scope is not specified",
        )

    if intent_scope == proposal_scope:
        return FieldComparisonResult(
            field="authorization_scope",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.AUTHORIZATION_SCOPE_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value=intent_scope.value,
            proposal_value=proposal_scope.value,
            explanation=f"Authorization scope '{proposal_scope.value}' matches intent",
        )

    # Scope escalation detection
    is_escalation = (
        (intent_scope == AuthorizationScopeValue.SINGLE_USE)
        and proposal_scope in (
            AuthorizationScopeValue.RECURRING,
            AuthorizationScopeValue.SESSION,
        )
    ) or (
        (intent_scope == AuthorizationScopeValue.SESSION)
        and proposal_scope == AuthorizationScopeValue.RECURRING
    )

    if is_escalation:
        return FieldComparisonResult(
            field="authorization_scope",
            status=FieldStatus.MISMATCH,
            drift_category=DriftCategory.AUTHORIZATION_SCOPE_DRIFT,
            severity=DriftSeverity.HIGH,
            intent_value=intent_scope.value,
            proposal_value=proposal_scope.value,
            explanation=(
                f"Proposed scope '{proposal_scope.value}' escalates beyond "
                f"authorized scope '{intent_scope.value}'"
            ),
        )

    # Narrower scope is acceptable (e.g., recurring → single_use)
    return FieldComparisonResult(
        field="authorization_scope",
        status=FieldStatus.MATCH,
        drift_category=DriftCategory.AUTHORIZATION_SCOPE_DRIFT,
        severity=DriftSeverity.NONE,
        intent_value=intent_scope.value,
        proposal_value=proposal_scope.value,
        explanation=(
            f"Proposed scope '{proposal_scope.value}' is within "
            f"authorized scope '{intent_scope.value}'"
        ),
    )


# ── Helpers ────────────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip whitespace."""
    return text.lower().strip()
