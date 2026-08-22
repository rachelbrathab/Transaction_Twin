"""Tests for ambiguity detection — required/recommended/optional classification."""


from app.services.intent_engine.ambiguity import detect_ambiguities, has_required_ambiguities
from app.services.intent_engine.models import (
    AmbiguitySeverity,
    AmountConstraints,
    AuthorizationScope,
    CategoryConstraints,
    CurrencyInfo,
    CurrencySource,
    GeographicConstraints,
    GoalType,
    IntentMetadata,
    MerchantConstraints,
    StructuredIntent,
    TemporalConstraints,
    TransactionType,
)


def _make_intent(**overrides) -> StructuredIntent:
    defaults = {
        "goal": GoalType.PURCHASE,
        "transaction_type": TransactionType.PURCHASE,
        "currency": CurrencyInfo(code="INR", source=CurrencySource.EXPLICIT),
        "amount": AmountConstraints(),
        "category_constraints": CategoryConstraints(),
        "merchant_constraints": MerchantConstraints(),
        "geographic_constraints": GeographicConstraints(),
        "temporal_constraints": TemporalConstraints(),
        "authorization_scope": AuthorizationScope(),
        "metadata": IntentMetadata(
            parser_version="test",
            extraction_method="deterministic",
            canonical_request="test",
            reference_timestamp="2026-01-01T00:00:00Z",
        ),
    }
    defaults.update(overrides)
    return StructuredIntent(**defaults)


class TestAmbiguityDetection:
    def test_purchase_missing_category(self):
        intent = _make_intent()
        ambs = detect_ambiguities(intent)
        fields = [a.field for a in ambs]
        assert "category_constraints" in fields
        assert any(a.severity == AmbiguitySeverity.REQUIRED for a in ambs)

    def test_purchase_with_category_no_ambiguity_for_category(self):
        intent = _make_intent(
            category_constraints=CategoryConstraints(items=["shoes"]),
        )
        ambs = detect_ambiguities(intent)
        cat_ambiguities = [a for a in ambs if a.field == "category_constraints"]
        assert len(cat_ambiguities) == 0

    def test_booking_missing_destination(self):
        intent = _make_intent(
            goal=GoalType.BOOKING,
            transaction_type=TransactionType.BOOKING,
        )
        ambs = detect_ambiguities(intent)
        fields = [a.field for a in ambs]
        assert "geographic_constraints" in fields

    def test_currency_unknown_with_amount(self):
        intent = _make_intent(
            currency=CurrencyInfo(code=None, source=CurrencySource.UNKNOWN),
            amount=AmountConstraints(max=4000),
        )
        ambs = detect_ambiguities(intent)
        fields = [a.field for a in ambs]
        assert "currency" in fields

    def test_currency_unknown_without_amount(self):
        intent = _make_intent(
            currency=CurrencyInfo(code=None, source=CurrencySource.UNKNOWN),
            amount=AmountConstraints(),
        )
        ambs = detect_ambiguities(intent)
        fields = [a.field for a in ambs]
        assert "currency" not in fields

    def test_has_required_ambiguities_true(self):
        ambs = [
            {"field": "x", "severity": AmbiguitySeverity.REQUIRED, "message": "test"}
        ]
        from app.services.intent_engine.models import Ambiguity

        ambiguity_list = [Ambiguity(**a) for a in ambs]
        assert has_required_ambiguities(ambiguity_list) is True

    def test_has_required_ambiguities_false(self):
        from app.services.intent_engine.models import Ambiguity

        ambs = [
            Ambiguity(
                field="x",
                severity=AmbiguitySeverity.RECOMMENDED,
                message="test",
            )
        ]
        assert has_required_ambiguities(ambs) is False

    def test_subscription_missing_duration(self):
        intent = _make_intent(
            goal=GoalType.SUBSCRIPTION,
            transaction_type=TransactionType.SUBSCRIPTION,
            category_constraints=CategoryConstraints(items=["news"]),
        )
        ambs = detect_ambiguities(intent)
        fields = [a.field for a in ambs]
        assert "temporal_constraints" in fields
