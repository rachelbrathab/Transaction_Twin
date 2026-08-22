"""Currency resolution — determines currency with explicit tracking.

Hierarchy:
1. Explicit currency in user text
2. User/account configured default
3. Application default
4. Unknown
"""

import re

from app.services.intent_engine.models import CurrencyInfo, CurrencySource

# Currency symbols and codes → ISO 4217 mapping
_CURRENCY_MAP: dict[str, str] = {
    # INR
    "₹": "INR",
    "rs.": "INR",
    "rs": "INR",
    "inr": "INR",
    "rupees": "INR",
    "rupee": "INR",
    # USD
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    # EUR
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    # GBP
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
}

# Pattern to find currency symbols/codes in text
_SYMBOL_PATTERN = re.compile(
    r"₹|\$|€|£|"
    r"(?:RS\.?|INR|USD|EUR|GBP)\s|"
    r"(?:rupees?|dollars?|euros?|pounds?)\s",
    re.IGNORECASE,
)

# Pattern to find currency code as standalone word
_CODE_PATTERN = re.compile(
    r"\b(INR|USD|EUR|GBP)\b",
    re.IGNORECASE,
)

# Pattern to find currency symbol prefix
_SYMBOL_PREFIX_PATTERN = re.compile(
    r"(₹|\$|€|£)\s*[\d,\.]+",
)


def _extract_explicit_currency(text: str) -> str | None:
    """Extract explicit currency from text.

    Returns ISO 4217 code or None.
    """
    # Check symbols first (most reliable)
    match = _SYMBOL_PREFIX_PATTERN.search(text)
    if match:
        symbol = match.group(1)
        code = _CURRENCY_MAP.get(symbol)
        if code:
            return code

    # Check word patterns
    match = _SYMBOL_PATTERN.search(text)
    if match:
        matched_text = match.group(0).strip().lower()
        code = _CURRENCY_MAP.get(matched_text)
        if code:
            return code

    # Check standalone codes
    match = _CODE_PATTERN.search(text)
    if match:
        code = match.group(1).upper()
        if code in _CURRENCY_MAP.values():
            return code

    return None


def resolve_currency(
    canonical_request: str,
    user_default_currency: str | None = None,
    app_default_currency: str | None = None,
) -> CurrencyInfo:
    """Resolve currency using the approved hierarchy.

    Returns CurrencyInfo with explicit source tracking.
    """
    # 1. Explicit currency in user text
    explicit_code = _extract_explicit_currency(canonical_request)
    if explicit_code:
        # Find the evidence span
        evidence_span = _find_currency_evidence_span(canonical_request, explicit_code)
        return CurrencyInfo(
            code=explicit_code,
            source=CurrencySource.EXPLICIT,
            evidence={
                "text_span": evidence_span,
                "confidence": 0.99,
            }
            if evidence_span
            else None,
        )

    # 2. User/account configured default
    if user_default_currency and len(user_default_currency) == 3:
        return CurrencyInfo(
            code=user_default_currency.upper(),
            source=CurrencySource.USER_DEFAULT,
            evidence=None,
        )

    # 3. Application default
    if app_default_currency and len(app_default_currency) == 3:
        return CurrencyInfo(
            code=app_default_currency.upper(),
            source=CurrencySource.APP_DEFAULT,
            evidence=None,
        )

    # 4. Unknown
    return CurrencyInfo(
        code=None,
        source=CurrencySource.UNKNOWN,
        evidence=None,
    )


def _find_currency_evidence_span(text: str, code: str) -> str | None:
    """Find the text span that provides currency evidence."""
    # Try symbol prefix first
    match = _SYMBOL_PREFIX_PATTERN.search(text)
    if match:
        symbol = match.group(1)
        if _CURRENCY_MAP.get(symbol) == code:
            return match.group(0)

    # Try code pattern
    for pattern in [_CODE_PATTERN, _SYMBOL_PATTERN]:
        for match in pattern.finditer(text):
            matched_text = match.group(0).strip()
            if _CURRENCY_MAP.get(matched_text.lower()) == code:
                return matched_text

    return None
