"""Graph Risk Engine constants — deterministic-v1 calibration values.

All limits, thresholds, and scoring parameters are defined here.
Changing graph risk behavior requires editing this file only.
"""

# ── Graph Construction Limits ──────────────────────────────────────

MAX_HISTORY_ROWS = 500
GRAPH_WINDOW_DAYS = 90
MAX_SIBLING_AGENTS = 50
MAX_MERCHANT_AGENTS = 100
MAX_GRAPH_NODES = 200

# ── Minimum Data Thresholds ────────────────────────────────────────

MIN_TRANSACTIONS_FOR_CONCENTRATION = 3
MIN_TRANSACTIONS_FOR_FULL_CONFIDENCE = 10
MIN_TRANSACTIONS_FOR_MODERATE_CONFIDENCE = 5

# Minimum peer agents for shared risk exposure to be meaningful
MIN_PEERS_FOR_SHARED_RISK = 2

# Minimum sibling agents for cluster risk to be meaningful
MIN_SIBLINGS_FOR_CLUSTER_RISK = 1

# ── Confidence Thresholds ──────────────────────────────────────────

# Based on transaction count
CONFIDENCE_BY_TRANSACTION_COUNT: list[tuple[int, float]] = [
    (0, 0.0),
    (1, 0.3),
    (3, 0.5),
    (5, 0.7),
    (10, 0.9),
    (20, 1.0),
]

# Based on peer agent count
CONFIDENCE_BY_PEER_COUNT: list[tuple[int, float]] = [
    (0, 0.0),
    (1, 0.3),
    (3, 0.5),
    (5, 0.7),
    (10, 1.0),
]

# Based on sibling agent count
CONFIDENCE_BY_SIBLING_COUNT: list[tuple[int, float]] = [
    (0, 0.0),
    (1, 0.3),
    (3, 0.6),
    (5, 0.8),
    (10, 1.0),
]

# ── Concentration Thresholds ───────────────────────────────────────

# Herfindahl-style: ratio of most-used merchant transactions / total
CONCENTRATION_LOW_THRESHOLD = 0.40
CONCENTRATION_MEDIUM_THRESHOLD = 0.60
CONCENTRATION_HIGH_THRESHOLD = 0.80

# ── Trust-Based Peer Risk Thresholds ──────────────────────────────

# Fraction of peer agents with low trust that constitutes risk
PEER_RISK_LOW_THRESHOLD = 0.30
PEER_RISK_MEDIUM_THRESHOLD = 0.50
PEER_RISK_HIGH_THRESHOLD = 0.70

# Trust score below which an agent is considered "low trust"
LOW_TRUST_THRESHOLD = 0.30

# ── Agent Cluster Risk Thresholds ─────────────────────────────────

# Fraction of sibling agents with low trust / inactive status
CLUSTER_RISK_LOW_THRESHOLD = 0.30
CLUSTER_RISK_MEDIUM_THRESHOLD = 0.50
CLUSTER_RISK_HIGH_THRESHOLD = 0.70

# ── Network Risk Confidence Reductions ─────────────────────────────
# Applied to Risk Engine confidence when network risk is available.

NETWORK_CONFIDENCE_REDUCTIONS: dict[str, float] = {
    "shared_risk_concerning": 0.15,
    "concentration_high": 0.10,
    "cluster_risk_concerning": 0.15,
}

# ── Version Metadata ───────────────────────────────────────────────

GRAPH_RISK_MODEL_VERSION = "graph-risk-v1"
