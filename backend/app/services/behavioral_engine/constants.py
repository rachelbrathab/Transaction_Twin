"""Behavioral Engine constants — deterministic-v1 calibration values.

All thresholds, minimums, and parameters are defined here.
Changing behavior requires editing this file only.
"""

# ── Baseline Parameters ────────────────────────────────────────────

BASELINE_WINDOW_DAYS = 90
BASELINE_MAX_ROWS = 500

# ── Minimum Sample Sizes ──────────────────────────────────────────

MIN_SAMPLES_FOR_AMOUNT = 5
MIN_SAMPLES_FOR_FREQUENCY = 3
MIN_SAMPLES_FOR_FULL_CONFIDENCE = 20

# ── Amount Anomaly Thresholds ─────────────────────────────────────
# Z-score (MAD-based) to anomaly score mapping

AMOUNT_Z_THRESHOLDS: list[tuple[float, float]] = [
    (1.0, 0.00),   # Within normal range
    (2.0, 0.15),   # Mildly unusual
    (3.0, 0.35),   # Notably unusual
    (4.0, 0.55),   # Highly unusual
    (float("inf"), 0.75),  # Extremely unusual
]

# ── Frequency Anomaly Thresholds ──────────────────────────────────

FREQUENCY_SHORT_MULTIPLIER = 0.3   # < 30% of mean interval → concerning
FREQUENCY_LONG_MULTIPLIER = 3.0    # > 300% of mean interval → less penalized
FREQUENCY_SHORT_SCORE = 0.25       # Base score for unusually short interval
FREQUENCY_LONG_SCORE = 0.05        # Score for unusually long interval

# ── Merchant Anomaly Thresholds ───────────────────────────────────

MERCHANT_FREQUENT_THRESHOLD = 0.30  # > 30% of txns → familiar
MERCHANT_COMMON_THRESHOLD = 0.10    # > 10% of txns → known
MERCHANT_NEW_SCORE = 0.25           # New merchant anomaly
MERCHANT_RARE_SCORE = 0.10          # Known but rare
MERCHANT_COMMON_SCORE = 0.05        # Known and somewhat common
MERCHANT_FREQUENT_SCORE = 0.0       # Frequent and familiar

# ── Overall Score ─────────────────────────────────────────────────

# Use dominant dimension (max) rather than average
# This ensures one strong anomaly isn't diluted

# ── Confidence Parameters ─────────────────────────────────────────

CONFIDENCE_BY_SAMPLE_SIZE: list[tuple[int, float]] = [
    (0, 0.0),
    (1, 0.2),
    (3, 0.4),
    (5, 0.6),
    (10, 0.8),
    (20, 0.95),
]

# ── Risk Engine Confidence Reductions ─────────────────────────────

BEHAVIORAL_CONFIDENCE_REDUCTIONS: dict[str, float] = {
    "amount_anomaly": 0.15,
    "frequency_anomaly": 0.10,
    "merchant_anomaly": 0.10,
}

# ── Version Metadata ───────────────────────────────────────────────

BEHAVIORAL_MODEL_VERSION = "behavioral-v1"
