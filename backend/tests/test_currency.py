"""Tests for currency resolution — hierarchy and evidence."""


from app.services.intent_engine.currency import resolve_currency
from app.services.intent_engine.models import CurrencySource


class TestCurrencyResolution:
    def test_explicit_inr_symbol(self):
        c = resolve_currency("Buy shoes under ₹4,000")
        assert c.code == "INR"
        assert c.source == CurrencySource.EXPLICIT
        assert c.evidence is not None

    def test_explicit_usd_symbol(self):
        c = resolve_currency("Buy shoes under $100")
        assert c.code == "USD"
        assert c.source == CurrencySource.EXPLICIT

    def test_explicit_eur_symbol(self):
        c = resolve_currency("Buy shoes for €50")
        assert c.code == "EUR"
        assert c.source == CurrencySource.EXPLICIT

    def test_explicit_gbp_symbol(self):
        c = resolve_currency("Buy shoes for £30")
        assert c.code == "GBP"
        assert c.source == CurrencySource.EXPLICIT

    def test_explicit_code_inr(self):
        c = resolve_currency("Buy shoes INR 4000")
        assert c.code == "INR"
        assert c.source == CurrencySource.EXPLICIT

    def test_explicit_code_usd(self):
        c = resolve_currency("Buy shoes USD 100")
        assert c.code == "USD"
        assert c.source == CurrencySource.EXPLICIT

    def test_user_default(self):
        c = resolve_currency(
            "Buy shoes", user_default_currency="INR"
        )
        assert c.code == "INR"
        assert c.source == CurrencySource.USER_DEFAULT
        assert c.evidence is None

    def test_app_default(self):
        c = resolve_currency(
            "Buy shoes", app_default_currency="USD"
        )
        assert c.code == "USD"
        assert c.source == CurrencySource.APP_DEFAULT

    def test_user_default_over_app_default(self):
        c = resolve_currency(
            "Buy shoes",
            user_default_currency="EUR",
            app_default_currency="USD",
        )
        assert c.code == "EUR"
        assert c.source == CurrencySource.USER_DEFAULT

    def test_unknown_no_defaults(self):
        c = resolve_currency("Buy shoes under 4000")
        assert c.code is None
        assert c.source == CurrencySource.UNKNOWN

    def test_explicit_beats_default(self):
        c = resolve_currency(
            "Buy shoes for $100", user_default_currency="INR"
        )
        assert c.code == "USD"
        assert c.source == CurrencySource.EXPLICIT

    def test_evidence_span_contains_symbol(self):
        c = resolve_currency("Buy shoes ₹4,000")
        assert c.evidence is not None
        assert "₹" in c.evidence.text_span

    def test_no_amount_currency_still_resolved(self):
        c = resolve_currency("Buy shoes from trusted seller")
        # No currency mentioned, so unknown
        assert c.source == CurrencySource.UNKNOWN
