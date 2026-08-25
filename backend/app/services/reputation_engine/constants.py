"""Reputation Engine constants — deterministic-v1 calibration values.

All weights, thresholds, and scoring parameters are defined here.
Changing reputation behavior requires editing this file only.
"""

from app.services.reputation_engine.models import ReputationDimension, TrustLevel

# ── Dimension Weights ──────────────────────────────────────────────
# Weights sum to 1.0.

DIMENSION_WEIGHTS: dict[ReputationDimension, float] = {
    ReputationDimension.SUCCESS_RATE: 0.30,
    ReputationDimension.POLICY_COMPLIANCE: 0.25,
    ReputationDimension.DRIFT_BEHAVIOR: 0.15,
    ReputationDimension.RISK_PROFILE: 0.15,
    ReputationDimension.CONSISTENCY: 0.05,
    ReputationDimension.LONGEVITY: 0.05,
    ReputationDimension.AMOUNT_BEHAVIOR: 0.05,
}

_weight_sum = sum(DIMENSION_WEIGHTS.values())
assert abs(_weight_sum - 1.0) < 1e-9, (
    f"Dimension weights must sum to 1.0, got {_weight_sum}"
)

# ── Trust Level Thresholds ────────────────────────────────────────
# Deterministic-v1 calibration values.

TRUST_LEVEL_THRESHOLDS: list[tuple[float, TrustLevel]] = [
    (0.70, TrustLevel.HIGH),
    (0.40, TrustLevel.MEDIUM),
    (0.00, TrustLevel.LOW),
]

# ── Change Detection ──────────────────────────────────────────────
# Threshold for detecting meaningful reputation change.

CHANGE_THRESHOLD = 0.05
CHANGE_STABLE_THRESHOLD = 0.05  # abs(delta) < this → STABLE

# ── Confidence Thresholds ─────────────────────────────────────────
# Minimum transactions for full confidence in each dimension.

CONFIDENCE_THRESHOLDS: dict[str, int] = {
    "success_rate_full": 20,
    "policy_compliance_full": 10,
    "drift_behavior_full": 10,
    "consistency_full": 15,
    "amount_behavior_full": 10,
}

# ── History Window ────────────────────────────────────────────────

HISTORY_WINDOW_DAYS = 90
HISTORY_WINDOW_RECENT_DAYS = 30
MAX_HISTORY_ROWS = 1000

# ── Version Metadata ──────────────────────────────────────────────

REPUTATION_MODEL_VERSION = "reputation-v1"
REPUTATION_EVALUATOR_VERSION = "reputation-v1"
REPUTATION_FEATURE_VERSION = "v1"

# ── Derived Trust Score Mapping ───────────────────────────────────
# Maps reputation overall_score to Agent.trust_score equivalent.
# These are used when deciding whether to update the legacy trust_score.

LEGACY_TRUST_SCORE_FLOOR = 0.1
LEGACY_TRUST_SCORE_CEILING = 0.95
