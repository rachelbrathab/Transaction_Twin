"""Graph builder — constructs bounded in-memory graph from GraphContext.

Pure computation. No database. No I/O. Deterministic.
"""

from __future__ import annotations

from collections import defaultdict

from app.services.graph_risk_engine.models import (
    AgentTransactionRecord,
    GraphContext,
    GraphStatistics,
    MerchantPeerRecord,
    SiblingAgentRecord,
)


class BuiltGraph:
    """An in-memory graph representation built from GraphContext.

    Contains deterministic adjacency structures for signal extraction.
    """

    def __init__(
        self,
        agent_transactions: list[AgentTransactionRecord],
        merchant_transactions: dict[str, list[AgentTransactionRecord]],
        merchant_peers: dict[str, list[MerchantPeerRecord]],
        sibling_agents: list[SiblingAgentRecord],
        statistics: GraphStatistics,
    ) -> None:
        self.agent_transactions = agent_transactions
        self.merchant_transactions = merchant_transactions
        self.merchant_peers = merchant_peers
        self.sibling_agents = sibling_agents
        self.statistics = statistics


class GraphBuilder:
    """Constructs a bounded in-memory graph from a GraphContext.

    Usage:
        builder = GraphBuilder()
        graph = builder.build(context)
    """

    def build(self, context: GraphContext) -> BuiltGraph:
        """Build the in-memory graph from the provided context.

        Args:
            context: Pre-built GraphContext with historical data.

        Returns:
            BuiltGraph with adjacency structures and statistics.
        """
        if not context.graph_available:
            return self._empty_graph(context.target_agent_id, context.target_user_id)

        # Sort agent transactions deterministically (by created_at, then id)
        agent_txns = sorted(
            context.agent_transactions,
            key=lambda t: (t.created_at, t.transaction_id),
        )

        # Group agent transactions by merchant_id
        merchant_txns: dict[str, list[AgentTransactionRecord]] = defaultdict(list)
        for txn in agent_txns:
            if txn.merchant_id:
                merchant_txns[txn.merchant_id].append(txn)

        # Group merchant peers by merchant_id (deterministic order)
        merchant_peers: dict[str, list[MerchantPeerRecord]] = defaultdict(list)
        peer_agent_ids: set[str] = set()
        for peer in context.merchant_peer_records:
            merchant_peers[peer.merchant_id].append(peer)
            peer_agent_ids.add(peer.agent_id)

        # Sort sibling agents deterministically
        siblings = sorted(
            context.sibling_agents,
            key=lambda s: (s.agent_id,),
        )

        unique_merchants = len(merchant_txns)
        unique_peer_agents = len(peer_agent_ids)

        statistics = GraphStatistics(
            total_agent_transactions=len(agent_txns),
            unique_merchants=unique_merchants,
            total_merchant_peers=len(context.merchant_peer_records),
            unique_peer_agents=unique_peer_agents,
            sibling_agent_count=len(siblings),
        )

        return BuiltGraph(
            agent_transactions=agent_txns,
            merchant_transactions=dict(merchant_txns),
            merchant_peers=dict(merchant_peers),
            sibling_agents=siblings,
            statistics=statistics,
        )

    def _empty_graph(self, agent_id: str, user_id: str) -> BuiltGraph:
        """Return an empty graph for unavailable data."""
        return BuiltGraph(
            agent_transactions=[],
            merchant_transactions={},
            merchant_peers={},
            sibling_agents=[],
            statistics=GraphStatistics(),
        )
