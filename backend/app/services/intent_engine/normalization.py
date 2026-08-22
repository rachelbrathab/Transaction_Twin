"""Normalization module — derives canonical request from original.

The original_request is NEVER modified.
Security analysis and parsing operate on the canonical copy.
"""

import re
import unicodedata

# Maximum allowed request length
MAX_REQUEST_LENGTH = 5000

# Zero-width characters to strip
_ZERO_WIDTH_PATTERN = re.compile(
    "[\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e]"
)

# Control characters to strip (except newline/tab which may be meaningful)
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class NormalizationResult:
    """Result of normalizing a user request.

    Attributes:
        original_request: Verbatim user text, never modified.
        canonical_request: NFKC-normalized, zero-width-stripped copy.
        was_modified: Whether canonical differs from original.
    """

    def __init__(
        self,
        original_request: str,
        canonical_request: str,
        was_modified: bool,
    ) -> None:
        self.original_request = original_request
        self.canonical_request = canonical_request
        self.was_modified = was_modified


def normalize_request(original_request: str) -> NormalizationResult:
    """Derive a canonical request from the original.

    The original_request is preserved exactly as provided.
    The canonical_request is:
    - NFKC-normalized
    - Zero-width characters removed
    - Control characters removed (except newline/tab)
    - Stripped of leading/trailing whitespace
    """
    if not original_request or not original_request.strip():
        msg = "original_request must not be empty"
        raise ValueError(msg)

    if len(original_request) > MAX_REQUEST_LENGTH:
        msg = f"original_request exceeds maximum length of {MAX_REQUEST_LENGTH}"
        raise ValueError(msg)

    # Step 1: NFKC unicode normalization
    normalized = unicodedata.normalize("NFKC", original_request)

    # Step 2: Remove zero-width characters
    normalized = _ZERO_WIDTH_PATTERN.sub("", normalized)

    # Step 3: Remove control characters (keep newline and tab)
    normalized = _CONTROL_CHAR_PATTERN.sub("", normalized)

    # Step 4: Strip leading/trailing whitespace
    canonical = normalized.strip()

    was_modified = canonical != original_request

    return NormalizationResult(
        original_request=original_request,
        canonical_request=canonical,
        was_modified=was_modified,
    )
