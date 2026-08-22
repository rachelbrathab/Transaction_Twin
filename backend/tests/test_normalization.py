"""Tests for normalization module — canonical request derivation."""

import pytest

from app.services.intent_engine.normalization import normalize_request


class TestNormalization:
    def test_original_unchanged(self):
        """original_request must remain exactly as provided."""
        original = "Buy black running shoes under ₹4,000"
        result = normalize_request(original)
        assert result.original_request == original

    def test_canonical_basic(self):
        result = normalize_request("  Buy shoes  ")
        assert result.canonical_request == "Buy shoes"

    def test_nfkc_normalization(self):
        """NFKC normalization should handle unicode."""
        # Full-width digit 1
        original = "Buy\uFF11shoes"
        result = normalize_request(original)
        assert result.canonical_request == "Buy1shoes"

    def test_zero_width_removal(self):
        original = "Buy\u200bshoes"
        result = normalize_request(original)
        assert result.canonical_request == "Buyshoes"

    def test_control_char_removal(self):
        original = "Buy\x00shoes"
        result = normalize_request(original)
        assert result.canonical_request == "Buyshoes"

    def test_newline_preserved(self):
        original = "Line1\nLine2"
        result = normalize_request(original)
        assert "\n" in result.canonical_request

    def test_tab_preserved(self):
        original = "Col1\tCol2"
        result = normalize_request(original)
        assert "\t" in result.canonical_request

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_request("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            normalize_request("   ")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            normalize_request("x" * 6000)

    def test_was_modified_true(self):
        result = normalize_request("  hello  ")
        assert result.was_modified is True

    def test_was_modified_false(self):
        result = normalize_request("hello")
        assert result.was_modified is False

    def test_cyrillic_text_normalized(self):
        original = "\u0410\u0411\u0412"  # Cyrillic АБВ
        result = normalize_request(original)
        assert result.canonical_request == "\u0410\u0411\u0412"

    def test_indian_rupee_preserved(self):
        original = "Buy shoes ₹4,000"
        result = normalize_request(original)
        assert "₹" in result.canonical_request
