"""Tests for Graph Builder — in-memory graph construction."""

from app.services.graph_risk_engine.graph_builder import GraphBuilder
from app.services.graph_risk_engine.models import (
    AgentTransactionRecord,
    GraphContext,
    MerchantPeerRecord,
    SiblingAgentRecord,
)


class TestGraphBuilderEmpty:
    """Tests for empty/unavailable graph construction."""

    def test_empty_graph(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[],
        )
        graph = builder.build(ctx)
        assert graph.statistics.total_agent_transactions == 0
        assert graph.statistics.unique_merchants == 0

    def test_unavailable_graph(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            graph_available=False,
        )
        graph = builder.build(ctx)
        assert graph.statistics.total_agent_transactions == 0
        assert len(graph.agent_transactions) == 0


class TestGraphBuilderTransactions:
    """Tests for transaction graph construction."""

    def test_single_transaction(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="txn-001",
                    merchant_id="merch-001",
                    amount=100.0,
                    created_at="2025-01-15T10:00:00Z",
                ),
            ],
        )
        graph = builder.build(ctx)
        assert graph.statistics.total_agent_transactions == 1
        assert graph.statistics.unique_merchants == 1
        assert "merch-001" in graph.merchant_transactions

    def test_multiple_merchants(self):
        builder = GraphBuilder()
        txns = [
            AgentTransactionRecord(
                transaction_id=f"txn-{i:03d}",
                merchant_id=f"merch-{i % 3:03d}",
                amount=100.0 * (i + 1),
                created_at=f"2025-01-{15 + i:02d}T10:00:00Z",
            )
            for i in range(10)
        ]
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=txns,
        )
        graph = builder.build(ctx)
        assert graph.statistics.total_agent_transactions == 10
        assert graph.statistics.unique_merchants == 3

    def test_deterministic_sorting(self):
        """Same input always produces same graph structure."""
        builder = GraphBuilder()
        txns = [
            AgentTransactionRecord(
                transaction_id="txn-002",
                merchant_id="merch-001",
                amount=200.0,
                created_at="2025-01-15T12:00:00Z",
            ),
            AgentTransactionRecord(
                transaction_id="txn-001",
                merchant_id="merch-001",
                amount=100.0,
                created_at="2025-01-15T10:00:00Z",
            ),
        ]
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=txns,
        )
        graph1 = builder.build(ctx)
        graph2 = builder.build(ctx)
        t1_id_g1 = graph1.agent_transactions[0].transaction_id
        t1_id_g2 = graph2.agent_transactions[0].transaction_id
        assert t1_id_g1 == t1_id_g2
        t2_id_g1 = graph1.agent_transactions[1].transaction_id
        t2_id_g2 = graph2.agent_transactions[1].transaction_id
        assert t2_id_g1 == t2_id_g2

    def test_unknown_merchant_handled(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="txn-001",
                    merchant_id=None,
                    amount=100.0,
                ),
            ],
        )
        graph = builder.build(ctx)
        assert graph.statistics.unique_merchants == 0  # None merchant not counted


class TestGraphBuilderPeers:
    """Tests for merchant peer graph construction."""

    def test_merchant_peers_grouped(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="txn-001",
                    merchant_id="merch-001",
                    amount=100.0,
                ),
            ],
            merchant_peer_records=[
                MerchantPeerRecord(
                    agent_id="agent-002",
                    merchant_id="merch-001",
                    trust_score=0.5,
                ),
                MerchantPeerRecord(
                    agent_id="agent-003",
                    merchant_id="merch-001",
                    trust_score=0.8,
                ),
                MerchantPeerRecord(
                    agent_id="agent-004",
                    merchant_id="merch-002",
                    trust_score=0.2,
                ),
            ],
        )
        graph = builder.build(ctx)
        assert graph.statistics.total_merchant_peers == 3
        assert graph.statistics.unique_peer_agents == 3
        assert len(graph.merchant_peers.get("merch-001", [])) == 2
        assert len(graph.merchant_peers.get("merch-002", [])) == 1


class TestGraphBuilderSiblings:
    """Tests for sibling agent graph construction."""

    def test_siblings_sorted_deterministically(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="txn-001",
                    merchant_id="merch-001",
                    amount=100.0,
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="agent-003", name="C"),
                SiblingAgentRecord(agent_id="agent-001", name="A"),
                SiblingAgentRecord(agent_id="agent-002", name="B"),
            ],
        )
        graph = builder.build(ctx)
        assert graph.sibling_agents[0].agent_id == "agent-001"
        assert graph.sibling_agents[1].agent_id == "agent-002"
        assert graph.sibling_agents[2].agent_id == "agent-003"
        assert graph.statistics.sibling_agent_count == 3

    def test_no_siblings(self):
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="txn-001",
                    merchant_id="merch-001",
                    amount=100.0,
                ),
            ],
        )
        graph = builder.build(ctx)
        assert graph.statistics.sibling_agent_count == 0
        assert len(graph.sibling_agents) == 0


class TestGraphBuilderDeterminism:
    """Tests for deterministic graph construction."""

    def test_same_input_same_output(self):
        """Prove determinism: identical context → identical graph."""
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            agent_transactions=[
                AgentTransactionRecord(
                    transaction_id="txn-001",
                    merchant_id="merch-001",
                    amount=100.0,
                    created_at="2025-01-15T10:00:00Z",
                ),
                AgentTransactionRecord(
                    transaction_id="txn-002",
                    merchant_id="merch-002",
                    amount=200.0,
                    created_at="2025-01-15T11:00:00Z",
                ),
            ],
            merchant_peer_records=[
                MerchantPeerRecord(
                    agent_id="agent-002",
                    merchant_id="merch-001",
                    trust_score=0.5,
                ),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="agent-002", name="B"),
            ],
        )
        graph1 = builder.build(ctx)
        graph2 = builder.build(ctx)
        s1 = graph1.statistics
        s2 = graph2.statistics
        assert s1.total_agent_transactions == s2.total_agent_transactions
        assert graph1.statistics.unique_merchants == graph2.statistics.unique_merchants
        assert graph1.statistics.total_merchant_peers == graph2.statistics.total_merchant_peers

    def test_output_from_graph_builder_class(self):
        """GraphBuilder produces BuiltGraph, not raw dicts."""
        builder = GraphBuilder()
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
        )
        from app.services.graph_risk_engine.graph_builder import BuiltGraph
        graph = builder.build(ctx)
        assert isinstance(graph, BuiltGraph)
