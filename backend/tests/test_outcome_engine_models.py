"""Tests for Outcome Engine domain models."""


import pytest

from app.services.outcome_engine.models import (
    FeedbackClassification,
    FeedbackType,
    OutcomeEvent,
    OutcomeEventType,
    OutcomeSource,
    TransactionEventRecord,
    TransactionHistory,
    TransactionLifecycle,
    VerificationState,
)


class TestTransactionLifecycle:
    """Tests for TransactionLifecycle enum."""

    def test_all_states(self):
        """Verify all lifecycle states exist."""
        states = list(TransactionLifecycle)
        assert len(states) == 13
        assert TransactionLifecycle.PROPOSED in states
        assert TransactionLifecycle.DECIDED in states
        assert TransactionLifecycle.APPROVED in states
        assert TransactionLifecycle.REJECTED in states
        assert TransactionLifecycle.PROCESSING in states
        assert TransactionLifecycle.COMPLETED in states
        assert TransactionLifecycle.FAILED in states
        assert TransactionLifecycle.CANCELLED in states
        assert TransactionLifecycle.EXPIRED in states
        assert TransactionLifecycle.REFUNDED in states
        assert TransactionLifecycle.PARTIALLY_REFUNDED in states
        assert TransactionLifecycle.CHARGEBACK in states
        assert TransactionLifecycle.DISPUTED in states

    def test_string_values(self):
        """Verify enum string values."""
        assert TransactionLifecycle.PROPOSED.value == "proposed"
        assert TransactionLifecycle.DECIDED.value == "decided"
        assert TransactionLifecycle.APPROVED.value == "approved"
        assert TransactionLifecycle.COMPLETED.value == "completed"


class TestOutcomeEventType:
    """Tests for OutcomeEventType enum."""

    def test_all_types(self):
        """Verify all event types exist."""
        types = list(OutcomeEventType)
        assert len(types) == 16

    def test_decision_created(self):
        assert OutcomeEventType.DECISION_CREATED.value == "decision_created"

    def test_payment_success(self):
        assert OutcomeEventType.PAYMENT_SUCCESS.value == "payment_success"

    def test_chargeback_received(self):
        assert OutcomeEventType.CHARGEBACK_RECEIVED.value == "chargeback_received"


class TestOutcomeSource:
    """Tests for OutcomeSource enum."""

    def test_all_sources(self):
        sources = list(OutcomeSource)
        assert len(sources) == 7

    def test_values(self):
        assert OutcomeSource.PAYMENT_PROVIDER.value == "payment_provider"
        assert OutcomeSource.ADMIN.value == "admin"
        assert OutcomeSource.SYSTEM.value == "system"
        assert OutcomeSource.SIMULATOR.value == "simulator"


class TestVerificationState:
    """Tests for VerificationState enum."""

    def test_all_states(self):
        states = list(VerificationState)
        assert len(states) == 3

    def test_values(self):
        assert VerificationState.VERIFIED.value == "verified"
        assert VerificationState.PENDING.value == "pending"
        assert VerificationState.UNVERIFIED.value == "unverified"


class TestFeedbackType:
    """Tests for FeedbackType enum."""

    def test_all_types(self):
        types = list(FeedbackType)
        assert len(types) == 6

    def test_values(self):
        assert FeedbackType.CORRECT_ALLOW.value == "correct_allow"
        assert FeedbackType.CORRECT_BLOCK.value == "correct_block"
        assert FeedbackType.CORRECT_REVIEW.value == "correct_review"
        assert FeedbackType.POSSIBLE_FALSE_POSITIVE.value == "possible_false_positive"
        assert FeedbackType.POSSIBLE_FALSE_NEGATIVE.value == "possible_false_negative"
        assert FeedbackType.UNKNOWN.value == "unknown"


