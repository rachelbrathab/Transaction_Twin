"""Tests for deterministic fallback parser — extraction and fallback behavior."""

import pytest

from app.services.intent_engine.adapters.deterministic import DeterministicAdapter


@pytest.fixture
def adapter():
    return DeterministicAdapter()


class TestDeterministicExtraction:
    @pytest.mark.asyncio
    async def test_purchase_shoes(self, adapter):
        result = await adapter.parse_intent(
            "Buy black running shoes under ₹4,000",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["goal"] == "purchase"
        assert result.raw_output["transaction_type"] == "purchase"
        assert result.raw_output["currency"]["code"] == "INR"
        assert result.raw_output["amount"]["max"] == 4000.0
        assert "shoes" in result.raw_output["category_constraints"]["items"]
        assert result.raw_output["category_constraints"]["attributes"]["color"] == "black"

    @pytest.mark.asyncio
    async def test_trust_required(self, adapter):
        result = await adapter.parse_intent(
            "Buy from a trusted seller under ₹4,000",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["merchant_constraints"]["trust_required"] is True

    @pytest.mark.asyncio
    async def test_k_suffix_amount(self, adapter):
        result = await adapter.parse_intent(
            "Buy shoes under 4K",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["amount"]["max"] == 4000.0

    @pytest.mark.asyncio
    async def test_exact_amount(self, adapter):
        result = await adapter.parse_intent(
            "Buy shoes exactly ₹4,000",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["amount"]["exact"] == 4000.0

    @pytest.mark.asyncio
    async def test_between_amounts(self, adapter):
        result = await adapter.parse_intent(
            "Buy shoes between ₹2,000 and ₹4,000",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["amount"]["min"] == 2000.0
        assert result.raw_output["amount"]["max"] == 4000.0

    @pytest.mark.asyncio
    async def test_booking_intent(self, adapter):
        result = await adapter.parse_intent(
            "Book a hotel for tomorrow",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["goal"] == "booking"

    @pytest.mark.asyncio
    async def test_explicit_transaction_type_hint(self, adapter):
        result = await adapter.parse_intent(
            "Buy shoes",
            "INR", "refund", "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.success is True
        assert result.raw_output["goal"] == "refund"

    @pytest.mark.asyncio
    async def test_authorization_scope_null_by_default(self, adapter):
        result = await adapter.parse_intent(
            "Buy shoes under ₹4,000",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.raw_output["authorization_scope"]["value"] is None

    @pytest.mark.asyncio
    async def test_evidence_spans_present(self, adapter):
        result = await adapter.parse_intent(
            "Buy black running shoes under ₹4,000",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        raw = result.raw_output
        assert raw["amount"]["evidence"] is not None
        assert raw["category_constraints"]["evidence"] is not None

    @pytest.mark.asyncio
    async def test_no_amount_no_evidence(self, adapter):
        result = await adapter.parse_intent(
            "Buy shoes",
            "INR", None, "2026-01-01T00:00:00Z", "deterministic-v1",
        )
        assert result.raw_output["amount"]["evidence"] is None

    @pytest.mark.asyncio
    async def test_confidence_cap(self, adapter):
        """Deterministic adapter confidence should be capped at 0.70."""
        assert adapter.CAP_CONFIDENCE == 0.70

    @pytest.mark.asyncio
    async def test_health_check(self, adapter):
        assert await adapter.health_check() is True
