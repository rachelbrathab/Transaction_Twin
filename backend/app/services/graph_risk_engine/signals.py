"""Graph Risk Engine signal extractors.

Each function takes a BuiltGraph and returns a NetworkSignal or None.
All extractors are pure functions — no I/O, no database, no side effects.
"""

from __future__ import annotations

from app.services.graph_risk_engine.constants import (
    CLUSTER_RISK_HIGH_THRESHOLD,
    CLUSTER_RISK_MEDIUM_THRESHOLD,
    CONCENTRATION_HIGH_THRESHOLD,
    CONCENTRATION_MEDIUM_THRESHOLD,
    CONFIDENCE_BY_PEER_COUNT,
    CONFIDENCE_BY_SIBLING_COUNT,
    CONFIDENCE_BY_TRANSACTION_COUNT,
    LOW_TRUST_THRESHOLD,
    MIN_PEERS_FOR_SHARED_RISK,
    MIN_SIBLINGS_FOR_CLUSTER_RISK,
    MIN_TRANSACTIONS_FOR_CONCENTRATION,
    PEER_RISK_HIGH_THRESHOLD,
    PEER_RISK_MEDIUM_THRESHOLD,
)
from app.services.graph_risk_engine.graph_builder import BuiltGraph
from app.services.graph_risk_engine.models import NetworkSignal, NetworkSignalType

# ── SHARED RISK EXPOSURE ───────────────────────────────────────────


def extract_shared_risk_exposure(graph: BuiltGraph) -> NetworkSignal | None:
    """Detect whether peer agents at the same merchants have low trust.

    NOTE (Sprint 9B): Decision.transaction_id is currently NULL for
    /transactions/decide outcomes. Therefore we cannot reliably join
    Transaction → Decision to determine if peer agents were BLOCKED.

    Instead, we use Agent.trust_score of peer agents as a proxy for
    merchant risk exposure. If most peers at a merchant have low trust,
    the merchant is potentially risky.

    When insufficient peer data is available, returns UNKNOWN (score=0,
    confidence=0) so the caller can skip this signal.
    """
    all_peers = []
    for peers in graph.merchant_peers.values():
        all_peers.extend(peers)

    # Need minimum peer data
    if len(all_peers) < MIN_PEERS_FOR_SHARED_RISK:
        return None  # UNKNOWN — insufficient data

    # Count peers with low trust
    low_trust_count = 0
    known_trust_count = 0
    for peer in all_peers:
        if peer.trust_score is not None:
            known_trust_count += 1
            if peer.trust_score < LOW_TRUST_THRESHOLD:
                low_trust_count += 1

    if known_trust_count == 0:
        return None  # UNKNOWN — no trust data available

    # Compute risk fraction
    risk_fraction = low_trust_count / known_trust_count

    # Map to score
    if risk_fraction >= PEER_RISK_HIGH_THRESHOLD:
        score = 0.60
        risk_level = "high"
    elif risk_fraction >= PEER_RISK_MEDIUM_THRESHOLD:
        score = 0.35
        risk_level = "medium"
    elif risk_fraction >= 0.10:
        score = 0.10
        risk_level = "low"
    else:
        score = 0.0
        risk_level = None

    # Confidence based on peer count
    confidence = _lookup_confidence(len(all_peers), CONFIDENCE_BY_PEER_COUNT)

    unique_peers = len({p.agent_id for p in all_peers})
    unique_merchants = len(graph.merchant_peers)

    what = (
        f"{low_trust_count} of {known_trust_count} peer agents at "
        f"{unique_merchants} shared merchant(s) have low trust"
    )
    why = (
        f"Peer agents transacting at the same merchants show "
        f"{risk_level or 'no'} risk indicators"
        if risk_level
        else "Peer agents at shared merchants have acceptable trust levels"
    )

    return NetworkSignal(
        signal_type=NetworkSignalType.SHARED_RISK_EXPOSURE,
        score=round(score, 4),
        confidence=round(confidence, 4),
        what=what,
        why=why,
        evidence={
            "low_trust_peers": low_trust_count,
            "known_trust_peers": known_trust_count,
            "risk_fraction": round(risk_fraction, 4),
            "unique_peer_agents": unique_peers,
            "shared_merchants": unique_merchants,
        },
        source_engine="graph_risk_engine",
        source_fields=["merchant_peer_records.trust_score"],
    )


# ── MERCHANT CONCENTRATION ─────────────────────────────────────────


