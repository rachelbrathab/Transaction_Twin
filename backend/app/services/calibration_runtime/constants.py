"""Calibration Runtime constants.

Defines safe bounds and allowed parameter names for runtime calibration.

All values here are derived from the existing Risk Engine constants
and define the valid range for calibration-adjusted parameters.
"""

from __future__ import annotations

# ── Allowed Parameter Names ──────────────────────────────────────
# Only these parameter names may appear in a calibration version's
# parameter_snapshot. Unknown names are rejected.

ALLOWED_SIGNAL_WEIGHT_PARAMS: frozenset[str] = frozenset({
    "intent_drift",
    "amount_anomaly",
    "agent_trust",
    "merchant_trust",
    "policy_interaction",
    "velocity",
    "data_quality",
    "currency_mismatch",
    "geographic_anomaly",
})

ALLOWED_RISK_THRESHOLD_PARAMS: frozenset[str] = frozenset({
    "critical",
    "high",
    "medium",
    "low",
})

ALLOWED_CONFIDENCE_REDUCTION_PARAMS: frozenset[str] = frozenset({
    "drift_missing",
    "agent_trust_missing",
    "merchant_trust_missing",
    "velocity_missing",
    "intent_confidence_missing",
    "policy_missing",
    "proposal_amount_missing",
    "network_shared_risk",
    "network_concentration",
    "network_cluster_risk",
    "behavioral_amount_anomaly",
    "behavioral_frequency_anomaly",
    "behavioral_merchant_anomaly",
})

ALLOWED_CONFIDENCE_BOUNDS: frozenset[str] = frozenset({
    "confidence_floor",
    "confidence_ceiling",
})

# ── Parameter Category Keys ──────────────────────────────────────
# Keys used in parameter_snapshot to group parameters.

CATEGORY_SIGNAL_WEIGHTS = "signal_weights"
CATEGORY_RISK_THRESHOLDS = "risk_level_thresholds"
CATEGORY_CONFIDENCE_REDUCTIONS = "confidence_reductions"
CATEGORY_CONFIDENCE_BOUNDS = "confidence_bounds"

ALLOWED_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_SIGNAL_WEIGHTS,
    CATEGORY_RISK_THRESHOLDS,
    CATEGORY_CONFIDENCE_REDUCTIONS,
    CATEGORY_CONFIDENCE_BOUNDS,
})

# ── Safe Bounds ──────────────────────────────────────────────────

MIN_SIGNAL_WEIGHT = 0.0
MAX_SIGNAL_WEIGHT = 1.0
SIGNAL_WEIGHT_SUM_TOLERANCE = 1e-6

MIN_RISK_THRESHOLD = 0.0
MAX_RISK_THRESHOLD = 1.0

MIN_CONFIDENCE_REDUCTION = 0.0
MAX_CONFIDENCE_REDUCTION = 0.5

MIN_CONFIDENCE_FLOOR = 0.0
MAX_CONFIDENCE_FLOOR = 0.5

MIN_CONFIDENCE_CEILING = 0.5
MAX_CONFIDENCE_CEILING = 1.0

# ── Existing Defaults (read-only reference) ──────────────────────
# These mirror the Risk Engine constants for validation and fallback.
# This module NEVER modifies the actual Risk Engine constants.

DEFAULT_SIGNAL_WEIGHTS: dict[str, float] = {
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

DEFAULT_RISK_LEVEL_THRESHOLDS: dict[str, float] = {
    "critical": 0.75,
    "high": 0.50,
    "medium": 0.25,
    "low": 0.00,
}

DEFAULT_CONFIDENCE_REDUCTIONS: dict[str, float] = {
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

DEFAULT_CONFIDENCE_FLOOR = 0.1
DEFAULT_CONFIDENCE_CEILING = 1.0
