"""Calibration Intelligence — dataset builder.

Builds a CalibrationDataset from pre-fetched Transaction, Decision,
and TransactionEvent records. Pure function — no database access.

UNKNOWN feedback is never used as ground truth.
UNVERIFIED/PENDING outcomes are never used as ground truth.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.calibration_intelligence.constants import (
    ELIGIBLE_FEEDBACK_TYPES,
    ELIGIBLE_VERIFICATION_STATES,
    MIN_FEEDBACK_CONFIDENCE,
)
from app.services.calibration_intelligence.models import (
    CalibrationDataset,
    CalibrationSample,
)


def build_dataset(
    transaction_records: list[dict],
    decision_records: list[dict],
    outcome_records: list[dict],
    agent_map: dict[str, str] | None = None,
    window_days: int = 30,
) -> CalibrationDataset:
    """Build a calibration dataset from pre-fetched records.

    Args:
        transaction_records: List of dicts with keys:
            id, user_id, agent_id, status, amount, currency,
            transaction_type, created_at
        decision_records: List of dicts with keys:
            id, transaction_id, decision, policy_id, explanation,
            created_at
        outcome_records: List of dicts with keys:
            transaction_id, event_type, verification_state,
            created_at
        agent_map: Optional mapping of intent_id → agent_id
        window_days: Analysis window in days

    Returns:
        CalibrationDataset with eligible and excluded samples.
    """
    now = datetime.now(UTC).isoformat()

    # Build lookup structures
    decision_by_txn: dict[str, dict] = {}
    for d in decision_records:
        txn_id = d.get("transaction_id", "")
        if txn_id:
            # Keep the latest decision per transaction
            if txn_id not in decision_by_txn:
                decision_by_txn[txn_id] = d
            elif d.get("created_at", "") > decision_by_txn[txn_id].get(
                "created_at", ""
            ):
                decision_by_txn[txn_id] = d

    # Build outcome lookup: most recent verified outcome per transaction
    outcome_by_txn: dict[str, dict] = {}
    # Track ALL non-decision outcomes per transaction (including excluded)
    # so we can distinguish 'no outcome' from 'unverified outcome exists'
    all_outcomes_by_txn: dict[str, list[dict]] = {}
    for o in outcome_records:
        txn_id = o.get("transaction_id", "")
        if not txn_id:
            continue
        # Skip decision_created events (they're not outcomes)
        if o.get("event_type") == "decision_created":
            continue
        all_outcomes_by_txn.setdefault(txn_id, []).append(o)
        # Only keep verified outcomes for the outcome lookup
        if o.get("verification_state") not in ELIGIBLE_VERIFICATION_STATES:
            continue
        # Keep the most recent verified outcome per transaction
        if txn_id not in outcome_by_txn:
            outcome_by_txn[txn_id] = o
        elif o.get("created_at", "") > outcome_by_txn[txn_id].get(
            "created_at", ""
        ):
            outcome_by_txn[txn_id] = o

    # Build samples
    samples: list[CalibrationSample] = []
    exclusion_counts: dict[str, int] = {}

    for txn in transaction_records:
        txn_id = txn.get("id", "")
        if not txn_id:
            continue

        # Check if decision exists
        decision = decision_by_txn.get(txn_id)
        if decision is None:
            sample = _excluded_sample(
                txn, "missing_decision", SampleExclusionReason.MISSING_DECISION,
            )
            samples.append(sample)
            exclusion_counts["missing_decision"] = (
                exclusion_counts.get("missing_decision", 0) + 1
            )
            continue

        # Check if verified outcome exists
        outcome = outcome_by_txn.get(txn_id)
        if outcome is None:
            # Determine if an outcome event exists but was excluded
            existing_outcomes = all_outcomes_by_txn.get(txn_id, [])
            has_non_verified = any(
                o.get("verification_state") not in ELIGIBLE_VERIFICATION_STATES
                for o in existing_outcomes
            )
            has_pending = any(
                o.get("verification_state") == "pending"
                for o in existing_outcomes
            )

            if has_pending and not has_non_verified:
                reason = SampleExclusionReason.PENDING_OUTCOME
                label = "pending_outcome"
            elif has_non_verified or (has_pending):
                reason = SampleExclusionReason.UNVERIFIED_OUTCOME
                label = "unverified_outcome"
            else:
                reason = SampleExclusionReason.PENDING_OUTCOME
                label = "pending_outcome"

            sample = _excluded_sample(txn, label, reason)
            samples.append(sample)
            exclusion_counts[label] = exclusion_counts.get(label, 0) + 1
            continue

        # Classify feedback
        feedback_type = _classify_feedback_type(
            decision.get("decision", ""),
            outcome.get("event_type", ""),
        )

        # Check eligibility
        exclusion = _check_eligibility(
            feedback_type,
            outcome.get("verification_state", ""),
            decision.get("feedback_confidence", 1.0),
        )

        if exclusion is not None:
            sample = _excluded_sample(txn, feedback_type, exclusion)
            samples.append(sample)
            exclusion_counts[exclusion.value] = (
                exclusion_counts.get(exclusion.value, 0) + 1
            )
            continue

        # Extract risk level from explanation
        explanation = decision.get("explanation", {})
        risk_info = explanation.get("risk", {}) if isinstance(
            explanation, dict
        ) else {}
        risk_level = risk_info.get("level") if isinstance(
            risk_info, dict
        ) else None
        risk_available = bool(
            risk_info.get("available", False)
        ) if isinstance(risk_info, dict) else False

        # Extract signal/policy counts from explanation
        policy_info = explanation.get("policy", {}) if isinstance(
            explanation, dict
        ) else {}
        signal_count = decision.get("signal_count", 0)
        policy_triggered = (
            policy_info.get("triggered_count", 0)
            if isinstance(policy_info, dict)
            else 0
        )

        sample = CalibrationSample(
            transaction_id=txn_id,
            decision_id=decision.get("id", ""),
            original_decision=decision.get("decision", ""),
            final_lifecycle_status=txn.get("status", ""),
            feedback_type=feedback_type,
            feedback_confidence=outcome.get("feedback_confidence", 0.9),
            verification_state=outcome.get("verification_state", "verified"),
            risk_level=risk_level,
            risk_available=risk_available,
            signal_count=signal_count,
            policy_triggered_count=policy_triggered,
            policy_id=decision.get("policy_id"),
            drift_severity=decision.get("drift_severity"),
            agent_id=txn.get("agent_id"),
            amount=float(txn["amount"]) if txn.get("amount") else None,
            currency=txn.get("currency"),
            transaction_type=txn.get("transaction_type"),
            created_at=decision.get("created_at", ""),
            sample_eligible=True,
        )
        samples.append(sample)

    eligible = [s for s in samples if s.sample_eligible]
    excluded = [s for s in samples if not s.sample_eligible]

    return CalibrationDataset(
        samples=samples,
        total_samples=len(samples),
        eligible_samples=len(eligible),
        excluded_samples=len(excluded),
        exclusion_summary=exclusion_counts,
        window_days=window_days,
        computed_at=now,
    )


# ── Internal helpers ───────────────────────────────────────────────


def _classify_feedback_type(decision: str, event_type: str) -> str:
    """Deterministically classify feedback type from decision + outcome."""
    decision = decision.lower()
    event = event_type.lower()

    if decision == "allow":
        if event == "payment_success":
            return "correct_allow"
        if event in ("chargeback_received", "fraud_confirmed"):
            return "possible_false_negative"
    elif decision == "block":
        if event in ("payment_cancelled", "payment_expired"):
            return "correct_block"
        if event == "fraud_false_positive":
            return "possible_false_positive"
    elif decision == "review":
        if event in ("manual_approved", "manual_rejected"):
            return "correct_review"

    return "unknown"


from app.services.calibration_intelligence.models import SampleExclusionReason  # noqa: E402


def _check_eligibility(
    feedback_type: str,
    verification_state: str,
    confidence: float,
) -> SampleExclusionReason | None:
    """Check if a sample is eligible for calibration.

    Returns None if eligible, or the exclusion reason if not.
    """
    if feedback_type not in ELIGIBLE_FEEDBACK_TYPES:
        return SampleExclusionReason.UNKNOWN_FEEDBACK

    if verification_state not in ELIGIBLE_VERIFICATION_STATES:
        if verification_state == "pending":
            return SampleExclusionReason.PENDING_OUTCOME
        return SampleExclusionReason.UNVERIFIED_OUTCOME

    if confidence < MIN_FEEDBACK_CONFIDENCE:
        return SampleExclusionReason.LOW_CONFIDENCE

    return None


def _excluded_sample(
    txn: dict,
    feedback_type: str,
    reason: SampleExclusionReason,
) -> CalibrationSample:
    """Create an excluded calibration sample."""
    return CalibrationSample(
        transaction_id=txn.get("id", ""),
        decision_id="",
        original_decision="",
        final_lifecycle_status=txn.get("status", ""),
        feedback_type=feedback_type,
        feedback_confidence=0.0,
        verification_state="unknown",
        created_at=txn.get("created_at", ""),
        sample_eligible=False,
        exclusion_reason=reason.value,
    )
