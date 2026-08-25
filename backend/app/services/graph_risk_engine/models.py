"""Graph Risk Engine domain models.

Strongly typed Pydantic models for graph/network risk analysis.
Framework-independent. No database/HTTP/LLM dependencies.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class NetworkSignalType(StrEnum):
    """Types of network risk signals."""

    SHARED_RISK_EXPOSURE = "shared_risk_exposure"
    MERCHANT_CONCENTRATION = "merchant_concentration"
    AGENT_CLUSTER_RISK = "agent_cluster_risk"


class GraphNodeType(StrEnum):
    """Node types in the transaction graph."""

    AGENT = "agent"
    MERCHANT = "merchant"
    TRANSACTION = "transaction"


class GraphEdgeType(StrEnum):
    """Edge types in the transaction graph."""

    EXECUTED = "executed"
    VENDED_AT = "vended_at"


# ── Graph Data Records ─────────────────────────────────────────────


class AgentTransactionRecord(BaseModel):
    """A single historical transaction by the target agent."""

    transaction_id: str
    merchant_id: str | None = None
    amount: float = Field(ge=0.0)
    currency: str = "INR"
    transaction_type: str = ""
    created_at: str = ""  # ISO 8601


class MerchantPeerRecord(BaseModel):
    """A peer agent's activity at one of the target agent's merchants."""

    agent_id: str
    merchant_id: str
    trust_score: float | None = None
    transaction_count: int = Field(default=0, ge=0)
    latest_transaction_at: str = ""  # ISO 8601


class SiblingAgentRecord(BaseModel):
    """A sibling agent under the same user."""

    agent_id: str
    name: str = ""
    trust_score: float | None = None
    status: str = "active"
    transaction_count: int = Field(default=0, ge=0)


# ── Graph Context ──────────────────────────────────────────────────


class GraphContext(BaseModel):
    """All data needed for graph risk analysis.

    Built by the API service layer from bounded SQL queries.
    Graph Risk Engine consumes but does not query the database.
    """

    target_agent_id: str
    target_user_id: str

    # Agent's own recent transactions
    agent_transactions: list[AgentTransactionRecord] = Field(default_factory=list)

    # Other agents' activity at the same merchants
    merchant_peer_records: list[MerchantPeerRecord] = Field(default_factory=list)

    # Sibling agents under the same user
    sibling_agents: list[SiblingAgentRecord] = Field(default_factory=list)

    # Metadata
    history_window_days: int = 90
    graph_available: bool = True


# ── Network Signal ─────────────────────────────────────────────────


class NetworkSignal(BaseModel):
    """A single network risk signal with full explainability."""

    signal_type: NetworkSignalType

    # Risk score for this signal [0.0, 1.0]
    score: float = Field(ge=0.0, le=1.0)

    # Confidence in this signal [0.0, 1.0]
    confidence: float = Field(ge=0.0, le=1.0)

    # Human-readable: what was observed
    what: str = ""

    # Human-readable: why it matters
    why: str = ""

    # Structured evidence for the frontend
    evidence: dict[str, Any] = Field(default_factory=dict)

    # Source engine provenance
    source_engine: str = "graph_risk_engine"
    source_fields: list[str] = Field(default_factory=list)


# ── Graph Statistics ───────────────────────────────────────────────


class GraphStatistics(BaseModel):
    """Summary statistics about the constructed graph."""

    total_agent_transactions: int = Field(default=0, ge=0)
    unique_merchants: int = Field(default=0, ge=0)
    total_merchant_peers: int = Field(default=0, ge=0)
    unique_peer_agents: int = Field(default=0, ge=0)
    sibling_agent_count: int = Field(default=0, ge=0)
    graph_construction_time_ms: int = Field(default=0, ge=0)


# ── Network Risk Result ────────────────────────────────────────────


class NetworkRiskResult(BaseModel):
    """Complete network risk assessment.

    Standalone result from GraphRiskEngine. Not part of the weighted
    Risk Engine scoring — integrates through confidence modification.
    """

    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    signals: list[NetworkSignal] = Field(default_factory=list)
    signal_count: int = Field(default=0, ge=0)

    graph_statistics: GraphStatistics = Field(default_factory=GraphStatistics)

    # Explainability
    summary: str = ""

    # Metadata
    evaluation_id: str = ""
    model_version: str = "graph-risk-v1"
    evaluated_at: str = ""
