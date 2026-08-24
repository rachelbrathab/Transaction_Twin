"""Tests for aggregation logic — overall status, severity, summary."""

from app.services.comparison_engine.aggregator import (
    aggregate_counts,
    compute_drift_severity,
    compute_overall_status,
    generate_summary,
)
from app.services.comparison_engine.models import (
    DriftCategory,
    DriftResult,
    DriftSeverity,
    FieldComparisonResult,
    FieldStatus,
    OverallStatus,
)


def _field_result(
    field: str,
    status: FieldStatus,
    severity: DriftSeverity = DriftSeverity.NONE,
    explanation: str = "",
) -> FieldComparisonResult:
    """Helper to create a FieldComparisonResult."""
    return FieldComparisonResult(
        field=field,
        status=status,
        drift_category=DriftCategory.TRANSACTION_TYPE_DRIFT,
        severity=severity,
        explanation=explanation,
    )


class TestComputeOverallStatus:
    def test_all_match(self):
        results = [
            _field_result("transaction_type", FieldStatus.MATCH),
            _field_result("amount", FieldStatus.MATCH),
            _field_result("currency", FieldStatus.MATCH),
        ]
        assert compute_overall_status(results) == OverallStatus.MATCH

    def test_one_mismatch(self):
        results = [
            _field_result("transaction_type", FieldStatus.MATCH),
            _field_result("amount", FieldStatus.MISMATCH),
            _field_result("currency", FieldStatus.MATCH),
        ]
        assert compute_overall_status(results) == OverallStatus.PARTIAL_MATCH

    def test_mismatch_no_match(self):
        results = [
            _field_result("amount", FieldStatus.MISMATCH),
            _field_result("currency", FieldStatus.UNKNOWN),
        ]
        assert compute_overall_status(results) == OverallStatus.DRIFT_DETECTED

    def test_all_unknown(self):
        results = [
            _field_result("amount", FieldStatus.UNKNOWN),
            _field_result("currency", FieldStatus.UNKNOWN),
        ]
        assert compute_overall_status(results) == OverallStatus.INSUFFICIENT_DATA

    def test_all_not_applicable(self):
        results = [
            _field_result("amount", FieldStatus.NOT_APPLICABLE),
            _field_result("currency", FieldStatus.NOT_APPLICABLE),
        ]
        assert compute_overall_status(results) == OverallStatus.MATCH

    def test_mixed_unknown_and_not_applicable(self):
        results = [
            _field_result("amount", FieldStatus.UNKNOWN),
            _field_result("currency", FieldStatus.NOT_APPLICABLE),
        ]
        assert compute_overall_status(results) == OverallStatus.INSUFFICIENT_DATA

    def test_empty_results(self):
        assert compute_overall_status([]) == OverallStatus.MATCH


class TestComputeDriftSeverity:
    def test_all_match(self):
        results = [
            _field_result("transaction_type", FieldStatus.MATCH),
            _field_result("amount", FieldStatus.MATCH),
        ]
        assert compute_drift_severity(results) == DriftSeverity.NONE

    def test_critical_severity(self):
        results = [
            _field_result(
                "transaction_type",
                FieldStatus.MISMATCH,
                DriftSeverity.CRITICAL,
            ),
            _field_result("amount", FieldStatus.MATCH),
        ]
        assert compute_drift_severity(results) == DriftSeverity.CRITICAL

    def test_high_severity(self):
        results = [
            _field_result("currency", FieldStatus.MISMATCH, DriftSeverity.HIGH),
            _field_result("amount", FieldStatus.MATCH),
        ]
        assert compute_drift_severity(results) == DriftSeverity.HIGH

    def test_mixed_severity(self):
        results = [
            _field_result("amount", FieldStatus.MISMATCH, DriftSeverity.LOW),
            _field_result("currency", FieldStatus.MISMATCH, DriftSeverity.HIGH),
        ]
        assert compute_drift_severity(results) == DriftSeverity.HIGH

    def test_no_mismatches(self):
        results = [
            _field_result("amount", FieldStatus.UNKNOWN),
            _field_result("currency", FieldStatus.NOT_APPLICABLE),
        ]
        assert compute_drift_severity(results) == DriftSeverity.NONE

    def test_empty_results(self):
        assert compute_drift_severity([]) == DriftSeverity.NONE


class TestAggregateCounts:
    def test_all_statuses(self):
        results = [
            _field_result("a", FieldStatus.MATCH),
            _field_result("b", FieldStatus.MISMATCH),
            _field_result("c", FieldStatus.UNKNOWN),
            _field_result("d", FieldStatus.NOT_APPLICABLE),
        ]
        m, mi, u, na = aggregate_counts(results)
        assert m == 1
        assert mi == 1
        assert u == 1
        assert na == 1

    def test_all_match(self):
        results = [
            _field_result("a", FieldStatus.MATCH),
            _field_result("b", FieldStatus.MATCH),
        ]
        m, mi, u, na = aggregate_counts(results)
        assert m == 2
        assert mi == 0
        assert u == 0
        assert na == 0

    def test_empty(self):
        m, mi, u, na = aggregate_counts([])
        assert m == 0
        assert mi == 0
        assert u == 0
        assert na == 0


class TestGenerateSummary:
    def test_match_summary(self):
        result = DriftResult(
            intent_id="test",
            intent_version=1,
            proposal_intent_id="test",
            overall_status=OverallStatus.MATCH,
            drift_severity=DriftSeverity.NONE,
        )
        summary = generate_summary(result)
        assert "fully matches" in summary

    def test_insufficient_data_summary(self):
        result = DriftResult(
            intent_id="test",
            intent_version=1,
            proposal_intent_id="test",
            overall_status=OverallStatus.INSUFFICIENT_DATA,
            drift_severity=DriftSeverity.NONE,
        )
        summary = generate_summary(result)
        assert "insufficient" in summary.lower()

    def test_drift_detected_summary(self):
        result = DriftResult(
            intent_id="test",
            intent_version=1,
            proposal_intent_id="test",
            overall_status=OverallStatus.DRIFT_DETECTED,
            drift_severity=DriftSeverity.HIGH,
            field_comparisons=[
                _field_result(
                    "amount",
                    FieldStatus.MISMATCH,
                    explanation="Amount exceeds maximum",
                ),
            ],
        )
        summary = generate_summary(result)
        assert "deviates" in summary.lower()
        assert "amount" in summary.lower()

    def test_partial_match_summary(self):
        result = DriftResult(
            intent_id="test",
            intent_version=1,
            proposal_intent_id="test",
            overall_status=OverallStatus.PARTIAL_MATCH,
            drift_severity=DriftSeverity.MEDIUM,
            field_comparisons=[
                _field_result("amount", FieldStatus.MATCH),
                _field_result(
                    "currency",
                    FieldStatus.MISMATCH,
                    explanation="Currency mismatch",
                ),
            ],
        )
        summary = generate_summary(result)
        assert "partially matches" in summary.lower()

    def test_invalid_proposal_summary(self):
        result = DriftResult(
            intent_id="test",
            intent_version=1,
            proposal_intent_id="test",
            overall_status=OverallStatus.INVALID_PROPOSAL,
            drift_severity=DriftSeverity.NONE,
            rejection_reason="Invalid amount",
        )
        summary = generate_summary(result)
        assert "Invalid amount" in summary
