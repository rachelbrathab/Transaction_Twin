"""Tests for Graph Risk Engine domain models."""

from app.services.graph_risk_engine.models import (
    AgentTransactionRecord,
    GraphContext,
    GraphEdgeType,
    GraphNodeType,
    GraphStatistics,
    MerchantPeerRecord,
    NetworkRiskResult,
    NetworkSignal,
    NetworkSignalType,
    SiblingAgentRecord,
)


class TestNetworkSignalType:
    """Tests for NetworkSignalType enum."""

    def test_all_types_exist(self):
        assert NetworkSignalType.SHARED_RISK_EXPOSURE == "shared_risk_exposure"
        assert NetworkSignalType.MERCHANT_CONCENTRATION == "merchant_concentration"
        assert NetworkSignalType.AGENT_CLUSTER_RISK == "agent_cluster_risk"

    def test_three_types(self):
        assert len(NetworkSignalType) == 3


class TestGraphNodeAndEdgeTypes:
    """Tests for graph type enums."""

    def test_node_types(self):
        assert GraphNodeType.AGENT == "agent"
        assert GraphNodeType.MERCHANT == "merchant"
        assert GraphNodeType.TRANSACTION == "transaction"

    def test_edge_types(self):
        assert GraphEdgeType.EXECUTED == "executed"
        assert GraphEdgeType.VENDED_AT == "vended_at"


class TestAgentTransactionRecord:
    """Tests for AgentTransactionRecord model."""

    def test_valid_record(self):
        record = AgentTransactionRecord(
            transaction_id="txn-001",
            merchant_id="merch-001",
            amount=1000.0,
            currency="INR",
            transaction_type="purchase",
            created_at="2025-01-15T10:00:00Z",
        )
        assert record.transaction_id == "txn-001"
        assert record.amount == 1000.0

    def test_defaults(self):
        record = AgentTransactionRecord(transaction_id="txn-002", amount=50.0)
        assert record.merchant_id is None
        assert record.amount == 50.0
        assert record.currency == "INR"

    def test_negative_amount_rejected(self):
        import pytest
        with pytest.raises(Exception):
            AgentTransactionRecord(transaction_id="txn-003", amount=-100.0)


class TestMerchantPeerRecord:
    """Tests for MerchantPeerRecord model."""

    def test_valid_record(self):
        record = MerchantPeerRecord(
            agent_id="agent-001",
            merchant_id="merch-001",
            trust_score=0.5,
            transaction_count=5,
            latest_transaction_at="2025-01-15T10:00:00Z",
        )
        assert record.agent_id == "agent-001"
        assert record.trust_score == 0.5

    def test_defaults(self):
        record = MerchantPeerRecord(agent_id="agent-002", merchant_id="merch-002")
        assert record.trust_score is None
        assert record.transaction_count == 0

    def test_negative_count_rejected(self):
        import pytest
        with pytest.raises(Exception):
            MerchantPeerRecord(agent_id="agent-003", transaction_count=-1)


class TestSiblingAgentRecord:
    """Tests for SiblingAgentRecord model."""

    def test_valid_record(self):
        record = SiblingAgentRecord(
            agent_id="agent-001",
            name="Sibling Agent",
            trust_score=0.8,
            status="active",
            transaction_count=10,
        )
        assert record.name == "Sibling Agent"
        assert record.status == "active"

    def test_defaults(self):
        record = SiblingAgentRecord(agent_id="agent-002")
        assert record.trust_score is None
        assert record.status == "active"


class TestGraphContext:
    """Tests for GraphContext model."""

    def test_empty_context(self):
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
        )
        assert ctx.graph_available is True
        assert len(ctx.agent_transactions) == 0
        assert len(ctx.merchant_peer_records) == 0
        assert len(ctx.sibling_agents) == 0

    def test_unavailable_context(self):
        ctx = GraphContext(
            target_agent_id="agent-001",
            target_user_id="user-001",
            graph_available=False,
        )
        assert ctx.graph_available is False

    def test_full_context(self):
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
                MerchantPeerRecord(agent_id="agent-002", merchant_id="merch-001"),
            ],
            sibling_agents=[
                SiblingAgentRecord(agent_id="agent-003"),
            ],
            history_window_days=30,
        )
        assert ctx.history_window_days == 30
        assert len(ctx.agent_transactions) == 1
        assert len(ctx.merchant_peer_records) == 1
        assert len(ctx.sibling_agents) == 1


class TestNetworkSignal:
    """Tests for NetworkSignal model."""

    def test_valid_signal(self):
        signal = NetworkSignal(
            signal_type=NetworkSignalType.SHARED_RISK_EXPOSURE,
            score=0.5,
            confidence=0.8,
            what="Test signal",
            why="Test reason",
        )
        assert signal.score == 0.5
        assert signal.source_engine == "graph_risk_engine"

    def test_score_bounds(self):
        import pytest
        with pytest.raises(Exception):
            NetworkSignal(
                signal_type=NetworkSignalType.MERCHANT_CONCENTRATION,
                score=-0.1,
                confidence=1.0,
            )
        with pytest.raises(Exception):
            NetworkSignal(
                signal_type=NetworkSignalType.MERCHANT_CONCENTRATION,
                score=1.1,
                confidence=1.0,
            )

    def test_confidence_bounds(self):
        import pytest
        with pytest.raises(Exception):
            NetworkSignal(
                signal_type=NetworkSignalType.AGENT_CLUSTER_RISK,
                score=0.5,
                confidence=-0.1,
            )
        with pytest.raises(Exception):
            NetworkSignal(
                signal_type=NetworkSignalType.AGENT_CLUSTER_RISK,
                score=0.5,
                confidence=1.1,
            )


class TestNetworkRiskResult:
    """Tests for NetworkRiskResult model."""

    def test_empty_result(self):
        result = NetworkRiskResult()
        assert result.overall_score == 0.0
        assert result.confidence == 1.0
        assert result.signal_count == 0

    def test_result_with_signals(self):
        signals = [
            NetworkSignal(
                signal_type=NetworkSignalType.SHARED_RISK_EXPOSURE,
                score=0.3,
                confidence=0.7,
            ),
        ]
        result = NetworkRiskResult(
            overall_score=0.3,
            confidence=0.7,
            signals=signals,
            signal_count=1,
        )
        assert result.signal_count == 1
        assert result.overall_score == 0.3


class TestGraphStatistics:
    """Tests for GraphStatistics model."""

    def test_defaults(self):
        stats = GraphStatistics()
        assert stats.total_agent_transactions == 0
        assert stats.unique_merchants == 0
        assert stats.total_merchant_peers == 0
        assert stats.unique_peer_agents == 0
        assert stats.sibling_agent_count == 0
