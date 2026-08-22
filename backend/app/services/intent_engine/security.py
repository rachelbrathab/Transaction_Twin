"""Security analysis — detects injection patterns in canonical request.

Detection does NOT automatically reject requests.
It produces security metadata for downstream logging and review.
The parser must still extract the actual user intent.
"""

import re

# Injection patterns (case-insensitive)
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous\s+)?rules", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\bdeveloper\s*:", re.IGNORECASE),
    re.compile(r"\badmin\s*:", re.IGNORECASE),
    re.compile(r"\broot\s*:", re.IGNORECASE),
    re.compile(r"<\|", re.IGNORECASE),
    re.compile(r"\|>", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"override\s+(?:all\s+)?restrictions", re.IGNORECASE),
    re.compile(r"bypass\s+(?:all\s+)?(?:safety|restrictions|rules)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"forget\s+(?:all|everything)", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"\[/INST\]", re.IGNORECASE),
    re.compile(r"<s>", re.IGNORECASE),
    re.compile(r"</s>", re.IGNORECASE),
]


class SecurityAnalysis:
    """Result of security analysis on a canonical request."""

    def __init__(
        self,
        injection_detected: bool,
        detected_patterns: list[str],
        canonical_request: str,
    ) -> None:
        self.injection_detected = injection_detected
        self.detected_patterns = detected_patterns
        self.canonical_request = canonical_request


def analyze_security(canonical_request: str) -> SecurityAnalysis:
    """Analyze canonical request for injection patterns.

    Detection does NOT reject the request. It flags suspicious patterns
    for logging and review. The parser must still extract user intent.
    """
    detected: list[str] = []

    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(canonical_request)
        if match:
            detected.append(match.group(0))

    return SecurityAnalysis(
        injection_detected=len(detected) > 0,
        detected_patterns=detected,
        canonical_request=canonical_request,
    )
