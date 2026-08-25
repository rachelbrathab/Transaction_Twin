"""Risk Engine constants — deterministic-v1 calibration values.

All weights, thresholds, and correlation groups are defined here.
Changing risk behavior requires editing this file only.
"""

from app.services.risk_engine.models import RiskLevel, RiskSignalType

# ── Signal Weights ─────────────────────────────────────────────────
# Weights sum to 1.0 excluding DATA_QUALITY (weight 0.0).
# DATA_QUALITY only affects confidence, never the risk score.

SIGNAL_WEIGHTS: dict[RiskSignalType, float] = {
    RiskSignalType.INTENT_DRIFT: 0.25,
    RiskSignalType.AMOUNT_ANOMALY: 0.15,
    RiskSignalType.AGENT_TRUST: 0.15,    # Used when reputation unavailable
    RiskSignalType.MERCHANT_TRUST: 0.10,
    RiskSignalType.POLICY_INTERACTION: 0.20,
    RiskSignalType.VELOCITY: 0.05,
    RiskSignalType.DATA_QUALITY: 0.00,
    RiskSignalType.CURRENCY_MISMATCH: 0.05,
    RiskSignalType.GEOGRAPHIC_ANOMALY: 0.05,
}
# NOTE (Sprint 8): When agent_reputation_available == True,
# AGENT_BEHAVIOR replaces AGENT_TRUST — only one trust signal
# is ever emitted per evaluation. AGENT_BEHAVIOR uses the same
# weight as AGENT_TRUST (0.15). It is NOT listed separately
# in SIGNAL_WEIGHTS to preserve Sprint 7 calibration.

# Verify weights sum to 1.0 (excluding DATA_QUALITY)
_score_weights = {k: v for k, v in SIGNAL_WEIGHTS.items() if v > 0}
assert abs(sum(_score_weights.values()) - 1.0) < 1e-9, (
    f"Score weights must sum to 1.0, got {sum(_score_weights.values())}"
)

# ── Correlation Groups ─────────────────────────────────────────────
# When multiple signals belong to the same group,
# the second signal's contribution is discounted.

CORRELATION_GROUPS: dict[str, list[RiskSignalType]] = {
    "drift_amount": [
        RiskSignalType.INTENT_DRIFT,
        RiskSignalType.AMOUNT_ANOMALY,
    ],
    "trust": [
        # Sprint 8: Only ONE of AGENT_TRUST or AGENT_BEHAVIOR is ever
        # emitted per evaluation (mutual exclusion in signal extractors).
        # Both are listed here so the group applies regardless of which
        # trust path is active.
        RiskSignalType.AGENT_TRUST,
        RiskSignalType.AGENT_BEHAVIOR,
        RiskSignalType.MERCHANT_TRUST,
    ],
    "geographic": [
        RiskSignalType.GEOGRAPHIC_ANOMALY,
        RiskSignalType.CURRENCY_MISMATCH,
    ],
}

# Discount factors per position within a correlation group.
# Position 0 = first signal in group (full weight).
# Position 1+ = subsequent signals (discounted).
GROUP_DISCOUNTS: dict[str, list[float]] = {
    "drift_amount": [1.0, 0.6],
    "trust": [1.0, 0.7],
    "geographic": [1.0, 0.5],
}

# ── Risk Level Thresholds ──────────────────────────────────────────
# deterministic-v1 calibration values.
# Selected so that:
#   - A single moderate signal (contribution ~0.25, weight 0.20) stays LOW
#   - Two strong signals or one dominant signal cross into MEDIUM/HIGH
#   - Critical drift (0.65) alone pushes into CRITICAL territory

RISK_LEVEL_THRESHOLDS: list[tuple[float, RiskLevel]] = [
    (0.75, RiskLevel.CRITICAL),
    (0.50, RiskLevel.HIGH),
    (0.25, RiskLevel.MEDIUM),
    (0.00, RiskLevel.LOW),
]

# ── Confidence Reductions ──────────────────────────────────────────
# Applied when specific context fields are missing.

CONFIDENCE_REDUCTIONS: dict[str, float] = {
    "drift_missing": 0.15,
    "agent_trust_missing": 0.10,
    "merchant_trust_missing": 0.05,
    "velocity_missing": 0.05,
    "intent_confidence_missing": 0.10,
    "policy_missing": 0.10,
    "proposal_amount_missing": 0.05,
    # Sprint 9: Network risk confidence reductions
    "network_shared_risk": 0.15,
    "network_concentration": 0.10,
    "network_cluster_risk": 0.15,
    # Sprint 10: Behavioral anomaly confidence reductions
    "behavioral_amount_anomaly": 0.15,
    "behavioral_frequency_anomaly": 0.10,
    "behavioral_merchant_anomaly": 0.10,
}

CONFIDENCE_FLOOR = 0.1
CONFIDENCE_CEILING = 1.0

# ── Dominant Signal Threshold ──────────────────────────────────────
# If any post-correlation signal has contribution >= this,
# apply dominant-signal boost to the overall score.

DOMINANT_SIGNAL_THRESHOLD = 0.5
DOMINANT_SIGNAL_MAX_WEIGHT = 0.6
DOMINANT_SIGNAL_MEAN_WEIGHT = 0.4

# ── Version Metadata ───────────────────────────────────────────────

RISK_MODEL_VERSION = "deterministic-v1"
EVALUATOR_VERSION = "risk-v1"
FEATURE_VERSION = "v1"
