"""Aggregation logic for overall status and drift severity.

Severity is NOT a risk score. It measures distance from authorized intent.
"""

from __future__ import annotations

from app.services.comparison_engine.models import (
    DriftResult,
    DriftSeverity,
    FieldComparisonResult,
    FieldStatus,
    OverallStatus,
)

# Base severity for each field on mismatch
_BASE_FIELD_SEVERITY: dict[str, DriftSeverity] = {
    "transaction_type": DriftSeverity.CRITICAL,
    "currency": DriftSeverity.HIGH,
    "merchant": DriftSeverity.MEDIUM,  # overridden per sub-constraint
    "category": DriftSeverity.MEDIUM,
    "product_attributes": DriftSeverity.MEDIUM,
    "geographic": DriftSeverity.MEDIUM,
    "temporal": DriftSeverity.LOW,
    "authorization_scope": DriftSeverity.HIGH,
    # "amount" severity is calculated dynamically from deviation percentage
}

# Severity hierarchy for max computation
_SEVERITY_ORDER: list[DriftSeverity] = [
    DriftSeverity.NONE,
    DriftSeverity.LOW,
    DriftSeverity.MEDIUM,
    DriftSeverity.HIGH,
    DriftSeverity.CRITICAL,
]


def compute_drift_severity(field_results: list[FieldComparisonResult]) -> DriftSeverity:
    """Compute overall drift severity as the maximum across all field mismatches."""
    max_severity = DriftSeverity.NONE
    for fr in field_results:
        if fr.status == FieldStatus.MISMATCH:
            idx = _SEVERITY_ORDER.index(fr.severity)
            max_idx = _SEVERITY_ORDER.index(max_severity)
            if idx > max_idx:
                max_severity = fr.severity
    return max_severity


def compute_overall_status(
    field_results: list[FieldComparisonResult],
) -> OverallStatus:
    """Compute overall comparison status from field-level results.

    Rules:
    - All applicable fields match → MATCH
    - Any mismatch → DRIFT_DETECTED (or PARTIAL_MATCH if some also match)
    - No mismatches but insufficient information → INSUFFICIENT_DATA
    """
    has_match = any(fr.status == FieldStatus.MATCH for fr in field_results)
    has_mismatch = any(fr.status == FieldStatus.MISMATCH for fr in field_results)
    has_unknown = any(fr.status == FieldStatus.UNKNOWN for fr in field_results)

    if has_mismatch:
        if has_match:
            return OverallStatus.PARTIAL_MATCH
        return OverallStatus.DRIFT_DETECTED

    if has_match:
        return OverallStatus.MATCH

    # No matches, no mismatches — all UNKNOWN or NOT_APPLICABLE
    if has_unknown:
        return OverallStatus.INSUFFICIENT_DATA

    # All NOT_APPLICABLE — no constraints to compare
    return OverallStatus.MATCH


def aggregate_counts(
    field_results: list[FieldComparisonResult],
) -> tuple[int, int, int, int]:
    """Count matches, mismatches, unknowns, and not-applicable."""
    match = sum(1 for fr in field_results if fr.status == FieldStatus.MATCH)
    mismatch = sum(1 for fr in field_results if fr.status == FieldStatus.MISMATCH)
    unknown = sum(1 for fr in field_results if fr.status == FieldStatus.UNKNOWN)
    not_applicable = sum(
        1 for fr in field_results if fr.status == FieldStatus.NOT_APPLICABLE
    )
    return match, mismatch, unknown, not_applicable


def generate_summary(result: DriftResult) -> str:
    """Generate a plain-English summary of the comparison result."""
    if result.overall_status == OverallStatus.MATCH:
        return "Proposed transaction fully matches user intent."
    if result.overall_status == OverallStatus.INSUFFICIENT_DATA:
        return "Unable to evaluate — insufficient constraint information in user intent."
    if result.overall_status == OverallStatus.INVALID_PROPOSAL:
        return result.rejection_reason or "Invalid proposal."
    if result.overall_status == OverallStatus.PARTIAL_MATCH:
        mismatches = [
            fr for fr in result.field_comparisons if fr.status == FieldStatus.MISMATCH
        ]
        parts = [f"{fr.field}: {fr.explanation}" for fr in mismatches]
        return f"Proposed transaction partially matches — deviations detected: {'; '.join(parts)}"

    # DRIFT_DETECTED
    mismatches = [
        fr for fr in result.field_comparisons if fr.status == FieldStatus.MISMATCH
    ]
    parts = [f"{fr.field}: {fr.explanation}" for fr in mismatches]
    return f"Proposed transaction deviates from user intent: {'; '.join(parts)}"
