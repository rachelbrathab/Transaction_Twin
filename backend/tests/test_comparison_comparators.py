"""Comprehensive tests for field-by-field comparators."""

from datetime import UTC, datetime
from decimal import Decimal

from app.services.comparison_engine.comparator import (
    _severity_from_deviation_percent,
    compare_amount,
    compare_authorization_scope,
    compare_category,
    compare_currency,
    compare_geographic,
    compare_merchant,
    compare_product_attributes,
    compare_temporal,
    compare_transaction_type,
)
from app.services.comparison_engine.models import (
    DriftSeverity,
    FieldStatus,
    TransactionProposal,
)
from app.services.intent_engine.models import (
    AmountConstraints,
    AuthorizationScope,
    AuthorizationScopeValue,
    CategoryConstraints,
    CurrencyInfo,
    CurrencySource,
    Evidence,
    GeographicConstraints,
    IntentMetadata,
    MerchantConstraints,
    StructuredIntent,
    TemporalConstraints,
    TransactionType,
)

# ── Helpers ────────────────────────────────────────────────────────


def _make_intent(**overrides) -> StructuredIntent:
    """Create a valid StructuredIntent for testing."""
    defaults = {
        "goal": "purchase",
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


def _make_proposal(**overrides) -> TransactionProposal:
    """Create a valid TransactionProposal for testing."""
    defaults = {
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "agent_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "intent_id": "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
        "transaction_type": TransactionType.PURCHASE,
        "amount": Decimal("3500"),
        "currency": "INR",
        "idempotency_key": "key-001",
    }
    defaults.update(overrides)
    return TransactionProposal(**defaults)


# ── Transaction Type ───────────────────────────────────────────────


class TestCompareTransactionType:
    def test_match_purchase(self):
        intent = _make_intent(transaction_type=TransactionType.PURCHASE)
        proposal = _make_proposal(transaction_type=TransactionType.PURCHASE)
        result = compare_transaction_type(intent, proposal)
        assert result.status == FieldStatus.MATCH
        assert result.severity == DriftSeverity.NONE

    def test_mismatch_critical(self):
        intent = _make_intent(transaction_type=TransactionType.PURCHASE)
        proposal = _make_proposal(transaction_type=TransactionType.TRANSFER)
        result = compare_transaction_type(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.CRITICAL

    def test_match_booking(self):
        intent = _make_intent(
            goal="booking",
            transaction_type=TransactionType.BOOKING,
        )
        proposal = _make_proposal(transaction_type=TransactionType.BOOKING)
        result = compare_transaction_type(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_refund(self):
        intent = _make_intent(
            goal="refund",
            transaction_type=TransactionType.REFUND,
        )
        proposal = _make_proposal(transaction_type=TransactionType.REFUND)
        result = compare_transaction_type(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_purchase_vs_booking(self):
        intent = _make_intent(transaction_type=TransactionType.PURCHASE)
        proposal = _make_proposal(transaction_type=TransactionType.BOOKING)
        result = compare_transaction_type(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_mismatch_subscription_vs_transfer(self):
        intent = _make_intent(
            goal="subscription",
            transaction_type=TransactionType.SUBSCRIPTION,
        )
        proposal = _make_proposal(transaction_type=TransactionType.TRANSFER)
        result = compare_transaction_type(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_match_all_types(self):
        for tt in TransactionType:
            intent = _make_intent(goal=tt.value, transaction_type=tt)
            proposal = _make_proposal(transaction_type=tt)
            result = compare_transaction_type(intent, proposal)
            assert result.status == FieldStatus.MATCH, f"Failed for {tt}"

    def test_mismatch_all_combinations(self):
        types = list(TransactionType)
        for i, t1 in enumerate(types):
            for j, t2 in enumerate(types):
                if i != j:
                    intent = _make_intent(goal=t1.value, transaction_type=t1)
                    proposal = _make_proposal(transaction_type=t2)
                    result = compare_transaction_type(intent, proposal)
                    assert result.status == FieldStatus.MISMATCH


# ── Amount ─────────────────────────────────────────────────────────


class TestCompareAmount:
    def test_match_within_max(self):
        intent = _make_intent(amount=AmountConstraints(max=4000))
        proposal = _make_proposal(amount=Decimal("3500"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH
        assert result.drift is None

    def test_match_exact_max(self):
        intent = _make_intent(amount=AmountConstraints(max=4000))
        proposal = _make_proposal(amount=Decimal("4000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_exceeds_max(self):
        intent = _make_intent(amount=AmountConstraints(max=4000))
        proposal = _make_proposal(amount=Decimal("4500"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.drift is not None
        assert result.drift.within_boundary is False
        assert result.drift.deviation_absolute == Decimal("500")
        assert result.drift.deviation_percent == Decimal("12.5")

    def test_mismatch_far_exceeds_max(self):
        intent = _make_intent(amount=AmountConstraints(max=4000))
        proposal = _make_proposal(amount=Decimal("8000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.drift is not None
        assert result.drift.deviation_percent == Decimal("100")

    def test_mismatch_below_min(self):
        intent = _make_intent(amount=AmountConstraints(min=1000))
        proposal = _make_proposal(amount=Decimal("500"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.drift is not None
        assert result.drift.within_boundary is False

    def test_match_within_range(self):
        intent = _make_intent(amount=AmountConstraints(min=1000, max=4000))
        proposal = _make_proposal(amount=Decimal("2500"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_exact_min_in_range(self):
        intent = _make_intent(amount=AmountConstraints(min=1000, max=4000))
        proposal = _make_proposal(amount=Decimal("1000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_exact_max_in_range(self):
        intent = _make_intent(amount=AmountConstraints(min=1000, max=4000))
        proposal = _make_proposal(amount=Decimal("4000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_above_range(self):
        intent = _make_intent(amount=AmountConstraints(min=1000, max=4000))
        proposal = _make_proposal(amount=Decimal("5000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_mismatch_below_range(self):
        intent = _make_intent(amount=AmountConstraints(min=1000, max=4000))
        proposal = _make_proposal(amount=Decimal("500"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_match_exact_amount(self):
        intent = _make_intent(amount=AmountConstraints(exact=4000))
        proposal = _make_proposal(amount=Decimal("4000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_exact_amount(self):
        intent = _make_intent(amount=AmountConstraints(exact=4000))
        proposal = _make_proposal(amount=Decimal("4100"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.drift is not None
        assert result.drift.authorized_boundary == "exact"

    def test_not_applicable_no_constraint(self):
        intent = _make_intent(amount=AmountConstraints())
        proposal = _make_proposal(amount=Decimal("5000"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_unknown_proposal_no_amount(self):
        intent = _make_intent(amount=AmountConstraints(max=4000))
        proposal = _make_proposal(amount=None)
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_match_min_only(self):
        intent = _make_intent(amount=AmountConstraints(min=1000))
        proposal = _make_proposal(amount=Decimal("1500"))
        result = compare_amount(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_severity_low_under_10_percent(self):
        assert _severity_from_deviation_percent(Decimal("5")) == DriftSeverity.LOW

    def test_severity_medium_10_to_25_percent(self):
        assert _severity_from_deviation_percent(Decimal("15")) == DriftSeverity.MEDIUM

    def test_severity_high_25_to_50_percent(self):
        assert _severity_from_deviation_percent(Decimal("30")) == DriftSeverity.HIGH

    def test_severity_critical_over_50_percent(self):
        assert _severity_from_deviation_percent(Decimal("60")) == DriftSeverity.CRITICAL

    def test_severity_none_at_zero(self):
        assert _severity_from_deviation_percent(Decimal("0")) == DriftSeverity.NONE

    def test_amount_evidence_preserved(self):
        evidence = Evidence(text_span="under ₹4,000", confidence=0.98)
        intent = _make_intent(
            amount=AmountConstraints(max=4000, evidence=evidence)
        )
        proposal = _make_proposal(amount=Decimal("4500"))
        result = compare_amount(intent, proposal)
        assert result.intent_evidence is not None
        assert result.intent_evidence["text_span"] == "under ₹4,000"


# ── Currency ───────────────────────────────────────────────────────


class TestCompareCurrency:
    def test_match_inr(self):
        intent = _make_intent(currency=CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT))
        proposal = _make_proposal(currency="INR")
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_case_insensitive(self):
        intent = _make_intent(currency=CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT))
        proposal = _make_proposal(currency="inr")
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_inr_vs_usd(self):
        intent = _make_intent(currency=CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT))
        proposal = _make_proposal(currency="USD")
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.HIGH

    def test_unknown_intent_currency(self):
        intent = _make_intent(currency=CurrencyInfo(code=None, source=CurrencySource.UNKNOWN))
        proposal = _make_proposal(currency="USD")
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_unknown_proposal_currency(self):
        intent = _make_intent(currency=CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT))
        proposal = _make_proposal(currency=None)
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_match_eur(self):
        intent = _make_intent(currency=CurrencyInfo(code="EUR", source=CurrencySource.EXPLICIT))
        proposal = _make_proposal(currency="EUR")
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_eur_vs_gbp(self):
        intent = _make_intent(currency=CurrencyInfo(code="EUR", source=CurrencySource.EXPLICIT))
        proposal = _make_proposal(currency="GBP")
        result = compare_currency(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_currency_evidence_preserved(self):
        evidence = Evidence(text_span="₹4,000", confidence=0.99)
        intent = _make_intent(
            currency=CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT, evidence=evidence)
        )
        proposal = _make_proposal(currency="INR")
        result = compare_currency(intent, proposal)
        assert result.intent_evidence is not None


# ── Category ───────────────────────────────────────────────────────


class TestCompareCategory:
    def test_match_exact(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["running shoes"])
        )
        proposal = _make_proposal(category="running shoes")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_case_insensitive(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["Running Shoes"])
        )
        proposal = _make_proposal(category="running shoes")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_specific_instance(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["running shoes"])
        )
        proposal = _make_proposal(category="nike running shoes")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_different_category(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["running shoes"])
        )
        proposal = _make_proposal(category="formal shoes")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_not_applicable_no_constraint(self):
        intent = _make_intent(category_constraints=CategoryConstraints())
        proposal = _make_proposal(category="anything")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_unknown_proposal_no_category(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["running shoes"])
        )
        proposal = _make_proposal(category=None)
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_match_multiple_items(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["running shoes", "sports shoes"]
            )
        )
        proposal = _make_proposal(category="sports shoes")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_partially_matching(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["laptop"])
        )
        proposal = _make_proposal(category="gaming chair")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_category_evidence_preserved(self):
        evidence = Evidence(text_span="black running shoes", confidence=0.95)
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["running shoes"], evidence=evidence
            )
        )
        proposal = _make_proposal(category="running shoes")
        result = compare_category(intent, proposal)
        assert result.intent_evidence is not None
        assert result.intent_evidence["text_span"] == "black running shoes"

    def test_match_whitespace_normalized(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["  running shoes  "])
        )
        proposal = _make_proposal(category="running shoes")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_empty_string_proposal(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["running shoes"])
        )
        proposal = _make_proposal(category="")
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_not_applicable_both_empty(self):
        intent = _make_intent(category_constraints=CategoryConstraints())
        proposal = _make_proposal(category=None)
        result = compare_category(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE


# ── Product Attributes ─────────────────────────────────────────────


class TestCompareProductAttributes:
    def test_match_color(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"], attributes={"color": "black"}
            )
        )
        proposal = _make_proposal(product_attributes={"color": "black"})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_color(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"], attributes={"color": "black"}
            )
        )
        proposal = _make_proposal(product_attributes={"color": "red"})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_unknown_proposal_no_attrs(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"], attributes={"color": "black"}
            )
        )
        proposal = _make_proposal(product_attributes={})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_not_applicable_no_constraint(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["shoes"])
        )
        proposal = _make_proposal(product_attributes={"color": "black"})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_match_multiple_attrs(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"],
                attributes={"color": "black", "size": "10"},
            )
        )
        proposal = _make_proposal(
            product_attributes={"color": "black", "size": "10"}
        )
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_one_attr_wrong(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"],
                attributes={"color": "black", "size": "10"},
            )
        )
        proposal = _make_proposal(
            product_attributes={"color": "black", "size": "12"}
        )
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_case_insensitive_attrs(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"], attributes={"color": "Black"}
            )
        )
        proposal = _make_proposal(product_attributes={"color": "black"})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_unknown_missing_one_attr(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"],
                attributes={"color": "black", "size": "10"},
            )
        )
        proposal = _make_proposal(product_attributes={"color": "black"})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_not_applicable_both_empty(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["shoes"])
        )
        proposal = _make_proposal(product_attributes={})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_match_brand(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(
                items=["shoes"], attributes={"brand": "Nike"}
            )
        )
        proposal = _make_proposal(product_attributes={"brand": "Nike"})
        result = compare_product_attributes(intent, proposal)
        assert result.status == FieldStatus.MATCH


# ── Merchant ───────────────────────────────────────────────────────


class TestCompareMerchant:
    def test_not_applicable_no_constraint(self):
        intent = _make_intent(merchant_constraints=MerchantConstraints())
        proposal = _make_proposal(merchant_name="Amazon")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_match_trusted(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(trust_required=True)
        )
        proposal = _make_proposal(merchant_name="Amazon", merchant_trusted=True)
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_untrusted(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(trust_required=True)
        )
        proposal = _make_proposal(merchant_name="UnknownShop", merchant_trusted=False)
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.HIGH

    def test_unknown_trust_status(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(trust_required=True)
        )
        proposal = _make_proposal(merchant_name="Amazon", merchant_trusted=None)
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_match_preferred(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(preferred=["Amazon", "Flipkart"])
        )
        proposal = _make_proposal(merchant_name="Amazon")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_not_preferred(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(preferred=["Amazon", "Flipkart"])
        )
        proposal = _make_proposal(merchant_name="eBay")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.MEDIUM

    def test_match_preferred_case_insensitive(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(preferred=["Amazon"])
        )
        proposal = _make_proposal(merchant_name="amazon")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_excluded(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(excluded=["AliExpress"])
        )
        proposal = _make_proposal(merchant_name="AliExpress")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.MEDIUM

    def test_match_not_excluded(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(excluded=["AliExpress"])
        )
        proposal = _make_proposal(merchant_name="Amazon")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_unknown_no_proposal_merchant(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(preferred=["Amazon"])
        )
        proposal = _make_proposal(merchant_name=None)
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_merchant_evidence_preserved(self):
        evidence = Evidence(text_span="from Amazon", confidence=0.95)
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(
                preferred=["Amazon"], evidence=evidence
            )
        )
        proposal = _make_proposal(merchant_name="Amazon")
        result = compare_merchant(intent, proposal)
        assert result.intent_evidence is not None

    def test_merchant_whitespace_normalized(self):
        intent = _make_intent(
            merchant_constraints=MerchantConstraints(preferred=[" Amazon "])
        )
        proposal = _make_proposal(merchant_name="amazon")
        result = compare_merchant(intent, proposal)
        assert result.status == FieldStatus.MATCH


# ── Geographic ─────────────────────────────────────────────────────


class TestCompareGeographic:
    def test_not_applicable_no_constraint(self):
        intent = _make_intent(geographic_constraints=GeographicConstraints())
        proposal = _make_proposal(country="IN", city="Bangalore")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_match_country(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(country="IN")
        )
        proposal = _make_proposal(country="IN")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_country_case_insensitive(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(country="in")
        )
        proposal = _make_proposal(country="IN")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_country(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(country="IN")
        )
        proposal = _make_proposal(country="US")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_unknown_proposal_no_country(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(country="IN")
        )
        proposal = _make_proposal(country=None)
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_match_city(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(city="Bangalore")
        )
        proposal = _make_proposal(city="Bangalore")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_city_case_insensitive(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(city="bangalore")
        )
        proposal = _make_proposal(city="Bangalore")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_city(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(city="Bangalore")
        )
        proposal = _make_proposal(city="Chennai")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_match_country_and_city(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(
                country="IN", city="Bangalore"
            )
        )
        proposal = _make_proposal(country="IN", city="Bangalore")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_country_matches_but_city_fails(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(
                country="IN", city="Bangalore"
            )
        )
        proposal = _make_proposal(country="IN", city="Chennai")
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.MISMATCH

    def test_unknown_city_not_specified(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(
                country="IN", city="Bangalore"
            )
        )
        proposal = _make_proposal(country="IN", city=None)
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_unknown_proposal_no_city(self):
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(city="Bangalore")
        )
        proposal = _make_proposal(city=None)
        result = compare_geographic(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_geographic_evidence_preserved(self):
        evidence = Evidence(text_span="in Bangalore", confidence=0.90)
        intent = _make_intent(
            geographic_constraints=GeographicConstraints(
                city="Bangalore", evidence=evidence
            )
        )
        proposal = _make_proposal(city="Bangalore")
        result = compare_geographic(intent, proposal)
        assert result.intent_evidence is not None


# ── Temporal ───────────────────────────────────────────────────────


class TestCompareTemporal:
    def test_not_applicable_no_constraint(self):
        intent = _make_intent(temporal_constraints=TemporalConstraints())
        proposal = _make_proposal(
            scheduled_at=datetime(2026, 8, 23, 10, 0, 0, tzinfo=UTC)
        )
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.NOT_APPLICABLE

    def test_match_before_deadline(self):
        deadline = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(deadline=deadline)
        )
        proposal = _make_proposal(
            scheduled_at=datetime(2026, 8, 23, 10, 0, 0, tzinfo=UTC)
        )
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_match_exact_deadline(self):
        deadline = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(deadline=deadline)
        )
        proposal = _make_proposal(scheduled_at=deadline)
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_after_deadline(self):
        deadline = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(deadline=deadline)
        )
        proposal = _make_proposal(
            scheduled_at=datetime(2026, 8, 26, 14, 0, 0, tzinfo=UTC)
        )
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.LOW

    def test_unknown_proposal_no_time(self):
        deadline = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(deadline=deadline)
        )
        proposal = _make_proposal(scheduled_at=None)
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_unknown_recurring(self):
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(recurring=True)
        )
        proposal = _make_proposal(
            scheduled_at=datetime(2026, 8, 23, 10, 0, 0, tzinfo=UTC)
        )
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_timezone_aware_comparison(self):
        from datetime import timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        deadline = datetime(2026, 8, 25, 12, 0, 0, tzinfo=ist)
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(deadline=deadline)
        )
        # Proposal is in UTC, before IST deadline
        proposal = _make_proposal(
            scheduled_at=datetime(2026, 8, 25, 6, 0, 0, tzinfo=UTC)
        )
        result = compare_temporal(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_temporal_evidence_preserved(self):
        deadline = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
        evidence = Evidence(text_span="before Friday", confidence=0.85)
        intent = _make_intent(
            temporal_constraints=TemporalConstraints(
                deadline=deadline, evidence=evidence
            )
        )
        proposal = _make_proposal(
            scheduled_at=datetime(2026, 8, 23, 10, 0, 0, tzinfo=UTC)
        )
        result = compare_temporal(intent, proposal)
        assert result.intent_evidence is not None


# ── Authorization Scope ────────────────────────────────────────────


class TestCompareAuthorizationScope:
    def test_unknown_null_intent_scope(self):
        intent = _make_intent(
            authorization_scope=AuthorizationScope(value=None)
        )
        proposal = _make_proposal(
            authorization_scope=AuthorizationScopeValue.SINGLE_USE
        )
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN

    def test_match_single_use(self):
        intent = _make_intent(
            authorization_scope=AuthorizationScope(
                value=AuthorizationScopeValue.SINGLE_USE
            )
        )
        proposal = _make_proposal(
            authorization_scope=AuthorizationScopeValue.SINGLE_USE
        )
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_scope_escalation(self):
        intent = _make_intent(
            authorization_scope=AuthorizationScope(
                value=AuthorizationScopeValue.SINGLE_USE
            )
        )
        proposal = _make_proposal(
            authorization_scope=AuthorizationScopeValue.RECURRING
        )
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.HIGH

    def test_match_recurring_to_single_use(self):
        intent = _make_intent(
            authorization_scope=AuthorizationScope(
                value=AuthorizationScopeValue.RECURRING
            )
        )
        proposal = _make_proposal(
            authorization_scope=AuthorizationScopeValue.SINGLE_USE
        )
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_mismatch_session_to_recurring_escalation(self):
        """Session → recurring is an escalation (mismatch)."""
        intent = _make_intent(
            authorization_scope=AuthorizationScope(
                value=AuthorizationScopeValue.SESSION
            )
        )
        proposal = _make_proposal(
            authorization_scope=AuthorizationScopeValue.RECURRING
        )
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.MISMATCH
        assert result.severity == DriftSeverity.HIGH

    def test_match_recurring(self):
        intent = _make_intent(
            authorization_scope=AuthorizationScope(
                value=AuthorizationScopeValue.RECURRING
            )
        )
        proposal = _make_proposal(
            authorization_scope=AuthorizationScopeValue.RECURRING
        )
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.MATCH

    def test_unknown_proposal_no_scope(self):
        intent = _make_intent(
            authorization_scope=AuthorizationScope(
                value=AuthorizationScopeValue.SINGLE_USE
            )
        )
        proposal = _make_proposal(authorization_scope=None)
        result = compare_authorization_scope(intent, proposal)
        assert result.status == FieldStatus.UNKNOWN
