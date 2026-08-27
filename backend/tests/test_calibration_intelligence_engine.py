"""Tests for Calibration Intelligence core engine."""

from app.services.calibration_intelligence.engine import (
    CalibrationIntelligenceEngine,
)


class TestCalibrationIntelligenceEngine:
    def test_empty_input(self):
        engine = CalibrationIntelligenceEngine()
        result = engine.evaluate(
            transaction_records=[],
            decision_records=[],
            outcome_records=[],
        )
        assert result.dataset.total_samples == 0
        assert result.metrics == []
        assert result.recommendations == []

    def test_with_eligible_samples(self):
        engine = CalibrationIntelligenceEngine()
        txns = [
            {
                "id": f"txn-{i}",
                "status": "completed",
                "amount": 100 * i,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
            for i in range(35)
        ]
        decisions = [
            {
                "id": f"dec-{i}",
                "transaction_id": f"txn-{i}",
                "decision": "allow",
                "explanation": {},
                "signal_count": 5,
                "created_at": "2026-01-01T00:00:00Z",
                "feedback_confidence": 0.9,
            }
            for i in range(35)
        ]
        outcomes = [
            {
                "transaction_id": f"txn-{i}",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            }
            for i in range(35)
        ]

        result = engine.evaluate(
            transaction_records=txns,
            decision_records=decisions,
            outcome_records=outcomes,
        )
        assert result.dataset.eligible_samples == 35
        assert len(result.metrics) == 3
        assert result.version is not None

    def test_version_increments(self):
        engine = CalibrationIntelligenceEngine()
        r1 = engine.evaluate([], [], [])
        r2 = engine.evaluate([], [], [])
        assert r1.version.version_id != r2.version.version_id

    def test_deterministic_results(self):
        engine = CalibrationIntelligenceEngine()
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "a",
            },
            {
                "id": "txn-2",
                "status": "completed",
                "amount": 200,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "a",
            },
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "signal_count": 3,
                "created_at": "2026-01-01T00:00:00Z",
                "feedback_confidence": 0.9,
            },
            {
                "id": "dec-2",
                "transaction_id": "txn-2",
                "decision": "block",
                "explanation": {},
                "signal_count": 5,
                "created_at": "2026-01-01T00:00:00Z",
                "feedback_confidence": 0.9,
            },
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            },
            {
                "transaction_id": "txn-2",
                "event_type": "payment_cancelled",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            },
        ]

        r1 = engine.evaluate(txns, decisions, outcomes)
        r2 = engine.evaluate(txns, decisions, outcomes)
        assert r1.dataset.eligible_samples == r2.dataset.eligible_samples
        assert len(r1.metrics) == len(r2.metrics)

    def test_policy_names_used(self):
        engine = CalibrationIntelligenceEngine()
        txns = [
            {
                "id": f"txn-{i}",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "a",
            }
            for i in range(12)
        ]
        decisions = [
            {
                "id": f"dec-{i}",
                "transaction_id": f"txn-{i}",
                "decision": "block",
                "explanation": {},
                "signal_count": 3,
                "created_at": "2026-01-01T00:00:00Z",
                "feedback_confidence": 0.9,
            }
            for i in range(12)
        ]
        outcomes = [
            {
                "transaction_id": f"txn-{i}",
                "event_type": "payment_cancelled",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            }
            for i in range(12)
        ]

        result = engine.evaluate(
            txns,
            decisions,
            outcomes,
            policy_names={"policy-id-1": "Velocity Policy"},
        )
        assert result.dataset.eligible_samples == 12

    def test_no_eval_exec(self):
        """Engine must not contain eval or exec."""
        import inspect

        from app.services.calibration_intelligence import engine

        source = inspect.getsource(engine)
        assert "eval(" not in source
        assert "exec(" not in source
        assert "subprocess" not in source
        assert "__import__" not in source

    def test_no_sqlalchemy_in_engine(self):
        """Core engine must not import SQLAlchemy."""
        import inspect

        from app.services.calibration_intelligence import engine

        source = inspect.getsource(engine)
        assert "sqlalchemy" not in source.lower()
        assert "session" not in source.lower()
