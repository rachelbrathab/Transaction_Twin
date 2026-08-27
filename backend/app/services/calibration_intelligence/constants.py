"""Calibration Intelligence constants.

All deterministic configuration values centralized here.
Changing calibration behavior requires editing this file only.
"""

from __future__ import annotations

# ── Version Metadata ───────────────────────────────────────────────

CALIBRATION_INTELLIGENCE_VERSION = "calibration-intelligence-v1"
CALIBRATION_VERSION_PREFIX = "calibration-v"

# ── Dataset Eligibility ────────────────────────────────────────────

# Feedback types that qualify as ground truth
ELIGIBLE_FEEDBACK_TYPES: frozenset[str] = frozenset({
    "correct_allow",
    "correct_block",
    "correct_review",
    "possible_false_positive",
    "possible_false_negative",
})

# Verification states that qualify
ELIGIBLE_VERIFICATION_STATES: frozenset[str] = frozenset({
    "verified",
})

# Minimum feedback confidence for eligibility
MIN_FEEDBACK_CONFIDENCE = 0.5

# ── Minimum Sample Sizes ───────────────────────────────────────────
# Below these thresholds, no recommendation is generated.

MIN_SAMPLES_DECISION_ACCURACY = 30
MIN_SAMPLES_FPR_FNR = 20
MIN_SAMPLES_RISK_CALIBRATION = 50
MIN_SAMPLES_POLICY_EFFECTIVENESS = 10
MIN_SAMPLES_AGENT_CALIBRATION = 10
MIN_SAMPLES_BEHAVIORAL = 20
MIN_SAMPLES_NETWORK = 20

# ── Thresholds for Recommendations ─────────────────────────────────

# False-positive rate above which a POLICY_REVIEW is recommended
FP_RATE_THRESHOLD_FOR_REVIEW = 0.30

# False-negative rate above which a WEIGHT_REVIEW is recommended
FN_RATE_THRESHOLD_FOR_REVIEW = 0.20

# Over-triggering rate above which POLICY_REVIEW is recommended
POLICY_OVER_TRIGGER_RATE = 0.80

# Low effectiveness below which POLICY_REVIEW is recommended
POLICY_LOW_EFFECTIVENESS = 0.50

# Over-risking: HIGH risk + correct_allow rate above this → WEIGHT_REVIEW
OVER_RISKING_THRESHOLD = 0.40

# Under-risking: LOW risk + false_negative rate above this → THRESHOLD_REVIEW
UNDER_RISKING_THRESHOLD = 0.15

# Agent reputation mismatch threshold
REPUTATION_MISMATCH_THRESHOLD = 5

# ── Data Sufficiency Thresholds ────────────────────────────────────

SUFFICIENCY_THRESHOLDS: list[tuple[int, str]] = [
    (100, "high"),
    (30, "moderate"),
    (10, "low"),
    (0, "insufficient"),
]

# ── Time Windows ───────────────────────────────────────────────────

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 90

# ── Existing Risk Engine Values (read-only reference) ──────────────
# These are imported from the risk engine for evidence context.
# Calibration Intelligence reads these but NEVER modifies them.

EXISTING_SIGNAL_WEIGHTS: dict[str, float] = {
    "intent_drift": 0.25,
    "amount_anomaly": 0.15,
    "agent_trust": 0.15,
    "merchant_trust": 0.10,
    "policy_interaction": 0.20,
    "velocity": 0.05,
    "data_quality": 0.00,
    "currency_mismatch": 0.05,
    "geographic_anomaly": 0.05,
}

EXISTING_RISK_LEVEL_THRESHOLDS: dict[str, float] = {
    "critical": 0.75,
    "high": 0.50,
    "medium": 0.25,
    "low": 0.00,
}

EXISTING_CONFIDENCE_REDUCTIONS: dict[str, float] = {
    "drift_missing": 0.15,
    "agent_trust_missing": 0.10,
    "merchant_trust_missing": 0.05,
    "velocity_missing": 0.05,
    "intent_confidence_missing": 0.10,
    "policy_missing": 0.10,
    "proposal_amount_missing": 0.05,
    "network_shared_risk": 0.15,
    "network_concentration": 0.10,
    "network_cluster_risk": 0.15,
    "behavioral_amount_anomaly": 0.15,
    "behavioral_frequency_anomaly": 0.10,
    "behavioral_merchant_anomaly": 0.10,
}