class TestOutcomeEventModel:
    """Tests for OutcomeEvent Pydantic model."""

    def test_valid_event(self):
        event = OutcomeEvent(
            event_id="evt-123",
            transaction_id="txn-456",
            event_type=OutcomeEventType.PAYMENT_SUCCESS,
            source=OutcomeSource.PAYMENT_PROVIDER,
            verification_state=VerificationState.VERIFIED,
            sequence_number=1,
        )
        assert event.event_id == "evt-123"
        assert event.transaction_id == "txn-456"
        assert event.event_type == OutcomeEventType.PAYMENT_SUCCESS
        assert event.source == OutcomeSource.PAYMENT_PROVIDER
        assert event.verification_state == VerificationState.VERIFIED
        assert event.sequence_number == 1
        assert event.payload == {}

    def test_event_with_provider(self):
        event = OutcomeEvent(
            event_id="evt-123",
            transaction_id="txn-456",
            event_type=OutcomeEventType.PAYMENT_SUCCESS,
            source=OutcomeSource.PAYMENT_PROVIDER,
            provider="razorpay",
            external_event_id="ext-789",
            sequence_number=1,
        )
        assert event.provider == "razorpay"
        assert event.external_event_id == "ext-789"

    def test_event_sequence_must_be_positive(self):
        with pytest.raises(Exception):
            OutcomeEvent(
                event_id="evt-123",
                transaction_id="txn-456",
                event_type=OutcomeEventType.PAYMENT_SUCCESS,
                source=OutcomeSource.PAYMENT_PROVIDER,
                sequence_number=0,
            )


class TestFeedbackClassificationModel:
    """Tests for FeedbackClassification Pydantic model."""

    def test_valid_classification(self):
        fc = FeedbackClassification(
            feedback_type=FeedbackType.CORRECT_ALLOW,
            confidence=0.9,
            reasoning="Test reasoning",
            decision_value="allow",
            outcome_event_type="payment_success",
            verification_state=VerificationState.VERIFIED,
        )
        assert fc.feedback_type == FeedbackType.CORRECT_ALLOW
        assert fc.confidence == 0.9
        assert fc.reasoning == "Test reasoning"

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            FeedbackClassification(
                feedback_type=FeedbackType.CORRECT_ALLOW,
                confidence=1.5,  # out of bounds
                reasoning="Test",
                decision_value="allow",
                outcome_event_type="payment_success",
                verification_state=VerificationState.VERIFIED,
            )

    def test_negative_confidence_rejected(self):
        with pytest.raises(Exception):
            FeedbackClassification(
                feedback_type=FeedbackType.CORRECT_ALLOW,
                confidence=-0.1,  # negative
                reasoning="Test",
                decision_value="allow",
                outcome_event_type="payment_success",
                verification_state=VerificationState.VERIFIED,
            )


class TestTransactionEventRecord:
    """Tests for TransactionEventRecord model."""

    def test_valid_record(self):
        record = TransactionEventRecord(
            event_id="evt-123",
            event_type="payment_success",
            source="payment_provider",
            verification_state="verified",
            sequence_number=1,
            payload={"key": "value"},
            created_at="2026-01-01T00:00:00Z",
        )
        assert record.event_id == "evt-123"
        assert record.event_type == "payment_success"


class TestTransactionHistory:
    """Tests for TransactionHistory model."""

    def test_valid_history(self):
        history = TransactionHistory(
            transaction_id="txn-123",
            current_status="completed",
            decision="allow",
        )
        assert history.transaction_id == "txn-123"
        assert history.current_status == "completed"
        assert history.decision == "allow"
        assert history.events == []
        assert history.feedback is None

    def test_history_with_events(self):
        events = [
            TransactionEventRecord(
                event_id="evt-1",
                event_type="decision_created",
                source="system",
                verification_state="verified",
                sequence_number=1,
                created_at="2026-01-01T00:00:00Z",
            )
        ]
        history = TransactionHistory(
            transaction_id="txn-123",
            current_status="decided",
            decision="allow",
            events=events,
        )
        assert len(history.events) == 1
