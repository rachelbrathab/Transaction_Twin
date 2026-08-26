"""Tests for Outcome Engine state machine.

Pure deterministic tests. No database, no I/O.
"""

from datetime import datetime

from app.services.outcome_engine.state_machine import (
    get_next_status,
    get_terminal_states,
    is_terminal,
    validate_event_order,
    validate_transition,
)


class TestGetNextStatus:
    """Tests for get_next_status."""

    def test_proposed_to_decided(self):
        result = get_next_status("proposed", "decision_created")
        assert result == "decided"

    def test_decided_to_approved(self):
        result = get_next_status("decided", "manual_approved")
        assert result == "approved"

    def test_decided_to_rejected(self):
        result = get_next_status("decided", "manual_rejected")
        assert result == "rejected"

    def test_decided_to_processing(self):
        result = get_next_status("decided", "payment_initiated")
        assert result == "processing"

    def test_approved_to_processing(self):
        result = get_next_status("approved", "payment_initiated")
        assert result == "processing"

    def test_processing_to_completed(self):
        result = get_next_status("processing", "payment_success")
        assert result == "completed"

    def test_processing_to_failed(self):
        result = get_next_status("processing", "payment_failed")
        assert result == "failed"

    def test_processing_to_cancelled(self):
        result = get_next_status("processing", "payment_cancelled")
        assert result == "cancelled"

    def test_processing_to_expired(self):
        result = get_next_status("processing", "payment_expired")
        assert result == "expired"

    def test_failed_to_processing(self):
        """Retry after FAILED."""
        result = get_next_status("failed", "payment_initiated")
        assert result == "processing"

    def test_completed_to_refunded(self):
        result = get_next_status("completed", "refund_completed")
        assert result == "refunded"

    def test_completed_to_partially_refunded(self):
        result = get_next_status("completed", "partial_refund")
        assert result == "partially_refunded"

    def test_completed_to_chargeback(self):
        result = get_next_status("completed", "chargeback_received")
        assert result == "chargeback"

    def test_completed_to_disputed(self):
        result = get_next_status("completed", "dispute_opened")
        assert result == "disputed"

    def test_partially_refunded_to_refunded(self):
        result = get_next_status("partially_refunded", "refund_completed")
        assert result == "refunded"

    def test_partially_refunded_to_partially_refunded(self):
        """Multiple partial refunds."""
        result = get_next_status("partially_refunded", "partial_refund")
        assert result == "partially_refunded"

    def test_disputed_to_disputed(self):
        """DISPUTE_RESOLVED keeps the disputed state."""
        result = get_next_status("disputed", "dispute_resolved")
        assert result == "disputed"

    def test_invalid_transition_returns_none(self):
        result = get_next_status("proposed", "payment_success")
        assert result is None

    def test_invalid_transition_from_terminal(self):
        result = get_next_status("completed", "payment_success")
        assert result is None


class TestValidateTransition:
    """Tests for validate_transition."""

    def test_valid_transition(self):
        is_valid, next_status, error = validate_transition("proposed", "decision_created")
        assert is_valid is True
        assert next_status == "decided"
        assert error is None

    def test_invalid_transition(self):
        is_valid, next_status, error = validate_transition("proposed", "payment_success")
        assert is_valid is False
        assert next_status is None
        assert "Invalid transition" in error

    def test_idempotent_decision_created(self):
        """DECISION_CREATED is idempotent if already DECIDED."""
        is_valid, next_status, error = validate_transition("decided", "decision_created")
        assert is_valid is True
        assert next_status == "decided"
        assert error is None

    def test_idempotent_payment_success(self):
        """PAYMENT_SUCCESS is idempotent if already COMPLETED."""
        is_valid, next_status, error = validate_transition("completed", "payment_success")
        assert is_valid is True
        assert next_status == "completed"

    def test_idempotent_payment_failed(self):
        is_valid, next_status, error = validate_transition("failed", "payment_failed")
        assert is_valid is True
        assert next_status == "failed"

    def test_idempotent_manual_approved(self):
        is_valid, next_status, error = validate_transition("approved", "manual_approved")
        assert is_valid is True
        assert next_status == "approved"

    def test_idempotent_manual_rejected(self):
        is_valid, next_status, error = validate_transition("rejected", "manual_rejected")
        assert is_valid is True
        assert next_status == "rejected"


class TestIsTerminal:
    """Tests for is_terminal."""

    def test_rejected_is_terminal(self):
        assert is_terminal("rejected") is True

    def test_completed_is_terminal(self):
        assert is_terminal("completed") is True

    def test_cancelled_is_terminal(self):
        assert is_terminal("cancelled") is True

    def test_expired_is_terminal(self):
        assert is_terminal("expired") is True

    def test_refunded_is_terminal(self):
        assert is_terminal("refunded") is True

    def test_chargeback_is_terminal(self):
        assert is_terminal("chargeback") is True

    def test_proposed_not_terminal(self):
        assert is_terminal("proposed") is False

    def test_decided_not_terminal(self):
        assert is_terminal("decided") is False

    def test_processing_not_terminal(self):
        assert is_terminal("processing") is False

    def test_approved_not_terminal(self):
        assert is_terminal("approved") is False

    def test_partially_refunded_not_terminal(self):
        assert is_terminal("partially_refunded") is False


