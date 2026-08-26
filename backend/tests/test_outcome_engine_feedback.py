"""Tests for Outcome Engine feedback classification.

Pure deterministic tests. No database, no I/O.
"""


from app.services.outcome_engine.feedback import classify_feedback
from app.services.outcome_engine.models import FeedbackType, VerificationState


class TestAllowDecisions:
    """Tests for ALLOW decision feedback classifications."""

    def test_allow_with_payment_success_verified(self):
        fc = classify_feedback("allow", "payment_success", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_ALLOW
        assert fc.confidence == 0.9

    def test_allow_with_payment_success_pending(self):
        fc = classify_feedback("allow", "payment_success", "pending")
        assert fc.feedback_type == FeedbackType.CORRECT_ALLOW
        assert fc.confidence == 0.5

    def test_allow_with_chargeback_verified(self):
        fc = classify_feedback("allow", "chargeback_received", "verified")
        assert fc.feedback_type == FeedbackType.POSSIBLE_FALSE_NEGATIVE
        assert fc.confidence == 0.8

    def test_allow_with_chargeback_unverified(self):
        fc = classify_feedback("allow", "chargeback_received", "unverified")
        assert fc.feedback_type == FeedbackType.UNKNOWN
        assert fc.confidence == 0.2

    def test_allow_with_chargeback_pending(self):
        fc = classify_feedback("allow", "chargeback_received", "pending")
        assert fc.feedback_type == FeedbackType.UNKNOWN
        assert fc.confidence == 0.5

    def test_allow_with_fraud_confirmed_verified(self):
        fc = classify_feedback("allow", "fraud_confirmed", "verified")
        assert fc.feedback_type == FeedbackType.POSSIBLE_FALSE_NEGATIVE
        assert fc.confidence == 0.8

    def test_allow_with_fraud_confirmed_unverified(self):
        fc = classify_feedback("allow", "fraud_confirmed", "unverified")
        assert fc.feedback_type == FeedbackType.UNKNOWN
        assert fc.confidence == 0.2

    def test_allow_with_payment_failed(self):
        fc = classify_feedback("allow", "payment_failed", "verified")
        assert fc.feedback_type == FeedbackType.UNKNOWN


class TestBlockDecisions:
    """Tests for BLOCK decision feedback classifications."""

    def test_block_with_payment_cancelled(self):
        fc = classify_feedback("block", "payment_cancelled", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_BLOCK

    def test_block_with_payment_expired(self):
        fc = classify_feedback("block", "payment_expired", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_BLOCK

    def test_block_with_false_positive_verified(self):
        fc = classify_feedback("block", "fraud_false_positive", "verified")
        assert fc.feedback_type == FeedbackType.POSSIBLE_FALSE_POSITIVE
        assert fc.confidence == 0.8

    def test_block_with_false_positive_unverified(self):
        fc = classify_feedback("block", "fraud_false_positive", "unverified")
        assert fc.feedback_type == FeedbackType.UNKNOWN

    def test_block_with_false_positive_pending(self):
        fc = classify_feedback("block", "fraud_false_positive", "pending")
        assert fc.feedback_type == FeedbackType.UNKNOWN

    def test_block_with_payment_success(self):
        """BLOCK + PAYMENT_SUCCESS → UNKNOWN (unexpected combination)."""
        fc = classify_feedback("block", "payment_success", "verified")
        assert fc.feedback_type == FeedbackType.UNKNOWN


class TestReviewDecisions:
    """Tests for REVIEW decision feedback classifications."""

    def test_review_with_manual_approved(self):
        fc = classify_feedback("review", "manual_approved", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_REVIEW

    def test_review_with_manual_approved_pending(self):
        fc = classify_feedback("review", "manual_approved", "pending")
        assert fc.feedback_type == FeedbackType.CORRECT_REVIEW

    def test_review_with_manual_rejected(self):
        fc = classify_feedback("review", "manual_rejected", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_REVIEW

    def test_review_with_payment_success(self):
        """REVIEW + PAYMENT_SUCCESS → UNKNOWN."""
        fc = classify_feedback("review", "payment_success", "verified")
        assert fc.feedback_type == FeedbackType.UNKNOWN


class TestVerificationConfidence:
    """Tests for confidence levels based on verification state."""

    def test_verified_higher_confidence_than_pending(self):
        fc_verified = classify_feedback("allow", "payment_success", "verified")
        fc_pending = classify_feedback("allow", "payment_success", "pending")
        assert fc_verified.confidence > fc_pending.confidence

    def test_pending_higher_confidence_than_unverified(self):
        fc_pending = classify_feedback("allow", "payment_success", "pending")
        fc_unverified = classify_feedback("allow", "payment_success", "unverified")
        assert fc_pending.confidence > fc_unverified.confidence

    def test_verified_chargedback_confidence(self):
        fc = classify_feedback("allow", "chargeback_received", "verified")
        assert fc.confidence == 0.8

    def test_unverified_chargedback_confidence(self):
        fc = classify_feedback("allow", "chargeback_received", "unverified")
        assert fc.confidence == 0.2


class TestUnknownSemantics:
    """Tests for UNKNOWN semantics — insufficient evidence."""

    def test_unknown_for_unrecognized_combination(self):
        fc = classify_feedback("block", "payment_success", "verified")
        assert fc.feedback_type == FeedbackType.UNKNOWN

    def test_unknown_for_unverified_fraud_claim(self):
        fc = classify_feedback("allow", "fraud_confirmed", "unverified")
        assert fc.feedback_type == FeedbackType.UNKNOWN

    def test_unknown_for_unverified_false_positive(self):
        fc = classify_feedback("block", "fraud_false_positive", "unverified")
        assert fc.feedback_type == FeedbackType.UNKNOWN

    def test_unknown_has_reasoning(self):
        fc = classify_feedback("block", "payment_success", "verified")
        assert len(fc.reasoning) > 0


class TestFeedbackReasoning:
    """Tests for feedback reasoning content."""

    def test_correct_allow_reasoning(self):
        fc = classify_feedback("allow", "payment_success", "verified")
        assert "successful" in fc.reasoning.lower()

    def test_false_negative_reasoning(self):
        fc = classify_feedback("allow", "chargeback_received", "verified")
        assert "chargeback" in fc.reasoning.lower()

    def test_correct_review_reasoning(self):
        fc = classify_feedback("review", "manual_approved", "verified")
        assert "review" in fc.reasoning.lower()

    def test_correct_block_reasoning(self):
        fc = classify_feedback("block", "payment_cancelled", "verified")
        assert "blocked" in fc.reasoning.lower() or "prevent" in fc.reasoning.lower()


class TestEdgeCases:
    """Edge case tests for feedback classification."""

    def test_case_insensitive_decision(self):
        """Feedback should handle case-insensitive decision values."""
        fc = classify_feedback("ALLOW", "payment_success", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_ALLOW

    def test_case_insensitive_event_type(self):
        fc = classify_feedback("allow", "PAYMENT_SUCCESS", "verified")
        assert fc.feedback_type == FeedbackType.CORRECT_ALLOW

    def test_case_insensitive_verification(self):
        fc = classify_feedback("allow", "payment_success", "VERIFIED")
        assert fc.feedback_type == FeedbackType.CORRECT_ALLOW

    def test_decision_value_preserved(self):
        fc = classify_feedback("block", "payment_cancelled", "verified")
        assert fc.decision_value == "block"

    def test_outcome_event_type_preserved(self):
        fc = classify_feedback("allow", "payment_success", "verified")
        assert fc.outcome_event_type == "payment_success"

    def test_verification_state_preserved(self):
        fc = classify_feedback("allow", "payment_success", "verified")
        assert fc.verification_state == VerificationState.VERIFIED
