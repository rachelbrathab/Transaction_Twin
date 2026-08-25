"""Tests for Calibration Engine — core engine, security, determinism."""

import os

from app.services.calibration_engine.engine import CalibrationEngine
from app.services.calibration_engine.models import (
    AgentRecord,
    CalibrationContext,
    CalibrationResult,
    DataSufficiencyLevel,
    DecisionRecord,
    PolicyRecord,
)


def _make_ctx(
    decisions: list[dict],
    agents: list[dict] | None = None,
    policies: list[dict] | None = None,
    filter_agent_id: str | None = None,
) -> CalibrationContext:
    records = [
        DecisionRecord(
            decision_id=f"d{i}",
            decision=d.get("decision", "allow"),
            explanation=d.get("explanation", {}),
            signal_count=d.get("signal_count", 3),
            policy_triggered_count=d.get("policy_triggered_count", 0),
            drift_severity=d.get("drift_severity", "none"),
        )
        for i, d in enumerate(decisions)
    ]
    agent_records = [
        AgentRecord(agent_id=a["agent_id"], agent_name=a.get("name"))
        for a in (agents or [])
    ]
    policy_records = [
        PolicyRecord(
            policy_id=p["policy_id"],
            policy_name=p.get("policy_name", p["policy_id"]),
            policy_version=p.get("policy_version", 1),
        )
        for p in (policies or [])
    ]
    return CalibrationContext(
        user_id="u1",
        decisions=records,
        agents=agent_records,
        policies=policy_records,
        filter_agent_id=filter_agent_id,
    )


class TestEngineBasics:
    def test_empty_context(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([])
        result = engine.evaluate(ctx)
        assert isinstance(result, CalibrationResult)
        assert result.total_decisions_analyzed == 0
        assert result.data_sufficiency.level == DataSufficiencyLevel.INSUFFICIENT

    def test_one_decision(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "allow"}])
        result = engine.evaluate(ctx)
        assert result.total_decisions_analyzed == 1
        assert result.decision_distribution.allow_rate == 1.0

    def test_mixed_decisions(self):
        engine = CalibrationEngine()
        decisions = (
            [{"decision": "allow"} for _ in range(70)]
            + [{"decision": "review"} for _ in range(20)]
            + [{"decision": "block"} for _ in range(10)]
        )
        ctx = _make_ctx(decisions)
        result = engine.evaluate(ctx)
        assert result.decision_distribution.allow_rate == 0.7
        assert result.decision_distribution.review_rate == 0.2
        assert result.decision_distribution.block_rate == 0.1

    def test_has_findings(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "allow"} for _ in range(10)])
        result = engine.evaluate(ctx)
        assert len(result.findings) >= 1
        assert result.findings[0].finding_type.value == "system_summary"

    def test_merchant_analysis_unavailable(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "allow"}])
        result = engine.evaluate(ctx)
        assert "NOT_AVAILABLE" in result.merchant_analysis

    def test_has_metadata(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "allow"}])
        result = engine.evaluate(ctx)
        assert result.computed_at != ""
        assert result.window_days == 30


class TestEngineWithPolicyAnalysis:
    def test_policy_triggered(self):
        engine = CalibrationEngine()
        ctx = _make_ctx(
            [
                {
                    "decision": "review",
                    "explanation": {
                        "policy_statuses": {"p1": "triggered"},
                        "triggered_policy_names": ["p1"],
                        "policy": {"highest_severity": "medium"},
                        "signals_by_source": {},
                    },
                },
            ],
            policies=[{"policy_id": "p1", "policy_name": "Max Amount"}],
        )
        result = engine.evaluate(ctx)
        assert len(result.policy_summaries) == 1
        assert result.policy_summaries[0].trigger_count == 1


class TestDeterminism:
    def test_same_input_same_output(self):
        engine = CalibrationEngine()
        ctx = _make_ctx(
            [{"decision": "allow", "signal_count": 3} for _ in range(20)]
        )
        r1 = engine.evaluate(ctx)
        r2 = engine.evaluate(ctx)
        assert r1.decision_distribution.allow_rate == r2.decision_distribution.allow_rate
        assert r1.data_sufficiency.level == r2.data_sufficiency.level
        assert len(r1.findings) == len(r2.findings)

    def test_different_input_different_output(self):
        engine = CalibrationEngine()
        ctx1 = _make_ctx([{"decision": "allow"} for _ in range(10)])
        ctx2 = _make_ctx([{"decision": "block"} for _ in range(10)])
        r1 = engine.evaluate(ctx1)
        r2 = engine.evaluate(ctx2)
        assert r1.decision_distribution.block_rate != r2.decision_distribution.block_rate


class TestSecurity:
    def test_no_eval_exec(self):
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "calibration_engine",
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "eval(" not in content, f"eval() in {filename}"
                assert "exec(" not in content, f"exec() in {filename}"

    def test_no_dynamic_imports(self):
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "calibration_engine",
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "__import__" not in content, f"__import__ in {filename}"
                assert "importlib" not in content, f"importlib in {filename}"

    def test_no_llm_imports(self):
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "calibration_engine",
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "openai" not in content, f"openai in {filename}"
                assert "gemini" not in content, f"gemini in {filename}"

    def test_no_subprocess(self):
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "calibration_engine",
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read()
                assert "subprocess" not in content, f"subprocess in {filename}"

    def test_no_sqlalchemy_in_core(self):
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "calibration_engine",
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "sqlalchemy" not in content, f"sqlalchemy in {filename}"

    def test_no_payment_logic(self):
        engine_dir = os.path.join(
            os.path.dirname(__file__), "..", "app", "services",
            "calibration_engine",
        )
        for filename in os.listdir(engine_dir):
            if filename.endswith(".py"):
                with open(os.path.join(engine_dir, filename)) as f:
                    content = f.read().lower()
                assert "razorpay" not in content, f"razorpay in {filename}"
                assert "payment" not in content, f"payment in {filename}"


class TestEdgeCases:
    def test_all_allow(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "allow"} for _ in range(50)])
        result = engine.evaluate(ctx)
        assert result.decision_distribution.allow_rate == 1.0
        assert result.decision_distribution.block_rate == 0.0

    def test_all_block(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "block"} for _ in range(50)])
        result = engine.evaluate(ctx)
        assert result.decision_distribution.block_rate == 1.0

    def test_all_review(self):
        engine = CalibrationEngine()
        ctx = _make_ctx([{"decision": "review"} for _ in range(50)])
        result = engine.evaluate(ctx)
        assert result.decision_distribution.review_rate == 1.0

    def test_100_decisions(self):
        engine = CalibrationEngine()
        decisions = (
            [{"decision": "allow"} for _ in range(80)]
            + [{"decision": "review"} for _ in range(15)]
            + [{"decision": "block"} for _ in range(5)]
        )
        ctx = _make_ctx(decisions)
        result = engine.evaluate(ctx)
        assert result.total_decisions_analyzed == 100
        assert result.data_sufficiency.level == DataSufficiencyLevel.HIGH