class TestValidateEventOrder:
    """Tests for validate_event_order."""

    def test_valid_order(self):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 1, 0, 0, 10)
        is_valid, error = validate_event_order(t1, t2, 1, 2)
        assert is_valid is True
        assert error is None

    def test_first_event(self):
        t = datetime(2026, 1, 1, 0, 0, 0)
        is_valid, error = validate_event_order(None, t, 0, 1)
        assert is_valid is True

    def test_duplicate_sequence_rejected(self):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 1, 0, 0, 10)
        is_valid, error = validate_event_order(t1, t2, 1, 1)
        assert is_valid is False
        assert "must be >" in error

    def test_decreasing_sequence_rejected(self):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 1, 0, 0, 10)
        is_valid, error = validate_event_order(t1, t2, 3, 2)
        assert is_valid is False

    def test_clock_skew_within_tolerance(self):
        """Events within clock skew tolerance should be accepted."""
        t1 = datetime(2026, 1, 1, 0, 5, 0)
        t2 = datetime(2026, 1, 1, 0, 0, 0)  # 5 minutes earlier (within tolerance)
        is_valid, error = validate_event_order(t1, t2, 1, 2)
        assert is_valid is True

    def test_clock_skew_exceeds_tolerance(self):
        """Events beyond clock skew tolerance should be rejected."""
        t1 = datetime(2026, 1, 1, 0, 10, 0)
        t2 = datetime(2026, 1, 1, 0, 0, 0)  # 10 minutes earlier (beyond 5 min tolerance)
        is_valid, error = validate_event_order(t1, t2, 1, 2)
        assert is_valid is False
        assert "before" in error


class TestGetTerminalStates:
    """Tests for get_terminal_states."""

    def test_contains_expected_states(self):
        terminals = get_terminal_states()
        assert "rejected" in terminals
        assert "completed" in terminals
        assert "cancelled" in terminals
        assert "expired" in terminals
        assert "refunded" in terminals
        assert "chargeback" in terminals

    def test_does_not_contain_non_terminal(self):
        terminals = get_terminal_states()
        assert "proposed" not in terminals
        assert "decided" not in terminals
        assert "processing" not in terminals
        assert "approved" not in terminals
        assert "partially_refunded" not in terminals


class TestStateMachineEdgeCases:
    """Edge case tests for the state machine."""

    def test_retry_after_failed(self):
        """FAILED → PROCESSING → COMPLETED is valid."""
        is_valid1, next1, _ = validate_transition("failed", "payment_initiated")
        assert is_valid1 is True
        assert next1 == "processing"

        is_valid2, next2, _ = validate_transition("processing", "payment_success")
        assert is_valid2 is True
        assert next2 == "completed"

    def test_full_lifecycle_happy_path(self):
        """proposed → decided → processing → completed."""
        steps = [
            ("proposed", "decision_created", "decided"),
            ("decided", "payment_initiated", "processing"),
            ("processing", "payment_success", "completed"),
        ]
        for current, event, expected in steps:
            is_valid, next_status, error = validate_transition(current, event)
            assert is_valid, f"Transition {current}+{event} failed: {error}"
            assert next_status == expected

    def test_full_lifecycle_with_review(self):
        """proposed → decided → approved → processing → completed."""
        steps = [
            ("proposed", "decision_created", "decided"),
            ("decided", "manual_approved", "approved"),
            ("approved", "payment_initiated", "processing"),
            ("processing", "payment_success", "completed"),
        ]
        for current, event, expected in steps:
            is_valid, next_status, error = validate_transition(current, event)
            assert is_valid, f"Transition {current}+{event} failed: {error}"
            assert next_status == expected

    def test_full_lifecycle_with_rejection(self):
        """proposed → decided → rejected (terminal)."""
        steps = [
            ("proposed", "decision_created", "decided"),
            ("decided", "manual_rejected", "rejected"),
        ]
        for current, event, expected in steps:
            is_valid, next_status, error = validate_transition(current, event)
            assert is_valid, f"Transition {current}+{event} failed: {error}"
            assert next_status == expected

        assert is_terminal("rejected")

    def test_refund_after_chargeback_rejected(self):
        """Cannot refund after chargeback (terminal)."""
        is_valid, _, _ = validate_transition("chargeback", "refund_completed")
        assert is_valid is False

    def test_payment_after_refund_rejected(self):
        """Cannot initiate payment after refund (terminal)."""
        is_valid, _, _ = validate_transition("refunded", "payment_initiated")
        assert is_valid is False

    def test_partial_refund_to_full_refund(self):
        """PARTIALLY_REFUNDED → REFUNDED."""
        is_valid, next_status, error = validate_transition(
            "partially_refunded", "refund_completed"
        )
        assert is_valid is True
        assert next_status == "refunded"

    def test_multiple_partial_refunds(self):
        """PARTIALLY_REFUNDED → PARTIALLY_REFUNDED."""
        is_valid, next_status, error = validate_transition(
            "partially_refunded", "partial_refund"
        )
        assert is_valid is True
        assert next_status == "partially_refunded"
