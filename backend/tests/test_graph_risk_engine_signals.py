"""Tests for Graph Risk Engine signal extractors."""

from app.services.graph_risk_engine.graph_builder import BuiltGraph, GraphBuilder
from app.services.graph_risk_engine.models import (
    AgentTransactionRecord,
    GraphContext,
    MerchantPeerRecord,
    NetworkSignalType,
    SiblingAgentRecord,
)
from app.services.graph_risk_engine.signals import (
    extract_agent_cluster_risk,
    extract_merchant_concentration,
    extract_shared_risk_exposure,
)


def _build_graph(**kwargs) -> BuiltGraph:
    """Helper to build a graph from keyword arguments."""
    ctx = GraphContext(
        target_agent_id=kwargs.get("agent_id", "agent-001"),
        target_user_id=kwargs.get("user_id", "user-001"),
        agent_transactions=kwargs.get("agent_transactions", []),
        merchant_peer_records=kwargs.get("merchant_peers", []),
        sibling_agents=kwargs.get("sibling_agents", []),
    )
    return GraphBuilder().build(ctx)


# ── SHARED RISK EXPOSURE ───────────────────────────────────────────


class TestSharedRiskExposure:
    """Tests for shared risk exposure signal."""

    def test_no_peers_returns_none(self):
        """No peer agents → UNKNOWN → None."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
        )
        signal = extract_shared_risk_exposure(graph)
        assert signal is None

    def test_insufficient_peers_returns_none(self):
        """Only 1 peer (< 2 minimum) → UNKNOWN → None."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            merchant_peers=[
                MerchantPeerRecord(agent_id="agent-002", merchant_id="m1", trust_score=0.8),
            ],
        )
        signal = extract_shared_risk_exposure(graph)
        assert signal is None

    def test_peers_with_no_trust_data_returns_none(self):
        """Peers exist but none have trust scores → UNKNOWN → None."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            merchant_peers=[
                MerchantPeerRecord(agent_id="agent-002", merchant_id="m1", trust_score=None),
                MerchantPeerRecord(agent_id="agent-003", merchant_id="m1", trust_score=None),
            ],
        )
        signal = extract_shared_risk_exposure(graph)
        assert signal is None

    def test_all_peers_trusted(self):
        """All peers have high trust → score 0.0."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            merchant_peers=[
                MerchantPeerRecord(agent_id="agent-002", merchant_id="m1", trust_score=0.8),
                MerchantPeerRecord(agent_id="agent-003", merchant_id="m1", trust_score=0.9),
                MerchantPeerRecord(agent_id="agent-004", merchant_id="m1", trust_score=0.85),
            ],
        )
        signal = extract_shared_risk_exposure(graph)
        assert signal is not None
        assert signal.signal_type == NetworkSignalType.SHARED_RISK_EXPOSURE
        assert signal.score == 0.0

    def test_all_peers_low_trust(self):
        """All peers have low trust → high score."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            merchant_peers=[
                MerchantPeerRecord(agent_id="agent-002", merchant_id="m1", trust_score=0.1),
                MerchantPeerRecord(agent_id="agent-003", merchant_id="m1", trust_score=0.2),
                MerchantPeerRecord(agent_id="agent-004", merchant_id="m1", trust_score=0.05),
            ],
        )
        signal = extract_shared_risk_exposure(graph)
        assert signal is not None
        assert signal.score == 0.60  # >= 0.70 fraction
        assert signal.confidence > 0.0

    def test_mixed_peer_trust(self):
        """Some peers low trust, some high → medium score."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            merchant_peers=[
                MerchantPeerRecord(agent_id="agent-002", merchant_id="m1", trust_score=0.1),
                MerchantPeerRecord(agent_id="agent-003", merchant_id="m1", trust_score=0.1),
                MerchantPeerRecord(agent_id="agent-004", merchant_id="m1", trust_score=0.8),
                MerchantPeerRecord(agent_id="agent-005", merchant_id="m1", trust_score=0.9),
            ],
        )
        signal = extract_shared_risk_exposure(graph)
        assert signal is not None
        assert 0.0 < signal.score <= 0.60

    def test_deterministic_output(self):
        """Same graph → same signal."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            merchant_peers=[
                MerchantPeerRecord(agent_id="agent-002", merchant_id="m1", trust_score=0.1),
                MerchantPeerRecord(agent_id="agent-003", merchant_id="m1", trust_score=0.1),
            ],
        )
        s1 = extract_shared_risk_exposure(graph)
        s2 = extract_shared_risk_exposure(graph)
        assert s1 is not None and s2 is not None
        assert s1.score == s2.score
        assert s1.confidence == s2.confidence


# ── MERCHANT CONCENTRATION ─────────────────────────────────────────


class TestMerchantConcentration:
    """Tests for merchant concentration signal."""

    def test_zero_transactions_returns_none(self):
        """No transactions → UNKNOWN → None."""
        graph = _build_graph()
        signal = extract_merchant_concentration(graph)
        assert signal is None

    def test_one_transaction_returns_none(self):
        """1 transaction (< 3 minimum) → UNKNOWN → None."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0,
                    created_at="2025-01-15T10:00:00Z",
                ),
            ],
        )
        signal = extract_merchant_concentration(graph)
        assert signal is None

    def test_two_transactions_returns_none(self):
        """2 transactions (< 3 minimum) → UNKNOWN → None."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0,
                    created_at="2025-01-15T10:00:00Z",
                ),
                AgentTransactionRecord(
                    transaction_id="t2", merchant_id="m1", amount=200.0,
                    created_at="2025-01-15T11:00:00Z",
                ),
            ],
        )
        signal = extract_merchant_concentration(graph)
        assert signal is None

    def test_diversified_merchants(self):
        """Many different merchants → low concentration score."""
        # Use 50 unique merchants so recent window (10 txns) is also diversified
        txns = [
            AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id=f"m{i}",
                amount=100.0,
                created_at=f"2025-01-{1 + i % 28:02d}T{(i // 28) + 10:02d}:00:00Z",
            )
            for i in range(50)
        ]
        graph = _build_graph(agent_transactions=txns)
        signal = extract_merchant_concentration(graph)
        assert signal is not None
        assert signal.score < 0.20  # Low concentration — diversified
        assert signal.signal_type == NetworkSignalType.MERCHANT_CONCENTRATION

    def test_concentrated_merchants(self):
        """Most transactions to one merchant, including recent → high concentration."""
        txns = []
        for i in range(10):
            # First 2 go to different merchants, last 8 all to m1
            merchant = f"m{i}" if i < 2 else "m1"
            txns.append(AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id=merchant,
                amount=100.0,
                created_at=f"2025-01-{1 + i:02d}T10:00:00Z",
            ))
        graph = _build_graph(agent_transactions=txns)
        signal = extract_merchant_concentration(graph)
        assert signal is not None
        assert signal.score >= 0.20  # Concentrated (recent 80% at m1)

    def test_recent_concentration_shift(self):
        """Historical diversification but recent concentration → higher score."""
        txns = []
        # 8 diversified historical transactions
        for i in range(8):
            txns.append(AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id=f"m{i}",
                amount=100.0,
                created_at=f"2025-01-{i + 1:02d}T10:00:00Z",
            ))
        # 2 recent transactions to same merchant
        txns.append(AgentTransactionRecord(
            transaction_id="t8",
            merchant_id="m_new",
            amount=500.0,
            created_at="2025-01-15T10:00:00Z",
        ))
        txns.append(AgentTransactionRecord(
            transaction_id="t9",
            merchant_id="m_new",
            amount=500.0,
            created_at="2025-01-16T10:00:00Z",
        ))
        graph = _build_graph(agent_transactions=txns)
        signal = extract_merchant_concentration(graph)
        assert signal is not None
        assert signal.score > 0.0  # At least some concentration

    def test_deterministic_output(self):
        """Same graph → same signal."""
        txns = [
            AgentTransactionRecord(
                transaction_id=f"t{i}",
                merchant_id="m1" if i < 7 else f"m{i}",
                amount=100.0,
                created_at=f"2025-01-{i + 1:02d}T10:00:00Z",
            )
            for i in range(10)
        ]
        graph = _build_graph(agent_transactions=txns)
        s1 = extract_merchant_concentration(graph)
        s2 = extract_merchant_concentration(graph)
        assert s1 is not None and s2 is not None
        assert s1.score == s2.score


# ── AGENT CLUSTER RISK ────────────────────────────────────────────


class TestAgentClusterRisk:
    """Tests for agent cluster risk signal."""

    def test_no_siblings_returns_none(self):
        """No sibling agents → UNKNOWN → None."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
        )
        signal = extract_agent_cluster_risk(graph)
        assert signal is None

    def test_all_siblings_healthy(self):
        """All siblings have high trust and active status → score 0.0."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="a2", trust_score=0.8, status="active"),
                SiblingAgentRecord(agent_id="a3", trust_score=0.9, status="active"),
            ],
        )
        signal = extract_agent_cluster_risk(graph)
        assert signal is not None
        assert signal.score == 0.0

    def test_all_siblings_risky(self):
        """All siblings have low trust or inactive → high score."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="a2", trust_score=0.1, status="active"),
                SiblingAgentRecord(agent_id="a3", trust_score=0.2, status="suspended"),
                SiblingAgentRecord(agent_id="a4", trust_score=0.05, status="active"),
            ],
        )
        signal = extract_agent_cluster_risk(graph)
        assert signal is not None
        assert signal.score >= 0.25

    def test_mixed_siblings(self):
        """Some siblings risky, some healthy → medium score."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="a2", trust_score=0.1, status="active"),
                SiblingAgentRecord(agent_id="a3", trust_score=0.8, status="active"),
                SiblingAgentRecord(agent_id="a4", trust_score=0.9, status="active"),
                SiblingAgentRecord(agent_id="a5", trust_score=0.85, status="active"),
            ],
        )
        signal = extract_agent_cluster_risk(graph)
        assert signal is not None
        assert 0.0 <= signal.score < 0.50

    def test_inactive_sibling_flagged(self):
        """Inactive sibling counts as risky."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="a2", trust_score=0.8, status="suspended"),
                SiblingAgentRecord(agent_id="a3", trust_score=0.8, status="active"),
            ],
        )
        signal = extract_agent_cluster_risk(graph)
        assert signal is not None
        assert signal.score > 0.0  # Suspended sibling counts as risky

    def test_deterministic_output(self):
        """Same graph → same signal."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="a2", trust_score=0.1, status="active"),
                SiblingAgentRecord(agent_id="a3", trust_score=0.8, status="active"),
            ],
        )
        s1 = extract_agent_cluster_risk(graph)
        s2 = extract_agent_cluster_risk(graph)
        assert s1 is not None and s2 is not None
        assert s1.score == s2.score
        assert s1.confidence == s2.confidence


# ── UNKNOWN SEMANTICS ──────────────────────────────────────────────


class TestUnknownSemantics:
    """Verify UNKNOWN semantics: insufficient data → 0 risk, reduced confidence."""

    def test_empty_graph_all_unknown(self):
        """Empty graph produces no signals (all UNKNOWN)."""
        graph = _build_graph()
        assert extract_shared_risk_exposure(graph) is None
        assert extract_merchant_concentration(graph) is None
        assert extract_agent_cluster_risk(graph) is None

    def test_insufficient_data_no_risk(self):
        """Insufficient data → None (not a risky signal)."""
        graph = _build_graph(
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="t1", merchant_id="m1", amount=100.0,
                    created_at="2025-01-15T10:00:00Z",
                ),
            ],
        )
        # Only 1 transaction → concentration UNKNOWN
        # No peers → shared risk UNKNOWN
        # No siblings → cluster risk UNKNOWN
        assert extract_merchant_concentration(graph) is None
        assert extract_shared_risk_exposure(graph) is None
        assert extract_agent_cluster_risk(graph) is None