def extract_merchant_concentration(graph: BuiltGraph) -> NetworkSignal | None:
    """Measure the agent's merchant transaction concentration.

    Compares the distribution of transactions across merchants.
    High concentration on a single merchant = higher risk.

    Returns None when insufficient transactions exist.
    """
    txns = graph.agent_transactions
    total = len(txns)

    if total < MIN_TRANSACTIONS_FOR_CONCENTRATION:
        return None  # UNKNOWN — insufficient data

    # Count transactions per merchant
    merchant_counts: dict[str, int] = {}
    for txn in txns:
        mid = txn.merchant_id or "_unknown_"
        merchant_counts[mid] = merchant_counts.get(mid, 0) + 1

    # Find the most-used merchant
    top_merchant_id = max(merchant_counts, key=lambda k: merchant_counts[k])
    top_count = merchant_counts[top_merchant_id]
    concentration = top_count / total if total > 0 else 0.0

    # Compare recent (last 20% of transactions by time) vs historical
    recent_count = max(1, total // 5)
    recent_txns = txns[-recent_count:]
    recent_merchant_counts: dict[str, int] = {}
    for txn in recent_txns:
        mid = txn.merchant_id or "_unknown_"
        recent_merchant_counts[mid] = recent_merchant_counts.get(mid, 0) + 1

    recent_top_count = max(recent_merchant_counts.values()) if recent_merchant_counts else 0
    recent_concentration = (
        recent_top_count / len(recent_txns) if recent_txns else 0.0
    )

    # Concentration shift: recent concentration vs overall
    concentration_shift = recent_concentration - concentration

    # Map to score
    # Base score from overall concentration
    if recent_concentration >= CONCENTRATION_HIGH_THRESHOLD:
        score = 0.40
    elif recent_concentration >= CONCENTRATION_MEDIUM_THRESHOLD:
        score = 0.20
    elif recent_concentration >= 0.40:
        score = 0.08
    else:
        score = 0.0

    # Boost if there's a significant concentration shift
    if concentration_shift > 0.20:
        score = min(score + 0.15, 0.60)
    elif concentration_shift > 0.10:
        score = min(score + 0.08, 0.40)

    # Confidence based on transaction count
    confidence = _lookup_confidence(total, CONFIDENCE_BY_TRANSACTION_COUNT)

    unique_merchants = len(merchant_counts)
    top_merchant_display = (
        top_merchant_id if top_merchant_id != "_unknown_" else "unknown"
    )

    what = (
        f"Agent's transactions are {recent_concentration:.0%} concentrated on "
        f"merchant {top_merchant_display} in recent activity "
        f"({unique_merchants} unique merchants across {total} transactions)"
    )
    why = (
        f"High merchant concentration ({recent_concentration:.0%}) indicates "
        f"potential coordinated or compromised activity"
        if recent_concentration >= CONCENTRATION_MEDIUM_THRESHOLD
        else "Merchant distribution is within normal parameters"
    )

    return NetworkSignal(
        signal_type=NetworkSignalType.MERCHANT_CONCENTRATION,
        score=round(score, 4),
        confidence=round(confidence, 4),
        what=what,
        why=why,
        evidence={
            "total_transactions": total,
            "unique_merchants": unique_merchants,
            "overall_concentration": round(concentration, 4),
            "recent_concentration": round(recent_concentration, 4),
            "concentration_shift": round(concentration_shift, 4),
            "top_merchant_id": top_merchant_display,
            "top_merchant_transactions": top_count,
        },
        source_engine="graph_risk_engine",
        source_fields=["agent_transactions.merchant_id"],
    )


# ── AGENT CLUSTER RISK ────────────────────────────────────────────


def extract_agent_cluster_risk(graph: BuiltGraph) -> NetworkSignal | None:
    """Analyze risk from sibling agents under the same user.

    If many sibling agents have low trust or are inactive,
    the current agent operates in a risky cluster.

    Returns None when no sibling agents exist.
    """
    siblings = graph.sibling_agents

    if len(siblings) < MIN_SIBLINGS_FOR_CLUSTER_RISK:
        return None  # UNKNOWN — no siblings

    # Count risky siblings
    risky_count = 0
    known_count = 0
    for sibling in siblings:
        known_count += 1
        is_risky = False
        if sibling.trust_score is not None and sibling.trust_score < LOW_TRUST_THRESHOLD:
            is_risky = True
        if sibling.status not in ("active",):
            is_risky = True
        if is_risky:
            risky_count += 1

    if known_count == 0:
        return None  # UNKNOWN

    risk_fraction = risky_count / known_count

    # Map to score
    if risk_fraction >= CLUSTER_RISK_HIGH_THRESHOLD:
        score = 0.50
        risk_level = "high"
    elif risk_fraction >= CLUSTER_RISK_MEDIUM_THRESHOLD:
        score = 0.25
        risk_level = "medium"
    elif risk_fraction >= 0.15:
        score = 0.08
        risk_level = "low"
    else:
        score = 0.0
        risk_level = None

    # Confidence based on sibling count
    confidence = _lookup_confidence(len(siblings), CONFIDENCE_BY_SIBLING_COUNT)

    what = (
        f"{risky_count} of {known_count} sibling agents under the same user "
        f"have low trust or inactive status"
    )
    why = (
        f"Agent operates in a cluster with {risk_level} risk indicators "
        f"from sibling agents"
        if risk_level
        else "Sibling agents show no significant risk indicators"
    )

    return NetworkSignal(
        signal_type=NetworkSignalType.AGENT_CLUSTER_RISK,
        score=round(score, 4),
        confidence=round(confidence, 4),
        what=what,
        why=why,
        evidence={
            "total_siblings": known_count,
            "risky_siblings": risky_count,
            "risk_fraction": round(risk_fraction, 4),
        },
        source_engine="graph_risk_engine",
        source_fields=["sibling_agents.trust_score", "sibling_agents.status"],
    )


# ── Helper ─────────────────────────────────────────────────────────


def _lookup_confidence(
    count: int,
    thresholds: list[tuple[int, float]],
) -> float:
    """Look up confidence from a count-based threshold table."""
    result = 0.0
    for threshold, conf in thresholds:
        if count >= threshold:
            result = conf
        else:
            break
    return result
