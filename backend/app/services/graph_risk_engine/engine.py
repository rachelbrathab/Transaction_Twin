"""Graph Risk Engine — deterministic, explainable network risk assessment.

Analyzes graph relationships between agents, merchants, and transactions
to produce structured network risk evidence.

No database. No API calls. No LLM. No payment execution.
Does NOT make ALLOW/REVIEW/BLOCK decisions.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog

from app.services.graph_risk_engine.constants import (
    GRAPH_RISK_MODEL_VERSION,
)
from app.services.graph_risk_engine.graph_builder import GraphBuilder
from app.services.graph_risk_engine.models import (
    GraphContext,
    GraphStatistics,
    NetworkRiskResult,
    NetworkSignal,
)
from app.services.graph_risk_engine.signals import (
    extract_agent_cluster_risk,
    extract_merchant_concentration,
    extract_shared_risk_exposure,
)

logger = structlog.get_logger()


class GraphRiskEngine:
    """Deterministic graph risk engine. No I/O, no DB, no LLM.

    Usage:
        engine = GraphRiskEngine()
        result = engine.evaluate(context)
    """

    def __init__(self) -> None:
        self._builder = GraphBuilder()

    def evaluate(self, context: GraphContext) -> NetworkRiskResult:
        """Evaluate graph risk and produce a deterministic NetworkRiskResult.

        Args:
            context: Pre-built GraphContext with historical data.

        Returns:
            NetworkRiskResult with scores, signals, and explanation.
        """
        start_time = time.monotonic()
        evaluation_id = str(uuid.uuid4())[:8]
        now = datetime.now(UTC)

        log = logger.bind(
            evaluation_id=evaluation_id,
            agent_id=context.target_agent_id,
            user_id=context.target_user_id,
        )

        # Step 1: Build in-memory graph
        graph = self._builder.build(context)

        # Step 2: Extract network signals (deterministic order)
        signals: list[NetworkSignal] = []

        shared_risk = extract_shared_risk_exposure(graph)
        if shared_risk is not None:
            signals.append(shared_risk)

        concentration = extract_merchant_concentration(graph)
        if concentration is not None:
            signals.append(concentration)

        cluster_risk = extract_agent_cluster_risk(graph)
        if cluster_risk is not None:
            signals.append(cluster_risk)

        # Step 3: Compute overall score
        overall_score = self._compute_overall_score(signals)

        # Step 4: Compute confidence
        confidence = self._compute_confidence(context, signals, graph.statistics)

        # Step 5: Build summary
        summary = self._build_summary(signals, overall_score)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "graph_risk_evaluation_completed",
            overall_score=overall_score,
            confidence=confidence,
            signal_count=len(signals),
            model_version=GRAPH_RISK_MODEL_VERSION,
            latency_ms=latency_ms,
        )

        return NetworkRiskResult(
            overall_score=round(overall_score, 4),
            confidence=round(confidence, 4),
            signals=signals,
            signal_count=len(signals),
            graph_statistics=graph.statistics,
            summary=summary,
            evaluation_id=evaluation_id,
            model_version=GRAPH_RISK_MODEL_VERSION,
            evaluated_at=now.isoformat(),
        )

    def _compute_overall_score(self, signals: list[NetworkSignal]) -> float:
        """Compute overall network risk score from signals.

        Uses the maximum signal score (dominant signal) rather than averaging,
        because a single strong network risk signal should be sufficient
        to raise concern.
        """
        if not signals:
            return 0.0

        # Overall score is the maximum of all signal scores
        # This ensures one strong signal isn't diluted by others
        max_score = max(s.score for s in signals)
        return min(max_score, 1.0)

    def _compute_confidence(
        self,
        context: GraphContext,
        signals: list[NetworkSignal],
        statistics: GraphStatistics,
    ) -> float:
        """Compute confidence based on data availability and signal quality.

        Blend: 60% data availability + 40% average signal confidence.
        """
        # Base confidence from data availability
        data_confidence = 1.0

        if not context.graph_available:
            data_confidence = 0.0
        elif statistics.total_agent_transactions == 0:
            data_confidence = 0.0
        elif statistics.total_agent_transactions < 3:
            data_confidence = 0.3
        elif statistics.total_agent_transactions < 5:
            data_confidence = 0.5
        elif statistics.total_agent_transactions < 10:
            data_confidence = 0.7
        else:
            data_confidence = 0.9

        # Adjust for peer data availability
        if statistics.unique_peer_agents == 0:
            data_confidence *= 0.8
        if statistics.sibling_agent_count == 0:
            data_confidence *= 0.9

        data_confidence = max(0.0, min(1.0, data_confidence))

        # Blend with average signal confidence
        if signals:
            avg_signal_confidence = sum(s.confidence for s in signals) / len(signals)
            confidence = data_confidence * 0.6 + avg_signal_confidence * 0.4
        else:
            # No signals available — confidence reflects data availability
            confidence = data_confidence * 0.5

        return round(max(0.0, min(1.0, confidence)), 4)

    def _build_summary(
        self, signals: list[NetworkSignal], overall_score: float
    ) -> str:
        """Build human-readable summary."""
        if not signals:
            return "No network risk data available for analysis."

        contributing = [s for s in signals if s.score > 0]
        if not contributing:
            return (
                "Network analysis found no significant risk indicators. "
                "Agent's network position appears normal."
            )

        descriptions = [s.what for s in contributing]
        return (
            f"Network risk ({overall_score:.2f}) — "
            f"{'; '.join(descriptions)}"
        )
