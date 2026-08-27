"""Calibration Intelligence — core engine.

Orchestrates dataset construction, metric computation, and
recommendation generation. Deterministic and explainable.

No database, no API, no LLM, no external service calls.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog

from app.services.calibration_intelligence.constants import (
    CALIBRATION_VERSION_PREFIX,
    DEFAULT_WINDOW_DAYS,
)
from app.services.calibration_intelligence.dataset import build_dataset
from app.services.calibration_intelligence.metrics import (
    compute_agent_effectiveness,
    compute_all_metrics,
    compute_policy_effectiveness,
    compute_risk_cross_tab,
)
from app.services.calibration_intelligence.models import (
    CalibrationIntelligenceResult,
)
from app.services.calibration_intelligence.recommendations import (
    generate_recommendations,
)

logger = structlog.get_logger()

# Global version counter (deterministic within a process)
_version_counter = 0


class CalibrationIntelligenceEngine:
    """Deterministic calibration intelligence engine.

    Usage:
        engine = CalibrationIntelligenceEngine()
        result = engine.evaluate(context)
    """

    def evaluate(
        self,
        transaction_records: list[dict],
        decision_records: list[dict],
        outcome_records: list[dict],
        policy_names: dict[str, str] | None = None,
        agent_names: dict[str, str] | None = None,
        window_days: int = DEFAULT_WINDOW_DAYS,
        user_id: str = "",
    ) -> CalibrationIntelligenceResult:
        """Evaluate calibration intelligence from verified outcomes.

        Args:
            transaction_records: Pre-fetched transaction data.
            decision_records: Pre-fetched decision data.
            outcome_records: Pre-fetched outcome event data.
            policy_names: Mapping of policy_id → display name.
            agent_names: Mapping of agent_id → display name.
            window_days: Analysis window in days.
            user_id: Owner user ID.

        Returns:
            CalibrationIntelligenceResult with dataset, metrics,
            and advisory recommendations.
        """
        global _version_counter
        _version_counter += 1

        start_time = time.monotonic()
        now = datetime.now(UTC)

        log = logger.bind(
            user_id=user_id,
            window_days=window_days,
            transaction_count=len(transaction_records),
        )

        # Step 1: Build calibration dataset
        dataset = build_dataset(
            transaction_records=transaction_records,
            decision_records=decision_records,
            outcome_records=outcome_records,
            window_days=window_days,
        )

        # Step 2: Compute metrics
        eligible_count = dataset.eligible_samples
        if eligible_count == 0:
            metrics: list = []
        else:
            metrics = compute_all_metrics(dataset)

        # Step 3: Compute risk cross-tabulation
        risk_cross_tab = compute_risk_cross_tab(dataset)

        # Step 4: Compute policy effectiveness
        policy_eff = compute_policy_effectiveness(
            dataset, policy_names=policy_names,
        )

        # Step 5: Compute agent effectiveness
        agent_eff = compute_agent_effectiveness(
            dataset, agent_names=agent_names,
        )

        # Step 6: Generate recommendations
        calibration_version = (
            f"{CALIBRATION_VERSION_PREFIX}{_version_counter}"
        )
        recommendations, version = generate_recommendations(
            metrics=metrics,
            risk_cross_tab=risk_cross_tab,
            policy_effectiveness=policy_eff,
            agent_effectiveness=agent_eff,
            calibration_version=calibration_version,
            window_days=window_days,
            total_samples=dataset.total_samples,
            eligible_samples=dataset.eligible_samples,
        )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "calibration_intelligence_completed",
            total_samples=dataset.total_samples,
            eligible_samples=dataset.eligible_samples,
            recommendation_count=len(recommendations),
            latency_ms=latency_ms,
        )

        return CalibrationIntelligenceResult(
            dataset=dataset,
            metrics=metrics,
            risk_cross_tab=risk_cross_tab,
            policy_effectiveness=policy_eff,
            agent_effectiveness=agent_eff,
            recommendations=recommendations,
            version=version,
            computed_at=now.isoformat(),
        )
