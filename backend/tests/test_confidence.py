"""Tests for confidence calculation — formula and boundary values."""


from app.services.intent_engine.ambiguity import Ambiguity, AmbiguitySeverity
from app.services.intent_engine.confidence import (
    DETERMINISTIC_CONFIDENCE_CAP,
    calculate_confidence,
)
from app.services.intent_engine.models import (
    AmountConstraints,
    AuthorizationScope,
    CategoryConstraints,
    CurrencyInfo,
    CurrencySource,
    Evidence,
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
        "currency": CurrencyInfo(
            code="INR",
            source=CurrencySource.EXPLICIT,
            evidence=Evidence(text_span="₹4,000", confidence=0.99),
        ),
        "amount": AmountConstraints(
            max=4000,
            evidence=Evidence(text_span="under ₹4,000", confidence=0.98),
        ),
        "category_constraints": CategoryConstraints(
            items=["running shoes"],
            attributes={"color": "black"},
            confidence=0.95,
            evidence=Evidence(text_span="black running shoes", confidence=0.95),
        ),
        "merchant_constraints": MerchantConstraints(
            trust_required=True,
            confidence=0.80,
            evidence=Evidence(text_span="trusted seller", confidence=0.92),
        ),
        "geographic_constraints": GeographicConstraints(),
        "temporal_constraints": TemporalConstraints(),
        "authorization_scope": AuthorizationScope(),
        "metadata": IntentMetadata(
            parser_version="test",
            extraction_method="deterministic",
            canonical_request="Buy shoes",
            reference_timestamp="2026-01-01T00:00:00Z",
        ),
    }
    defaults.update(overrides)
    return StructuredIntent(**defaults)


class TestConfidenceCalculation:
    def test_high_confidence_full_input(self):
        intent = _make_intent()
        conf = calculate_confidence(intent, [], is_deterministic=False)
        assert conf >= 0.50
        assert conf <= 1.0

    def test_low_confidence_empty_input(self):
        intent = _make_intent(
            amount=AmountConstraints(),
            category_constraints=CategoryConstraints(),
            merchant_constraints=MerchantConstraints(),
            currency=CurrencyInfo(code=None, source=CurrencySource.UNKNOWN),
        )
        ambs = [Ambiguity(field="x", severity=AmbiguitySeverity.REQUIRED, message="test")]
        conf = calculate_confidence(intent, ambs, is_deterministic=False)
        assert conf < 0.50

    def test_clamped_to_0(self):
        intent = _make_intent(
            amount=AmountConstraints(),
            category_constraints=CategoryConstraints(),
            merchant_constraints=MerchantConstraints(),
            currency=CurrencyInfo(code=None, source=CurrencySource.UNKNOWN),
        )
        many_ambs = [
            Ambiguity(field=f"f{i}", severity=AmbiguitySeverity.REQUIRED, message="x")
            for i in range(10)
        ]
        conf = calculate_confidence(intent, many_ambs, is_deterministic=False)
        assert conf >= 0.0

    def test_clamped_to_1(self):
        intent = _make_intent()
        conf = calculate_confidence(intent, [], is_deterministic=False)
        assert conf <= 1.0

    def test_deterministic_cap(self):
        intent = _make_intent()
        conf = calculate_confidence(intent, [], is_deterministic=True)
        assert conf <= DETERMINISTIC_CONFIDENCE_CAP
        assert DETERMINISTIC_CONFIDENCE_CAP == 0.70

    def test_required_ambiguity_penalty(self):
        intent = _make_intent()
        conf_no_amb = calculate_confidence(intent, [], is_deterministic=False)
        ambs = [Ambiguity(field="x", severity=AmbiguitySeverity.REQUIRED, message="y")]
        conf_with_amb = calculate_confidence(intent, ambs, is_deterministic=False)
        assert conf_with_amb < conf_no_amb

    def test_recommended_ambiguity_penalty_smaller(self):
        intent = _make_intent()
        conf_req = calculate_confidence(
            intent,
            [Ambiguity(field="x", severity=AmbiguitySeverity.REQUIRED, message="y")],
            is_deterministic=False,
        )
        conf_rec = calculate_confidence(
            intent,
            [Ambiguity(field="x", severity=AmbiguitySeverity.RECOMMENDED, message="y")],
            is_deterministic=False,
        )
        assert conf_rec > conf_req

    def test_exact_amount_highest_amount_clarity(self):
        intent = _make_intent(amount=AmountConstraints(exact=4000))
        conf = calculate_confidence(intent, [], is_deterministic=False)
        assert conf > 0

    def test_confidence_is_float(self):
        intent = _make_intent()
        conf = calculate_confidence(intent, [], is_deterministic=False)
        assert isinstance(conf, float)
