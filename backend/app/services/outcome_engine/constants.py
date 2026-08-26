"""Outcome Engine constants.

All deterministic configuration values centralized here.
"""

from __future__ import annotations

# ── Model version ──────────────────────────────────────────────────

OUTCOME_ENGINE_VERSION = "outcome-v1"
FEEDBACK_VERSION = "feedback-v1"

# ── Clock skew tolerance ───────────────────────────────────────────

# Allow 5 minutes of clock skew between event timestamps
CLOCK_SKEW_TOLERANCE_SECONDS = 300

# ── Sequence number bounds ─────────────────────────────────────────

MAX_SEQUENCE_NUMBER = 1000

# ── Idempotency ────────────────────────────────────────────────────

# If both provider and external_event_id are present, use them for idempotency
# Otherwise fall back to (transaction_id, event_type, source) tuple

# ── Feedback confidence thresholds ─────────────────────────────────

# Strong evidence required for false positive/negative classification
STRONG_EVIDENCE_CONFIDENCE = 0.8
MODERATE_EVIDENCE_CONFIDENCE = 0.5
WEAK_EVIDENCE_CONFIDENCE = 0.3

# ── Verification rules ─────────────────────────────────────────────

# Sources that may produce VERIFIED events automatically
TRUSTED_SOURCES_FOR_VERIFICATION = frozenset({
    "payment_provider",
    "admin",
})

# Sources that produce PENDING events by default
DEFAULT_PENDING_SOURCES = frozenset({
    "user",
    "merchant",
    "simulator",
})

# ── Feedback classification confidence ──────────────────────────────

# When outcome is VERIFIED
VERIFIED_CONFIDENCE = 0.9

# When outcome is PENDING
PENDING_CONFIDENCE = 0.5

# When outcome is UNVERIFIED
UNVERIFIED_CONFIDENCE = 0.2
