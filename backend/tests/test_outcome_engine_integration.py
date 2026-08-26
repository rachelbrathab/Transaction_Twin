"""Tests for Outcome Engine integration, security, and API endpoints."""


from app.services.outcome_engine.constants import (
    CLOCK_SKEW_TOLERANCE_SECONDS,
    OUTCOME_ENGINE_VERSION,
)
from app.services.outcome_engine.feedback import classify_feedback
from app.services.outcome_engine.state_machine import (
    get_terminal_states,
    validate_transition,
)


class TestSecurity:
    """Security tests for the outcome engine."""

    def test_no_eval_in_state_machine(self):
        """State machine must not contain eval."""
        import inspect

        from app.services.outcome_engine import state_machine
        source = inspect.getsource(state_machine)
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_eval_in_feedback(self):
        """Feedback must not contain eval."""
        import inspect

        from app.services.outcome_engine import feedback
        source = inspect.getsource(feedback)
        assert "eval(" not in source
        assert "exec(" not in source

    def test_no_subprocess_in_state_machine(self):
        import inspect

        from app.services.outcome_engine import state_machine
        source = inspect.getsource(state_machine)
        assert "subprocess" not in source
        assert "os.system" not in source

    def test_no_subprocess_in_feedback(self):
        import inspect

        from app.services.outcome_engine import feedback
        source = inspect.getsource(feedback)
        assert "subprocess" not in source
        assert "os.system" not in source

    def test_no_dynamic_imports_in_state_machine(self):
        import inspect

        from app.services.outcome_engine import state_machine
        source = inspect.getsource(state_machine)
        assert "__import__" not in source
        assert "importlib" not in source

    def test_no_dynamic_imports_in_feedback(self):
        import inspect

        from app.services.outcome_engine import feedback
        source = inspect.getsource(feedback)
        assert "__import__" not in source
        assert "importlib" not in source

    def test_no_llm_in_state_machine(self):
        import inspect

        from app.services.outcome_engine import state_machine
        source = inspect.getsource(state_machine)
        assert "openai" not in source.lower()
        assert "anthropic" not in source.lower()
        assert "llm" not in source.lower()

    def test_no_llm_in_feedback(self):
        import inspect

        from app.services.outcome_engine import feedback
        source = inspect.getsource(feedback)
        assert "openai" not in source.lower()
        assert "anthropic" not in source.lower()
        assert "llm" not in source.lower()

    def test_no_payment_execution_in_state_machine(self):
        import inspect

        from app.services.outcome_engine import state_machine
        source = inspect.getsource(state_machine)
        assert "razorpay" not in source.lower()
        # 'chargeback' is a domain concept, not payment execution
        assert "payment.execute" not in source.lower()
        assert "capture" not in source.lower()

    def test_no_database_in_state_machine(self):
        import inspect

        from app.services.outcome_engine import state_machine
        source = inspect.getsource(state_machine)
        assert "sqlalchemy" not in source.lower()
        assert "session" not in source.lower()

    def test_no_database_in_feedback(self):
        import inspect

        from app.services.outcome_engine import feedback
        source = inspect.getsource(feedback)
        assert "sqlalchemy" not in source.lower()
        assert "session" not in source.lower()


class TestConstants:
    """Tests for outcome engine constants."""

    def test_engine_version(self):
        assert OUTCOME_ENGINE_VERSION == "outcome-v1"

    def test_clock_skew_tolerance(self):
        assert CLOCK_SKEW_TOLERANCE_SECONDS == 300


class TestDeterminism:
    """Tests that the engine is deterministic."""

    def test_state_machine_deterministic(self):
        """Same inputs produce same outputs."""
        result1 = validate_transition("proposed", "decision_created")
        result2 = validate_transition("proposed", "decision_created")
        assert result1 == result2

    def test_feedback_deterministic(self):
        """Same inputs produce same feedback."""
        fc1 = classify_feedback("allow", "payment_success", "verified")
        fc2 = classify_feedback("allow", "payment_success", "verified")
        assert fc1.feedback_type == fc2.feedback_type
        assert fc1.confidence == fc2.confidence

    def test_terminal_states_deterministic(self):
        """Terminal states are consistent."""
        t1 = get_terminal_states()
        t2 = get_terminal_states()
        assert t1 == t2

    def test_multiple_calls_same_result(self):
        """Many calls produce the same result."""
        results = [
            validate_transition("processing", "payment_success")
            for _ in range(100)
        ]
        assert all(r == results[0] for r in results)


class TestBackwardCompatibility:
    """Tests that existing behavior is preserved."""

    def test_existing_transition_rules_still_work(self):
        """All Sprint 7-11 transition rules still function."""
        # These were the original transitions
        assert validate_transition("proposed", "decision_created")[0] is True
        assert validate_transition("processing", "payment_success")[0] is True
        assert validate_transition("processing", "payment_failed")[0] is True

    def test_existing_terminal_states_unchanged(self):
        terminals = get_terminal_states()
        assert "completed" in terminals
        assert "rejected" in terminals

    def test_new_states_are_additive(self):
        """New lifecycle states don't break old ones."""
        assert validate_transition("decided", "manual_approved")[0] is True
        assert validate_transition("decided", "manual_rejected")[0] is True
        # Old transition still works
        assert validate_transition("decided", "payment_initiated")[0] is True


class TestStateMachineComprehensive:
    """Comprehensive state machine coverage tests."""

    def test_all_valid_transitions(self):
        """Every valid transition should return True."""
        valid = [
            ("proposed", "decision_created"),
            ("decided", "manual_approved"),
            ("decided", "manual_rejected"),
            ("decided", "payment_initiated"),
            ("approved", "payment_initiated"),
            ("processing", "payment_success"),
            ("processing", "payment_failed"),
            ("processing", "payment_cancelled"),
            ("processing", "payment_expired"),
            ("failed", "payment_initiated"),
            ("completed", "refund_completed"),
            ("completed", "partial_refund"),
            ("completed", "chargeback_received"),
            ("completed", "dispute_opened"),
            ("partially_refunded", "refund_completed"),
            ("partially_refunded", "partial_refund"),
            ("disputed", "dispute_resolved"),
        ]
        for current, event in valid:
            is_valid, next_status, error = validate_transition(current, event)
            assert is_valid, f"Expected valid: {current} + {event}, got error: {error}"

    def test_common_invalid_transitions(self):
        """Common invalid transitions should be rejected."""
        invalid = [
            ("proposed", "payment_success"),
            ("proposed", "manual_approved"),
            ("processing", "manual_approved"),
            # completed + payment_success is idempotent, not invalid
            ("refunded", "payment_initiated"),
            ("rejected", "payment_initiated"),
            ("cancelled", "payment_initiated"),
            ("expired", "payment_initiated"),
            ("chargeback", "refund_completed"),
        ]
        for current, event in invalid:
            is_valid, _, _ = validate_transition(current, event)
            assert not is_valid, f"Expected invalid: {current} + {event}"


class TestFeedbackComprehensive:
    """Comprehensive feedback coverage tests."""

    def test_all_decision_types_covered(self):
        """Every decision type produces a valid feedback."""
        for decision in ["allow", "review", "block"]:
            for event in [
                "payment_success",
                "payment_failed",
                "chargeback_received",
                "fraud_confirmed",
                "manual_approved",
                "manual_rejected",
                "fraud_false_positive",
            ]:
                for verification in ["verified", "pending", "unverified"]:
                    fc = classify_feedback(decision, event, verification)
                    assert fc.feedback_type is not None
                    assert 0.0 <= fc.confidence <= 1.0
                    assert len(fc.reasoning) > 0
