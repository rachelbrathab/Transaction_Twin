"""Outcome Engine — deterministic feedback classification.

Classifies whether a decision was correct given verified outcome evidence.

Rules:
  - Only VERIFIED outcomes may be used as ground truth.
  - UNVERIFIED client claims must never become calibration ground truth.
  - Never automatically classify as FALSE_POSITIVE without strong evidence.
  - Insufficient evidence → UNKNOWN.
"""

from __future__ import annotations

from app.services.outcome_engine.constants import (
    PENDING_CONFIDENCE,
    STRONG_EVIDENCE_CONFIDENCE,
    UNVERIFIED_CONFIDENCE,
    VERIFIED_CONFIDENCE,
)
from app.services.outcome_engine.models import (
    FeedbackClassification,
    FeedbackType,
    OutcomeEventType,
    VerificationState,
)


def classify_feedback(
    original_decision: str,
    outcome_event_type: str,
    verification_state: str,
    previous_decision: str | None = None,
    previous_outcome: str | None = None,
) -> FeedbackClassification:
    """Classify the feedback for a decision given an outcome event.

    Args:
        original_decision: The original decision (allow/review/block)
        outcome_event_type: The outcome event type
        verification_state: Verification level of the outcome
        previous_decision: Previous decision if overridden (for REVIEW → approve)
        previous_outcome: Previous outcome event type if known

    Returns:
        FeedbackClassification with feedback_type, confidence, and reasoning
    """
    decision = original_decision.lower()
    event = outcome_event_type.lower()
    verification = verification_state.lower()

    # Determine base confidence from verification state
    if verification == VerificationState.VERIFIED:
        base_confidence = VERIFIED_CONFIDENCE
    elif verification == VerificationState.PENDING:
        base_confidence = PENDING_CONFIDENCE
    else:
        base_confidence = UNVERIFIED_CONFIDENCE

    # ── ALLOW + outcomes ───────────────────────────────────────

    if decision == "allow":
        if event == OutcomeEventType.PAYMENT_SUCCESS:
            return FeedbackClassification(
                feedback_type=FeedbackType.CORRECT_ALLOW,
                confidence=base_confidence,
                reasoning="ALLOW decision led to successful payment",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

        if event == OutcomeEventType.CHARGEBACK_RECEIVED:
            if verification == VerificationState.VERIFIED:
                return FeedbackClassification(
                    feedback_type=FeedbackType.POSSIBLE_FALSE_NEGATIVE,
                    confidence=STRONG_EVIDENCE_CONFIDENCE,
                    reasoning=(
                        "ALLOW decision followed by verified chargeback — "
                        "transaction may have been fraudulent"
                    ),
                    decision_value=decision,
                    outcome_event_type=event,
                    verification_state=VerificationState(verification),
                )
            return FeedbackClassification(
                feedback_type=FeedbackType.UNKNOWN,
                confidence=base_confidence,
                reasoning="Unverified chargeback claim — insufficient evidence",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

        if event == OutcomeEventType.FRAUD_CONFIRMED:
            if verification == VerificationState.VERIFIED:
                return FeedbackClassification(
                    feedback_type=FeedbackType.POSSIBLE_FALSE_NEGATIVE,
                    confidence=STRONG_EVIDENCE_CONFIDENCE,
                    reasoning=(
                        "ALLOW decision followed by verified fraud confirmation — "
                        "transaction was fraudulent"
                    ),
                    decision_value=decision,
                    outcome_event_type=event,
                    verification_state=VerificationState(verification),
                )
            return FeedbackClassification(
                feedback_type=FeedbackType.UNKNOWN,
                confidence=base_confidence,
                reasoning="Unverified fraud claim — insufficient evidence",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

        if event == OutcomeEventType.PAYMENT_FAILED:
            return FeedbackClassification(
                feedback_type=FeedbackType.UNKNOWN,
                confidence=base_confidence,
                reasoning=(
                    "ALLOW decision but payment failed — "
                    "insufficient evidence to judge decision correctness"
                ),
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

    # ── BLOCK + outcomes ───────────────────────────────────────

    if decision == "block":
        if event in (
            OutcomeEventType.PAYMENT_CANCELLED,
            OutcomeEventType.PAYMENT_EXPIRED,
        ):
            return FeedbackClassification(
                feedback_type=FeedbackType.CORRECT_BLOCK,
                confidence=base_confidence,
                reasoning="BLOCK decision prevented payment attempt",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

        if event == OutcomeEventType.FRAUD_FALSE_POSITIVE:
            if verification == VerificationState.VERIFIED:
                return FeedbackClassification(
                    feedback_type=FeedbackType.POSSIBLE_FALSE_POSITIVE,
                    confidence=STRONG_EVIDENCE_CONFIDENCE,
                    reasoning=(
                        "BLOCK decision followed by verified false positive — "
                        "transaction was actually safe"
                    ),
                    decision_value=decision,
                    outcome_event_type=event,
                    verification_state=VerificationState(verification),
                )
            return FeedbackClassification(
                feedback_type=FeedbackType.UNKNOWN,
                confidence=base_confidence,
                reasoning="Unverified false positive claim — insufficient evidence",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

    # ── REVIEW + outcomes ──────────────────────────────────────

    if decision == "review":
        if event == OutcomeEventType.MANUAL_APPROVED:
            return FeedbackClassification(
                feedback_type=FeedbackType.CORRECT_REVIEW,
                confidence=base_confidence,
                reasoning="REVIEW decision correctly triggered manual review",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

        if event == OutcomeEventType.MANUAL_REJECTED:
            return FeedbackClassification(
                feedback_type=FeedbackType.CORRECT_REVIEW,
                confidence=base_confidence,
                reasoning="REVIEW decision correctly triggered manual review",
                decision_value=decision,
                outcome_event_type=event,
                verification_state=VerificationState(verification),
            )

    # ── Default: insufficient evidence ─────────────────────────

    return FeedbackClassification(
        feedback_type=FeedbackType.UNKNOWN,
        confidence=base_confidence,
        reasoning=(
            f"Insufficient evidence to classify decision '{decision}' "
            f"with outcome '{event}'"
        ),
        decision_value=decision,
        outcome_event_type=event,
        verification_state=VerificationState(verification),
    )
