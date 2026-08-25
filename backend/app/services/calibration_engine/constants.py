"""Calibration Engine constants — deterministic-v1 calibration values.

All thresholds, parameters, and limits are defined here.
Changing calibration behavior requires editing this file only.
"""

# ── Time Windows ───────────────────────────────────────────────────

CURRENT_WINDOW_DAYS = 30
BASELINE_WINDOW_DAYS = 60
MAX_HISTORY_DAYS = 90

# ── Data Limits ────────────────────────────────────────────────────

MAX_DECISIONS = 1000
MAX_AGENTS = 500
MAX_POLICIES = 200

# ── Data Sufficiency Thresholds ────────────────────────────────────
# Deterministic-v1 calibration values.
# Chosen conservatively for a hackathon system with bounded history.

SUFFICIENCY_THRESHOLDS: list[tuple[int, str]] = [
    (100, "high"),
    (30, "moderate"),
    (10, "low"),
    (0, "insufficient"),
]

# ── Drift Detection Thresholds ─────────────────────────────────────
# These detect changes between baseline and current periods.

DRIFT_BLOCK_RATE_RATIO = 2.0       # > 2× baseline → drifting
DRIFT_REVIEW_RATE_RATIO = 1.5      # > 1.5× baseline → drifting
DRIFT_ALLOW_RATE_DECREASE = 0.30   # > 30% decrease → drifting
DRIFT_SIGNAL_SHIFT = 0.20          # > 20 percentage-point shift → drifting
DRIFT_POLICY_TRIGGER_RATIO = 2.0   # > 2× baseline → drifting

# Minimum sample sizes for drift detection
DRIFT_MIN_BASELINE = 10
DRIFT_MIN_CURRENT = 10

# ── Policy Analysis Thresholds ─────────────────────────────────────

POLICY_HIGH_TRIGGER_RATE = 0.50    # > 50% trigger rate → flagged
POLICY_MIN_EVALUATIONS = 5         # Minimum evals before flagging

# ── Agent Analysis Thresholds ──────────────────────────────────────

AGENT_UNSTABLE_REVIEW_RATE = 0.30  # > 30% review → unstable
AGENT_UNSTABLE_BLOCK_RATE = 0.10   # > 10% block → unstable

# ── Signal Analysis ────────────────────────────────────────────────

SIGNAL_SOURCES = [
    "validation", "policy", "drift", "trust", "risk", "intent"
]

# ── Version Metadata ───────────────────────────────────────────────

CALIBRATION_MODEL_VERSION = "calibration-v1"
