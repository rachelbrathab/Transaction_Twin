"""Decision Engine — deterministic transaction disposition.

Evaluates signals from Intent Engine, Transaction Twin, Policy Engine,
and trust checks to produce ALLOW / REVIEW / BLOCK decisions.

No database I/O. No LLM. No payment execution. Pure computation.

Safety model:
  "Fail-safe toward non-execution."
  - Known severe violation → BLOCK
  - Insufficient evidence → REVIEW
  - Sufficient positive evidence → ALLOW
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.services.comparison_engine.models import OverallStatus
from app.services.decision_engine.models import (
    DecisionContext,
    DecisionResult,
    DecisionSignal,
    DecisionStatus,
    DriftSummary,
    PolicySummary,
    RiskSummary,
)
from app.services.policy_engine.models import (
    PolicyCategory,
    PolicyEvaluationStatus,
    PolicySeverity,
)

logger = structlog.get_logger()

DECISION_VERSION = "decision-v1"

# ── Security categories for enforcement derivation ─────────────────
# When a policy in these categories is triggered at HIGH severity,
# it escalates to BLOCK (not just REVIEW).

SECURITY_ENFORCEMENT_CATEGORIES = {
    PolicyCategory.TRANSACTION_TYPE_RESTRICTION,
    PolicyCategory.AUTHORIZATION_SCOPE,
    PolicyCategory.AGENT_RESTRICTION,
}

# ── Severity ordering ──────────────────────────────────────────────

_SEVERITY_ORDER: list[PolicySeverity] = [
    PolicySeverity.NONE,
    PolicySeverity.LOW,
    PolicySeverity.MEDIUM,
    PolicySeverity.HIGH,
    PolicySeverity.CRITICAL,
]

_DRIFT_SEVERITY_ORDER: list[str] = [
    "none",
    "low",
    "medium",
    "high",
    "critical",
]


def _severity_index(sev: str | PolicySeverity | None) -> int:
    """Return numeric index for severity comparison."""
    if sev is None:
        return 0
    val = sev.value if isinstance(sev, PolicySeverity) else sev
    try:
        return _SEVERITY_ORDER.index(PolicySeverity(val))
    except (ValueError, KeyError):
        return 0


def _drift_severity_index(sev: str | None) -> int:
    """Return numeric index for drift severity comparison."""
    if sev is None:
        return 0
    try:
        return _DRIFT_SEVERITY_ORDER.index(sev)
    except ValueError:
        return 0


def _max_severity(a: str | None, b: str | None) -> str:
    """Return the higher of two severity strings."""
    idx_a = _severity_index(a)
    idx_b = _severity_index(b)
    return b if idx_b >= idx_a else (a or "none")


# ── Decision Engine ────────────────────────────────────────────────


class DecisionEngine:
    """Deterministic decision engine. No I/O, no DB, no LLM.

    Usage:
        engine = DecisionEngine()
        result = engine.evaluate(context)
    """

    def evaluate(self, context: DecisionContext) -> DecisionResult:
        """Evaluate all signals and produce a deterministic decision.

        Args:
            context: Pre-built DecisionContext with all available signals.

        Returns:
            DecisionResult with decision, explanation, and signals.
        """
        start_time = time.monotonic()
        evaluation_id = context.evaluation_id or str(uuid.uuid4())[:8]
        now = datetime.now(UTC)

        log = logger.bind(
            evaluation_id=evaluation_id,
            intent_id=context.intent_id,
            user_id=context.user_id,
            agent_id=context.agent_id,
        )

        signals: list[DecisionSignal] = []
        has_block = False
        has_review = False

        # ── Step 1: Hard violations ───────────────────────
        hard_block = self._check_hard_blocks(context)
        if hard_block is not None:
            signals.append(hard_block)
            has_block = True

        # ── Step 2: Policy signals ────────────────────────
        policy_signals = self._evaluate_policy_signals(context)
        for sig in policy_signals:
            signals.append(sig)
            if sig.status == "violation":
                has_block = True
            elif sig.status in ("triggered", "unknown"):
                has_review = True

        # ── Step 3: Drift signals ─────────────────────────
        drift_signals = self._evaluate_drift_signals(context)
        for sig in drift_signals:
            signals.append(sig)
            if sig.status == "violation":
                has_block = True
            elif sig.status in ("negative", "unknown"):
                has_review = True

        # ── Step 4: Agent trust ───────────────────────────
        agent_signal = self._evaluate_agent_trust(context)
        if agent_signal is not None:
            signals.append(agent_signal)
            if agent_signal.status in ("negative", "unknown"):
                has_review = True

        # ── Step 5: Merchant trust ────────────────────────
        merchant_signal = self._evaluate_merchant_trust(context)
        if merchant_signal is not None:
            signals.append(merchant_signal)
            if merchant_signal.status in ("negative", "unknown"):
                has_review = True

        # ── Step 6: Intent signals ────────────────────────
        intent_signals = self._evaluate_intent_signals(context)
        for sig in intent_signals:
            signals.append(sig)
            if sig.status == "violation":
                has_block = True
            elif sig.status in ("negative", "unknown"):
                has_review = True

        # ── Step 7: Final decision ────────────────────────
        if has_block:
            decision = DecisionStatus.BLOCK
        elif has_review:
            decision = DecisionStatus.REVIEW
        else:
            decision = DecisionStatus.ALLOW

        # ── Build summaries ───────────────────────────────
        policy_summary = self._build_policy_summary(context)
        risk_summary = self._build_risk_summary(context)
        drift_summary = self._build_drift_summary(context)

        # ── Build explanation ─────────────────────────────
        reason = self._build_reason(decision, signals)
        explanation = self._build_explanation(context, signals)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        log.info(
            "decision_evaluation_completed",
            decision=decision.value,
            signal_count=len(signals),
            latency_ms=latency_ms,
            decision_version=DECISION_VERSION,
        )

        if decision == DecisionStatus.BLOCK:
            log.warning(
                "decision_blocked",
                signal_count=len(signals),
            )
        elif decision == DecisionStatus.REVIEW:
            log.warning(
                "decision_review_required",
                signal_count=len(signals),
            )

        return DecisionResult(
            decision=decision,
            reason=reason,
            decision_version=DECISION_VERSION,
            evaluation_id=evaluation_id,
            intent_id=context.intent_id,
            intent_version=context.intent_version,
            proposal_intent_id=context.proposal_intent_id,
            policy_summary=policy_summary,
            risk_summary=risk_summary,
            drift_summary=drift_summary,
            signals=signals,
            signal_count=len(signals),
            explanation=explanation,
            created_at=now.isoformat(),
            evaluated_at=now.isoformat(),
        )

    # ── Hard Blocks ────────────────────────────────────────────────

    def _check_hard_blocks(self, ctx: DecisionContext) -> DecisionSignal | None:
        """Check for known hard violations. Returns a BLOCK signal or None."""

        # 1. Intent not active
        if ctx.intent_status in ("revoked", "expired", "rejected"):
            return DecisionSignal(
                source="validation",
                signal_type="intent_inactive",
                status="violation",
                description=(
                    f"Intent status is '{ctx.intent_status}' — "
                    "transaction cannot proceed against inactive intent"
                ),
                evidence={"intent_status": ctx.intent_status},
            )

        # 2. Intent missing structured data
        if ctx.intent_transaction_type is None:
            return DecisionSignal(
                source="validation",
                signal_type="intent_insufficient",
                status="violation",
                description="Intent has no structured data to evaluate against",
                evidence={},
            )

        # 3. Transaction Twin says proposal is invalid
        if (
            ctx.drift_result_available
            and ctx.drift_overall_status == OverallStatus.INVALID_PROPOSAL.value
        ):
            return DecisionSignal(
                source="validation",
                signal_type="invalid_proposal",
                status="violation",
                description="Transaction proposal is malformed or invalid",
                evidence={"drift_overall_status": ctx.drift_overall_status},
            )

        # 4. Transaction type mismatch (both known, both different)
        if (
            ctx.intent_transaction_type is not None
            and ctx.proposal_transaction_type is not None
            and ctx.intent_transaction_type != ctx.proposal_transaction_type
        ):
            return DecisionSignal(
                source="validation",
                signal_type="transaction_type_mismatch",
                status="violation",
                description=(
                    f"Proposed type '{ctx.proposal_transaction_type}' differs from "
                    f"authorized type '{ctx.intent_transaction_type}'"
                ),
                evidence={
                    "intent_type": ctx.intent_transaction_type,
                    "proposal_type": ctx.proposal_transaction_type,
                },
            )

        return None

    # ── Policy Signals ─────────────────────────────────────────────

    def _evaluate_policy_signals(
        self, ctx: DecisionContext
    ) -> list[DecisionSignal]:
        """Map policy evaluation results into DecisionSignals.

        Rules:
          PASS → positive signal
          TRIGGERED + CRITICAL → violation (BLOCK)
          TRIGGERED + HIGH + security category → violation (BLOCK)
          TRIGGERED + HIGH + non-security → triggered (REVIEW)
          TRIGGERED + MEDIUM → triggered (REVIEW)
          TRIGGERED + LOW → triggered (REVIEW)
          UNKNOWN → unknown (REVIEW)
          INVALID_POLICY → unknown (REVIEW)
        """
        signals: list[DecisionSignal] = []

        if not ctx.policy_result_available:
            return signals

        for pr_dict in ctx.policy_results_for_signals:
            policy_id = pr_dict.get("policy_id", "unknown")
            policy_name = pr_dict.get("policy_name", "unknown")
            status_str = pr_dict.get("status", "pass")
            highest_severity_str = pr_dict.get("highest_triggered_severity", "none")

            try:
                status = PolicyEvaluationStatus(status_str)
            except ValueError:
                status = PolicyEvaluationStatus.PASS

            # Determine enforcement from severity + category
            enforcement = self._derive_enforcement(pr_dict)

            if status == PolicyEvaluationStatus.PASS:
                signals.append(DecisionSignal(
                    source="policy",
                    signal_type="policy_passed",
                    status="positive",
                    description=f"Policy '{policy_name}' passed all rules",
                    evidence={"policy_id": policy_id, "policy_name": policy_name},
                ))

            elif status == PolicyEvaluationStatus.TRIGGERED:
                if enforcement == "block":
                    signals.append(DecisionSignal(
                        source="policy",
                        signal_type="policy_triggered",
                        status="violation",
                        severity=highest_severity_str,
                        description=(
                            f"Policy '{policy_name}' triggered with "
                            f"{highest_severity_str} severity (enforcement: block)"
                        ),
                        evidence={
                            "policy_id": policy_id,
                            "policy_name": policy_name,
                            "severity": highest_severity_str,
                            "enforcement": enforcement,
                        },
                    ))
                else:
                    signals.append(DecisionSignal(
                        source="policy",
                        signal_type="policy_triggered",
                        status="triggered",
                        severity=highest_severity_str,
                        description=(
                            f"Policy '{policy_name}' triggered with "
                            f"{highest_severity_str} severity (enforcement: review)"
                        ),
                        evidence={
                            "policy_id": policy_id,
                            "policy_name": policy_name,
                            "severity": highest_severity_str,
                            "enforcement": enforcement,
                        },
                    ))

            elif status == PolicyEvaluationStatus.UNKNOWN:
                signals.append(DecisionSignal(
                    source="policy",
                    signal_type="policy_unknown",
                    status="unknown",
                    description=(
                        f"Policy '{policy_name}' evaluation result is unknown — "
                        "cannot verify compliance"
                    ),
                    evidence={"policy_id": policy_id, "policy_name": policy_name},
                ))

            elif status == PolicyEvaluationStatus.INVALID_POLICY:
                signals.append(DecisionSignal(
                    source="policy",
                    signal_type="policy_invalid",
                    status="unknown",
                    description=(
                        f"Policy '{policy_name}' has invalid structure — "
                        "compliance cannot be verified"
                    ),
                    evidence={"policy_id": policy_id, "policy_name": policy_name},
                ))

        return signals

    def _derive_enforcement(self, policy_dict: dict[str, Any]) -> str:
        """Derive enforcement level from policy severity and category.

        This is the temporary derivation strategy for Sprint 6.
        Future enhancement: explicit 'enforcement' field on PolicyRule.
        """
        highest_sev_str = policy_dict.get("highest_triggered_severity", "none")
        try:
            severity = PolicySeverity(highest_sev_str)
        except ValueError:
            severity = PolicySeverity.NONE

        # CRITICAL always blocks
        if severity == PolicySeverity.CRITICAL:
            return "block"

        # HIGH + security category → block
        if severity == PolicySeverity.HIGH:
            categories = policy_dict.get("categories", [])
            for cat_str in categories:
                try:
                    cat = PolicyCategory(cat_str)
                    if cat in SECURITY_ENFORCEMENT_CATEGORIES:
                        return "block"
                except ValueError:
                    continue

        # Everything else → review
        return "review"

    # ── Drift Signals ──────────────────────────────────────────────

    def _evaluate_drift_signals(
        self, ctx: DecisionContext
    ) -> list[DecisionSignal]:
        """Map drift results into DecisionSignals.

        Rules:
          match → positive
          partial_match → neutral
          drift_detected + CRITICAL → violation (BLOCK)
          drift_detected + HIGH → negative (REVIEW)
          drift_detected + MEDIUM → negative (REVIEW)
          drift_detected + LOW → neutral
          insufficient_data → unknown (REVIEW)
          invalid_proposal → handled in hard blocks
          drift_result not available → unknown (REVIEW)
        """
        signals: list[DecisionSignal] = []

        if not ctx.drift_result_available:
            signals.append(DecisionSignal(
                source="drift",
                signal_type="drift_unavailable",
                status="unknown",
                description="Transaction Twin did not produce a drift result",
                evidence={},
            ))
            return signals

        overall = ctx.drift_overall_status
        severity = ctx.drift_severity

        if overall == OverallStatus.MATCH.value:
            signals.append(DecisionSignal(
                source="drift",
                signal_type="drift_match",
                status="positive",
                description="Transaction matches authorized intent",
                evidence={"overall_status": overall, "severity": severity},
            ))

        elif overall == OverallStatus.PARTIAL_MATCH.value:
            signals.append(DecisionSignal(
                source="drift",
                signal_type="drift_partial_match",
                status="neutral",
                description="Transaction partially matches authorized intent",
                evidence={"overall_status": overall, "severity": severity},
            ))

        elif overall == OverallStatus.DRIFT_DETECTED.value:
            sev_idx = _drift_severity_index(severity)

            if sev_idx >= _drift_severity_order_index("critical"):
                signals.append(DecisionSignal(
                    source="drift",
                    signal_type="drift_detected",
                    status="violation",
                    severity=severity,
                    description=(
                        "Critical drift detected — transaction deviates "
                        "significantly from authorized intent"
                    ),
                    evidence={"overall_status": overall, "severity": severity},
                ))
            elif sev_idx >= _drift_severity_order_index("high"):
                signals.append(DecisionSignal(
                    source="drift",
                    signal_type="drift_detected",
                    status="negative",
                    severity=severity,
                    description="High drift detected — significant deviation from intent",
                    evidence={"overall_status": overall, "severity": severity},
                ))
            elif sev_idx >= _drift_severity_order_index("medium"):
                signals.append(DecisionSignal(
                    source="drift",
                    signal_type="drift_detected",
                    status="negative",
                    severity=severity,
                    description="Medium drift detected — moderate deviation from intent",
                    evidence={"overall_status": overall, "severity": severity},
                ))
            else:
                signals.append(DecisionSignal(
                    source="drift",
                    signal_type="drift_detected",
                    status="neutral",
                    severity=severity,
                    description="Low drift detected — minor deviation from intent",
                    evidence={"overall_status": overall, "severity": severity},
                ))

        elif overall == OverallStatus.INSUFFICIENT_DATA.value:
            signals.append(DecisionSignal(
                source="drift",
                signal_type="drift_insufficient_data",
                status="unknown",
                description="Insufficient data to determine drift",
                evidence={"overall_status": overall},
            ))

        elif overall == OverallStatus.INVALID_PROPOSAL.value:
            # Already handled in hard blocks, but add signal for completeness
            signals.append(DecisionSignal(
                source="drift",
                signal_type="invalid_proposal",
                status="violation",
                description="Proposal is invalid per Transaction Twin",
                evidence={"overall_status": overall},
            ))

        return signals

    # ── Agent Trust ────────────────────────────────────────────────

    def _evaluate_agent_trust(
        self, ctx: DecisionContext
    ) -> DecisionSignal | None:
        """Evaluate agent trust score.

        Rules:
          >= 0.7 → positive
          0.3–<0.7 → neutral
          < 0.3 → negative (REVIEW)
          None → unknown (REVIEW)

        Agent trust alone must never BLOCK.
        """
        score = ctx.agent_trust_score

        if score is None:
            return DecisionSignal(
                source="trust",
                signal_type="agent_trust_unknown",
                status="unknown",
                description="Agent trust score is not available",
                evidence={"agent_id": ctx.agent_id},
            )

        if score >= 0.7:
            return DecisionSignal(
                source="trust",
                signal_type="agent_trust_high",
                status="positive",
                description=f"Agent trust score is {score:.2f} (high)",
                evidence={"agent_id": ctx.agent_id, "trust_score": score},
            )

        if score >= 0.3:
            return DecisionSignal(
                source="trust",
                signal_type="agent_trust_medium",
                status="neutral",
                description=f"Agent trust score is {score:.2f} (medium)",
                evidence={"agent_id": ctx.agent_id, "trust_score": score},
            )

        return DecisionSignal(
            source="trust",
            signal_type="agent_trust_low",
            status="negative",
            description=f"Agent trust score is {score:.2f} (low)",
            evidence={"agent_id": ctx.agent_id, "trust_score": score},
        )

    # ── Merchant Trust ─────────────────────────────────────────────

    def _evaluate_merchant_trust(
        self, ctx: DecisionContext
    ) -> DecisionSignal | None:
        """Evaluate merchant trust status.

        Rules:
          true → positive
          false → negative (REVIEW)
          None → unknown (REVIEW)

        Merchant trust alone must never BLOCK.
        """
        trusted = ctx.proposal_merchant_trusted

        if trusted is None:
            return DecisionSignal(
                source="trust",
                signal_type="merchant_trust_unknown",
                status="unknown",
                description="Merchant trust status not provided",
                evidence={
                    "merchant_name": ctx.proposal_merchant_name or "unknown",
                },
            )

        if trusted:
            return DecisionSignal(
                source="trust",
                signal_type="merchant_trusted",
                status="positive",
                description=f"Merchant '{ctx.proposal_merchant_name or 'unknown'}' is trusted",
                evidence={
                    "merchant_name": ctx.proposal_merchant_name,
                    "trusted": True,
                },
            )

        return DecisionSignal(
            source="trust",
            signal_type="merchant_untrusted",
            status="negative",
            description=f"Merchant '{ctx.proposal_merchant_name or 'unknown'}' is not trusted",
            evidence={
                "merchant_name": ctx.proposal_merchant_name,
                "trusted": False,
            },
        )

    # ── Intent Signals ─────────────────────────────────────────────

    def _evaluate_intent_signals(
        self, ctx: DecisionContext
    ) -> list[DecisionSignal]:
        """Evaluate intent-related signals.

        Rules:
          intent confidence >= 0.5 → positive
          intent confidence < 0.5 → negative (REVIEW)
          intent confidence None → unknown (REVIEW)
          proposal transaction type None → unknown (REVIEW)
        """
        signals: list[DecisionSignal] = []

        # Intent confidence
        if ctx.intent_confidence is not None:
            if ctx.intent_confidence >= 0.5:
                signals.append(DecisionSignal(
                    source="intent",
                    signal_type="intent_confidence_adequate",
                    status="positive",
                    description=f"Intent confidence is {ctx.intent_confidence:.2f}",
                    evidence={"confidence": ctx.intent_confidence},
                ))
            else:
                signals.append(DecisionSignal(
                    source="intent",
                    signal_type="intent_confidence_low",
                    status="negative",
                    description=(
                        f"Intent confidence is {ctx.intent_confidence:.2f} "
                        "— below 0.5 threshold"
                    ),
                    evidence={"confidence": ctx.intent_confidence},
                ))
        else:
            signals.append(DecisionSignal(
                source="intent",
                signal_type="intent_confidence_unknown",
                status="unknown",
                description="Intent confidence is not available",
                evidence={},
            ))

        # Proposal transaction type unknown
        if ctx.proposal_transaction_type is None:
            signals.append(DecisionSignal(
                source="validation",
                signal_type="proposal_type_unknown",
                status="unknown",
                description="Proposal transaction type is not specified",
                evidence={},
            ))

        return signals

    # ── Summary Builders ───────────────────────────────────────────

    def _build_policy_summary(self, ctx: DecisionContext) -> PolicySummary:
        """Build condensed policy summary from context."""
        triggered_names: list[str] = []
        triggered_categories: list[str] = []

        for pr_dict in ctx.policy_results_for_signals:
            status_str = pr_dict.get("status", "pass")
            if status_str == "triggered":
                triggered_names.append(pr_dict.get("policy_name", "unknown"))
                for cat in pr_dict.get("categories", []):
                    if cat not in triggered_categories:
                        triggered_categories.append(cat)

        return PolicySummary(
            total_policies=ctx.policy_triggered_count
            + ctx.policy_unknown_count
            + ctx.policy_invalid_count
            + max(
                0,
                len(ctx.policy_results_for_signals)
                - ctx.policy_triggered_count
                - ctx.policy_unknown_count
                - ctx.policy_invalid_count,
            ),
            triggered_count=ctx.policy_triggered_count,
            unknown_count=ctx.policy_unknown_count,
            invalid_count=ctx.policy_invalid_count,
            highest_triggered_severity=ctx.policy_highest_triggered_severity,
            triggered_policy_names=triggered_names,
            triggered_policy_categories=triggered_categories,
        )

    def _build_risk_summary(self, ctx: DecisionContext) -> RiskSummary:
        """Build risk summary. In Sprint 6, always unavailable."""
        if ctx.risk_result is not None:
            return RiskSummary(
                overall_score=ctx.risk_result.overall_score,
                risk_level=ctx.risk_result.risk_level,
                available=True,
            )
        return RiskSummary(available=False)

    def _build_drift_summary(self, ctx: DecisionContext) -> DriftSummary:
        """Build drift summary from context."""
        return DriftSummary(
            overall_status=ctx.drift_overall_status,
            severity=ctx.drift_severity,
        )

    # ── Reason & Explanation ────────────────────────────────────────

    def _build_reason(
        self, decision: DecisionStatus, signals: list[DecisionSignal]
    ) -> str:
        """Build human-readable reason for the decision."""
        if decision == DecisionStatus.ALLOW:
            return "All conditions satisfied"

        # Collect the most important signals
        violation_signals = [s for s in signals if s.status == "violation"]
        triggered_signals = [s for s in signals if s.status == "triggered"]
        unknown_signals = [s for s in signals if s.status == "unknown"]
        negative_signals = [s for s in signals if s.status == "negative"]

        parts: list[str] = []

        for sig in violation_signals[:3]:
            parts.append(sig.description)

        for sig in triggered_signals[:2]:
            parts.append(sig.description)

        if not parts and unknown_signals:
            for sig in unknown_signals[:2]:
                parts.append(sig.description)

        if not parts and negative_signals:
            for sig in negative_signals[:2]:
                parts.append(sig.description)

        return "; ".join(parts) if parts else "One or more conditions require review"

    def _build_explanation(
        self, ctx: DecisionContext, signals: list[DecisionSignal]
    ) -> dict[str, Any]:
        """Build structured explanation for frontend rendering."""
        explanation: dict[str, Any] = {}

        # Group signals by source
        by_source: dict[str, list[dict[str, Any]]] = {}
        for sig in signals:
            source = sig.source
            if source not in by_source:
                by_source[source] = []
            by_source[source].append({
                "signal_type": sig.signal_type,
                "status": sig.status,
                "severity": sig.severity,
                "description": sig.description,
            })

        explanation["signals_by_source"] = by_source

        # Policy details
        if ctx.policy_result_available:
            explanation["policy"] = {
                "triggered_count": ctx.policy_triggered_count,
                "unknown_count": ctx.policy_unknown_count,
                "invalid_count": ctx.policy_invalid_count,
                "highest_severity": ctx.policy_highest_triggered_severity,
            }

        # Drift details
        if ctx.drift_result_available:
            explanation["drift"] = {
                "overall_status": ctx.drift_overall_status,
                "severity": ctx.drift_severity,
            }

        # Trust details
        explanation["trust"] = {
            "agent_trust_score": ctx.agent_trust_score,
            "merchant_trusted": ctx.proposal_merchant_trusted,
        }

        # Risk
        explanation["risk"] = {
            "available": ctx.risk_result is not None,
        }

        return explanation


# ── Helper ─────────────────────────────────────────────────────────


def _drift_severity_order_index(sev: str) -> int:
    """Return the numeric index for a drift severity string."""
    try:
        return _DRIFT_SEVERITY_ORDER.index(sev)
    except ValueError:
        return 0
