"""Tests for Comparison Engine domain models — schema validation."""

import pytest
from pydantic import ValidationError

from app.services.comparison_engine.models import (
    AmountDrift,
    DriftCategory,
    DriftResult,
    DriftSeverity,
    FieldComparisonResult,
    FieldStatus,
    OverallStatus,
    TransactionProposal,
)
from app.services.intent_engine.models import (
    TransactionType,
)

# ── TransactionProposal ────────────────────────────────────────────


class TestTransactionProposal:
    def test_valid_proposal(self):
        p = TransactionProposal(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            intent_id="6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            transaction_type=TransactionType.PURCHASE,
            idempotency_key="key-001",
        )
        assert p.amount is None
        assert p.currency is None
        assert p.merchant_name is None

    def test_currency_normalized(self):
        p = TransactionProposal(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            intent_id="6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            transaction_type=TransactionType.PURCHASE,
            currency="inr",
            idempotency_key="key-002",
        )
        assert p.currency == "INR"

    def test_country_normalized(self):
        p = TransactionProposal(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            intent_id="6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            transaction_type=TransactionType.PURCHASE,
            country="in",
            idempotency_key="key-003",
        )
        assert p.country == "IN"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            TransactionProposal(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                intent_id="6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            )

    def test_nullable_amount(self):
        p = TransactionProposal(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            intent_id="6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            transaction_type=TransactionType.PURCHASE,
            amount=None,
            idempotency_key="key-004",
        )
        assert p.amount is None

    def test_metadata_treated_as_data(self):
        p = TransactionProposal(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            intent_id="6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            transaction_type=TransactionType.PURCHASE,
            idempotency_key="key-005",
            metadata={"note": "test data"},
        )
        assert p.metadata["note"] == "test data"


# ── FieldComparisonResult ──────────────────────────────────────────


class TestFieldComparisonResult:
    def test_match_result(self):
        r = FieldComparisonResult(
            field="currency",
            status=FieldStatus.MATCH,
            drift_category=DriftCategory.CURRENCY_DRIFT,
            severity=DriftSeverity.NONE,
            intent_value="INR",
            proposal_value="INR",
            explanation="Currency matches",
        )
        assert r.status == FieldStatus.MATCH

    def test_mismatch_result(self):
        r = FieldComparisonResult(
            field="currency",
            status=FieldStatus.MISMATCH,
            drift_category=DriftCategory.CURRENCY_DRIFT,
            severity=DriftSeverity.HIGH,
            intent_value="INR",
            proposal_value="USD",
            explanation="Currency mismatch",
        )
        assert r.severity == DriftSeverity.HIGH

    def test_unknown_result(self):
        r = FieldComparisonResult(
            field="amount",
            status=FieldStatus.UNKNOWN,
            drift_category=DriftCategory.AMOUNT_DRIFT,
        )
        assert r.status == FieldStatus.UNKNOWN


# ── AmountDrift ────────────────────────────────────────────────────


class TestAmountDrift:
    def test_valid_drift(self):
        from decimal import Decimal

        d = AmountDrift(
            authorized_boundary="max",
            authorized_value=Decimal("4000"),
            proposed_amount=Decimal("4500"),
            deviation_absolute=Decimal("500"),
            deviation_percent=Decimal("12.5"),
            within_boundary=False,
        )
        assert d.within_boundary is False
        assert d.deviation_percent == Decimal("12.5")


# ── DriftResult ────────────────────────────────────────────────────


class TestDriftResult:
    def test_match_result(self):
        r = DriftResult(
            intent_id="test-intent",
            intent_version=1,
            proposal_intent_id="test-intent",
            overall_status=OverallStatus.MATCH,
            drift_severity=DriftSeverity.NONE,
        )
        assert r.overall_status == OverallStatus.MATCH

    def test_drift_detected(self):
        r = DriftResult(
            intent_id="test-intent",
            intent_version=1,
            proposal_intent_id="test-intent",
            overall_status=OverallStatus.DRIFT_DETECTED,
            drift_severity=DriftSeverity.HIGH,
        )
        assert r.overall_status == OverallStatus.DRIFT_DETECTED

    def test_invalid_proposal(self):
        r = DriftResult(
            intent_id="test-intent",
            intent_version=1,
            proposal_intent_id="test-intent",
            overall_status=OverallStatus.INVALID_PROPOSAL,
            drift_severity=DriftSeverity.NONE,
            rejection_reason="Invalid amount",
        )
        assert r.rejection_reason == "Invalid amount"


# ── Enums ──────────────────────────────────────────────────────────


class TestEnums:
    def test_field_status_values(self):
        assert FieldStatus.MATCH == "match"
        assert FieldStatus.MISMATCH == "mismatch"
        assert FieldStatus.UNKNOWN == "unknown"
        assert FieldStatus.NOT_APPLICABLE == "not_applicable"

    def test_drift_severity_values(self):
        assert DriftSeverity.NONE == "none"
        assert DriftSeverity.CRITICAL == "critical"

    def test_overall_status_values(self):
        assert OverallStatus.MATCH == "match"
        assert OverallStatus.DRIFT_DETECTED == "drift_detected"
        assert OverallStatus.INVALID_PROPOSAL == "invalid_proposal"

    def test_drift_category_values(self):
        assert DriftCategory.AMOUNT_DRIFT == "amount_drift"
        assert DriftCategory.CURRENCY_DRIFT == "currency_drift"
