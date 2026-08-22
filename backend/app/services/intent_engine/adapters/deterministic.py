"""Deterministic adapter — conservative rule-based intent extraction.

Used when no LLM is available. Confidence capped at 0.70.
Only extracts what is explicitly present in the text.
Never invents values.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.services.intent_engine.adapters.base import AdapterResult, LLMAdapter, ProviderInfo
from app.services.intent_engine.prompts import DETERMINISTIC_PARSER_VERSION

# Amount patterns
_AMOUNT_EXACT_PATTERN = re.compile(
    r"(?:exactly|precisely)\s+(?:₹|\$|€|£|RS\.?\s?|INR\s|USD\s|EUR\s|GBP\s)?"
    r"\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_AMOUNT_MAX_PATTERNS = [
    re.compile(
        r"(?:under|below|less than|up to|max(?:imum)?(?:\s+of)?)\s+"
        r"(?:₹|\$|€|£|RS\.?\s?|INR\s|USD\s|EUR\s|GBP\s)?"
        r"\s*([\d,]+(?:\.\d+)?)\s*(?![kK])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:₹|\$|€|£|RS\.?\s?|INR\s|USD\s|EUR\s|GBP\s)?"
        r"\s*([\d,]+(?:\.\d+)?)\s*(?:or less|maximum|max)",
        re.IGNORECASE,
    ),
]
_AMOUNT_MIN_PATTERNS = [
    re.compile(
        r"(?:over|above|more than|at least|min(?:imum)?(?:\s+of)?)\s+"
        r"(?:₹|\$|€|£|RS\.?\s?|INR\s|USD\s|EUR\s|GBP\s)?"
        r"\s*([\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
]
_AMOUNT_BETWEEN_PATTERN = re.compile(
    r"between\s+(?:₹|\$|€|£|RS\.?\s?|INR\s|USD\s|EUR\s|GBP\s)?"
    r"\s*([\d,]+(?:\.\d+)?)"
    r"\s+(?:and|to|-)\s+"
    r"(?:₹|\$|€|£|RS\.?\s?|INR\s|USD\s|EUR\s|GBP\s)?"
    r"\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
# K-suffix amounts (e.g., 4k, 4K)
_K_AMOUNT_PATTERN = re.compile(r"([\d,]+)\s*[kK]\b")

# Goal detection
_GOAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "purchase": re.compile(
        r"\b(?:buy|purchase|order|get|shop|acquire)\b", re.IGNORECASE
    ),
    "booking": re.compile(
        r"\b(?:book|reserve|rent)\b", re.IGNORECASE
    ),
    "refund": re.compile(r"\b(?:refund|return|reimburse)\b", re.IGNORECASE),
    "subscription": re.compile(
        r"\b(?:subscribe|subscription|membership)\b", re.IGNORECASE
    ),
    "transfer": re.compile(
        r"\b(?:transfer|send|pay\s+to)\b", re.IGNORECASE
    ),
}

# Category keywords (basic — not exhaustive)
_CATEGORY_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    ("shoes", re.compile(r"\b(?:shoes?|sneakers?|footwear)\b", re.IGNORECASE)),
    ("electronics", re.compile(
        r"\b(?:laptop|phone|tablet|computer|device|earbuds|headphones)\b",
        re.IGNORECASE,
    )),
    ("clothing", re.compile(r"\b(?:shirt|pants|jacket|dress|clothes|clothing)\b", re.IGNORECASE)),
    ("hotel", re.compile(r"\b(?:hotel|hostel|lodge|resort|accommodation)\b", re.IGNORECASE)),
    ("flight", re.compile(r"\b(?:flight|airline|plane)\b", re.IGNORECASE)),
    ("groceries", re.compile(r"\b(?:groceries?|grocery|food)\b", re.IGNORECASE)),
    ("books", re.compile(r"\b(?:books?|novel|textbook)\b", re.IGNORECASE)),
]

# Attribute patterns
_COLOR_PATTERN = re.compile(
    r"\b(black|white|red|blue|green|yellow|grey|gray|brown|pink|purple|orange|navy|beige)\b",
    re.IGNORECASE,
)

# Merchant trust
_TRUST_PATTERN = re.compile(
    r"\b(?:trusted|verified|reliable|authentic|genuine)\s+(?:seller|merchant|store|shop|brand)",
    re.IGNORECASE,
)


def _parse_amount(text: str) -> float | None:
    """Parse a numeric amount from text, handling commas and K-suffix."""
    text = text.replace(",", "").strip()
    match = _K_AMOUNT_PATTERN.search(text)
    if match:
        return float(match.group(1).replace(",", "")) * 1000
    # Try direct parse
    nums = re.findall(r"[\d]+(?:\.\d+)?", text)
    if nums:
        return float(nums[0])
    return None


def _extract_amount_evidence_span(text: str, amount_value: float) -> str | None:
    """Find the text span that provides amount evidence."""
    for pattern in [_AMOUNT_EXACT_PATTERN, *_AMOUNT_MAX_PATTERNS, *_AMOUNT_MIN_PATTERNS]:
        match = pattern.search(text)
        if match:
            parsed = _parse_amount(match.group(1))
            if parsed is not None and abs(parsed - amount_value) < 0.01:
                return match.group(0).strip()
    return None


class DeterministicAdapter(LLMAdapter):
    """Rule-based intent parser. Conservative — only extracts explicit patterns.

    Confidence capped at 0.70.
    """

    CAP_CONFIDENCE = 0.70

    async def parse_intent(
        self,
        canonical_request: str,
        resolved_currency: str | None,
        transaction_type_hint: str | None,
        reference_timestamp: str,
        prompt_version: str,
    ) -> AdapterResult:
        start = time.monotonic()

        try:
            raw = self._extract(canonical_request, resolved_currency, transaction_type_hint)
            latency = int((time.monotonic() - start) * 1000)
            raw["metadata"]["parsing_latency_ms"] = latency
            return AdapterResult(
                success=True,
                raw_output=raw,
                provider_info=ProviderInfo(
                    provider="deterministic",
                    model="rule-based-v1",
                    latency_ms=latency,
                ),
            )
        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def _extract(
        self,
        text: str,
        resolved_currency: str | None,
        transaction_type_hint: str | None,
    ) -> dict[str, Any]:
        """Extract structured intent from text using rules."""
        # Goal
        goal = "purchase"  # default
        if transaction_type_hint:
            goal = transaction_type_hint
        else:
            for g, pattern in _GOAL_PATTERNS.items():
                if pattern.search(text):
                    goal = g
                    break

        # Amount
        amount_min = None
        amount_max = None
        amount_exact = None
        amount_evidence_span = None

        # Exact amount
        match = _AMOUNT_EXACT_PATTERN.search(text)
        if match:
            amount_exact = _parse_amount(match.group(1))
            amount_evidence_span = match.group(0).strip()

        # Between pattern
        if amount_exact is None:
            match = _AMOUNT_BETWEEN_PATTERN.search(text)
            if match:
                amount_min = _parse_amount(match.group(1))
                amount_max = _parse_amount(match.group(2))
                amount_evidence_span = match.group(0).strip()

        # K-suffix (check before max/min patterns to avoid 'under 4K' → 4)
        if amount_exact is None and amount_max is None and amount_min is None:
            match = _K_AMOUNT_PATTERN.search(text)
            if match:
                amount_max = float(match.group(1).replace(",", "")) * 1000
                amount_evidence_span = match.group(0).strip()

        # Max amount
        if amount_max is None and amount_exact is None:
            for pattern in _AMOUNT_MAX_PATTERNS:
                match = pattern.search(text)
                if match:
                    amount_max = _parse_amount(match.group(1))
                    amount_evidence_span = match.group(0).strip()
                    break

        # Min amount
        if amount_min is None and amount_exact is None:
            for pattern in _AMOUNT_MIN_PATTERNS:
                match = pattern.search(text)
                if match:
                    amount_min = _parse_amount(match.group(1))
                    if amount_evidence_span is None:
                        amount_evidence_span = match.group(0).strip()
                    break

        # Category
        items = []
        category_evidence = None
        for cat_name, cat_pattern in _CATEGORY_KEYWORDS:
            match = cat_pattern.search(text)
            if match:
                items.append(cat_name)
                category_evidence = match.group(0).strip()

        # Attributes (color)
        attributes = {}
        match = _COLOR_PATTERN.search(text)
        if match:
            attributes["color"] = match.group(1).lower()

        # Merchant trust
        trust_required = bool(_TRUST_PATTERN.search(text))
        merchant_evidence = None
        if trust_required:
            merchant_evidence = _TRUST_PATTERN.search(text).group(0).strip()  # type: ignore[union-attr]

        # Build result
        return {
            "goal": goal,
            "transaction_type": goal,
            "currency": {
                "code": resolved_currency,
                "source": "explicit" if resolved_currency else "unknown",
                "evidence": None,
            },
            "amount": {
                "min": amount_min,
                "max": amount_max,
                "exact": amount_exact,
                "evidence": {
                    "text_span": amount_evidence_span,
                    "confidence": 0.85,
                }
                if amount_evidence_span
                else None,
            },
            "category_constraints": {
                "items": items,
                "attributes": attributes,
                "confidence": 0.70 if items else 0.0,
                "evidence": {
                    "text_span": category_evidence,
                    "confidence": 0.80,
                }
                if category_evidence
                else None,
            },
            "merchant_constraints": {
                "trust_required": trust_required,
                "preferred": [],
                "excluded": [],
                "confidence": 0.80 if trust_required else 0.0,
                "evidence": {
                    "text_span": merchant_evidence,
                    "confidence": 0.85,
                }
                if merchant_evidence
                else None,
            },
            "geographic_constraints": {
                "country": None,
                "city": None,
                "radius_km": None,
                "confidence": 0.0,
                "evidence": None,
            },
            "temporal_constraints": {
                "deadline": None,
                "duration": None,
                "recurring": False,
                "confidence": 0.0,
                "evidence": None,
            },
            "authorization_scope": {
                "value": None,
                "evidence": None,
            },
            "metadata": {
                "parser_version": DETERMINISTIC_PARSER_VERSION,
                "model_provider": "deterministic",
                "model_name": "rule-based-v1",
                "extraction_method": "deterministic",
                "parsing_latency_ms": 0,
                "canonical_request": text,
                "reference_timestamp": "",
                "injection_detected": False,
            },
        }

    async def health_check(self) -> bool:
        return True

    def get_provider_info(self) -> ProviderInfo:
        return ProviderInfo(provider="deterministic", model="rule-based-v1")
