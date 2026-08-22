"""Tests for Intent Engine domain models — schema validation."""

import pytest
from pydantic import ValidationError

from app.services.intent_engine.models import (
    Ambiguity,
    AmbiguitySeverity,
    AmountConstraints,
    AuthorizationScope,
    AuthorizationScopeValue,
    CategoryConstraints,
    CurrencyInfo,
    CurrencySource,
    Evidence,
    GeographicConstraints,
    GoalType,
    IntentMetadata,
    IntentParseRequest,
    MerchantConstraints,
    ParseResult,
    ParseStatus,
    StructuredIntent,
    TemporalConstraints,
    TransactionType,
)


def _make_intent(**overrides) -> StructuredIntent:
    """Create a valid StructuredIntent for testing."""
    defaults = {
        "goal": GoalType.PURCHASE,
        "transaction_type": TransactionType.PURCHASE,
        "currency": CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT),
        "amount": AmountConstraints(max=4000),
        "metadata": IntentMetadata(
            parser_version="test-v1",
            extraction_method="deterministic",
            canonical_request="test",
            reference_timestamp="2026-01-01T00:00:00Z",
        ),
    }
    defaults.update(overrides)
    return StructuredIntent(**defaults)


# ── Evidence ───────────────────────────────────────────────────────


class TestEvidence:
    def test_valid_evidence(self):
        e = Evidence(text_span="under ₹4,000", confidence=0.95)
        assert e.text_span == "under ₹4,000"
        assert e.confidence == 0.95

    def test_evidence_min_confidence(self):
        e = Evidence(text_span="test", confidence=0.0)
        assert e.confidence == 0.0

    def test_evidence_max_confidence(self):
        e = Evidence(text_span="test", confidence=1.0)
        assert e.confidence == 1.0

    def test_evidence_confidence_below_min(self):
        with pytest.raises(ValidationError):
            Evidence(text_span="test", confidence=-0.1)

    def test_evidence_confidence_above_max(self):
        with pytest.raises(ValidationError):
            Evidence(text_span="test", confidence=1.1)


# ── Currency ───────────────────────────────────────────────────────


class TestCurrencyInfo:
    def test_explicit_currency(self):
        c = CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT)
        assert c.code == "INR"
        assert c.source == CurrencySource.EXPLICIT

    def test_unknown_currency(self):
        c = CurrencyInfo(code=None, source=CurrencySource.UNKNOWN)
        assert c.code is None

    def test_currency_code_length(self):
        with pytest.raises(ValidationError):
            CurrencyInfo(code="IN", source=CurrencySource.EXPLICIT)

    def test_currency_source_values(self):
        for src in CurrencySource:
            c = CurrencyInfo(code="USD", source=src)
            assert c.source == src


# ── Amount ─────────────────────────────────────────────────────────


class TestAmountConstraints:
    def test_valid_range(self):
        a = AmountConstraints(min=100, max=500)
        assert a.min == 100
        assert a.max == 500

    def test_exact_only(self):
        a = AmountConstraints(exact=4000)
        assert a.exact == 4000

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValidationError):
            AmountConstraints(min=500, max=100)

    def test_exact_less_than_min_raises(self):
        with pytest.raises(ValidationError):
            AmountConstraints(exact=50, min=100)

    def test_exact_greater_than_max_raises(self):
        with pytest.raises(ValidationError):
            AmountConstraints(exact=600, max=500)

    def test_all_null(self):
        a = AmountConstraints()
        assert a.min is None
        assert a.max is None
        assert a.exact is None

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError):
            AmountConstraints(min=-100)


# ── Category ───────────────────────────────────────────────────────


class TestCategoryConstraints:
    def test_with_items(self):
        c = CategoryConstraints(items=["running shoes"], attributes={"color": "black"})
        assert "running shoes" in c.items
        assert c.attributes["color"] == "black"

    def test_empty(self):
        c = CategoryConstraints()
        assert c.items == []
        assert c.attributes == {}


# ── Merchant ───────────────────────────────────────────────────────


class TestMerchantConstraints:
    def test_trust_required(self):
        m = MerchantConstraints(trust_required=True)
        assert m.trust_required is True

    def test_default(self):
        m = MerchantConstraints()
        assert m.trust_required is False


# ── Geographic ─────────────────────────────────────────────────────


class TestGeographicConstraints:
    def test_with_city(self):
        g = GeographicConstraints(city="Bangalore")
        assert g.city == "Bangalore"

    def test_empty(self):
        g = GeographicConstraints()
        assert g.country is None
        assert g.city is None


# ── Temporal ───────────────────────────────────────────────────────


class TestTemporalConstraints:
    def test_recurring(self):
        t = TemporalConstraints(recurring=True)
        assert t.recurring is True


# ── Authorization Scope ────────────────────────────────────────────


class TestAuthorizationScope:
    def test_null_value(self):
        s = AuthorizationScope(value=None)
        assert s.value is None

    def test_explicit_scope(self):
        s = AuthorizationScope(value=AuthorizationScopeValue.SINGLE_USE)
        assert s.value == AuthorizationScopeValue.SINGLE_USE

    def test_scope_without_evidence(self):
        s = AuthorizationScope(value=AuthorizationScopeValue.RECURRING, evidence=None)
        assert s.value == AuthorizationScopeValue.RECURRING

    def test_evidence_without_value_raises(self):
        with pytest.raises(ValidationError):
            AuthorizationScope(
                value=None,
                evidence=Evidence(text_span="test", confidence=0.9),
            )


# ── Structured Intent ──────────────────────────────────────────────


class TestStructuredIntent:
    def test_valid_purchase_intent(self):
        intent = _make_intent()
        assert intent.goal == GoalType.PURCHASE
        assert intent.transaction_type == TransactionType.PURCHASE

    def test_null_authorization_scope(self):
        intent = _make_intent()
        assert intent.authorization_scope.value is None

    def test_schema_validation_preserves_original(self):
        """Schema validation must not modify the original text."""
        intent = _make_intent()
        assert intent.metadata.canonical_request == "test"


# ── Parse Result ───────────────────────────────────────────────────


class TestParseResult:
    def test_parsed_result(self):
        r = ParseResult(status=ParseStatus.PARSED, confidence=0.9)
        assert r.status == ParseStatus.PARSED

    def test_rejection(self):
        r = ParseResult(
            status=ParseStatus.REJECTED,
            rejection_reason="Invalid input",
        )
        assert r.rejection_reason == "Invalid input"

    def test_needs_clarification(self):
        a = Ambiguity(
            field="category",
            severity=AmbiguitySeverity.REQUIRED,
            message="What product?",
        )
        r = ParseResult(
            status=ParseStatus.NEEDS_CLARIFICATION,
            ambiguities=[a],
        )
        assert len(r.ambiguities) == 1


# ── API Request ────────────────────────────────────────────────────


class TestIntentParseRequest:
    def test_valid_request(self):
        r = IntentParseRequest(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            original_request="Buy shoes",
        )
        assert r.default_currency == "INR"

    def test_empty_request_rejected(self):
        with pytest.raises(ValidationError):
            IntentParseRequest(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                original_request="",
            )

    def test_long_request_rejected(self):
        with pytest.raises(ValidationError):
            IntentParseRequest(
                user_id="550e8400-e29b-41d4-a716-446655440000",
                agent_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                original_request="x" * 6000,
            )
