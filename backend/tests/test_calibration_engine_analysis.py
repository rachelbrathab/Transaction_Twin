"""Tests for Calibration Engine policy and agent analysis."""

from app.services.calibration_engine.agent_analysis import (
    analyze_agents,
    identify_unstable_agents,
)
from app.services.calibration_engine.models import (
    AgentRecord,
    CalibrationContext,
    DecisionRecord,
    PolicyRecord,
)
from app.services.calibration_engine.policy_analysis import (
    analyze_policies,
    get_high_trigger_policies,
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
            signal_count=d.get("signal_count", 0),
            policy_triggered_count=d.get("policy_triggered_count", 0),
            drift_severity=d.get("drift_severity"),
            intent_id=d.get("intent_id"),
        )
        for i, d in enumerate(decisions)
    ]
    agent_records = [
        AgentRecord(
            agent_id=a["agent_id"],
            agent_name=a.get("name"),
            reputation_snapshot=a.get("reputation_snapshot"),
        )
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


class TestPolicyAnalysis:
    def test_empty(self):
        ctx = _make_ctx([])
        summaries = analyze_policies(ctx)
        assert len(summaries) == 0

    def test_triggered_policy(self):
        ctx = _make_ctx(
            [
                {
                    "decision": "review",
                    "explanation": {
                        "policy_statuses": {"p1": "triggered"},
                        "triggered_policy_names": ["p1"],
                        "policy": {"highest_severity": "medium"},
                    },
                },
            ],
            policies=[{"policy_id": "p1", "policy_name": "Max Amount"}],
        )
        summaries = analyze_policies(ctx)
        assert len(summaries) == 1
        assert summaries[0].trigger_count == 1
        assert summaries[0].trigger_rate == 1.0

    def test_multiple_policies(self):
        ctx = _make_ctx(
            [
                {
                    "decision": "allow",
                    "explanation": {
                        "policy_statuses": {"p1": "pass", "p2": "pass"},
                        "triggered_policy_names": [],
                        "policy": {},
                    },
                },
                {
                    "decision": "review",
                    "explanation": {
                        "policy_statuses": {"p1": "triggered", "p2": "pass"},
                        "triggered_policy_names": ["p1"],
                        "policy": {"highest_severity": "high"},
                    },
                },
            ],
            policies=[
                {"policy_id": "p1", "policy_name": "Policy A"},
                {"policy_id": "p2", "policy_name": "Policy B"},
            ],
        )
        summaries = analyze_policies(ctx)
        assert len(summaries) == 2
        p1 = next(s for s in summaries if s.policy_id == "p1")
        assert p1.evaluation_count == 2
        assert p1.trigger_count == 1

    def test_invalid_policy(self):
        ctx = _make_ctx(
            [
                {
                    "decision": "review",
                    "explanation": {
                        "policy_statuses": {"p1": "invalid_policy"},
                        "triggered_policy_names": [],
                        "policy": {},
                    },
                },
            ],
            policies=[{"policy_id": "p1", "policy_name": "Broken"}],
        )
        summaries = analyze_policies(ctx)
        assert summaries[0].invalid_count == 1

    def test_high_trigger_rate_flagged(self):
        ctx = _make_ctx(
            [
                {
                    "decision": "review",
                    "explanation": {
                        "policy_statuses": {"p1": "triggered"},
                        "triggered_policy_names": ["p1"],
                        "policy": {"highest_severity": "medium"},
                    },
                }
                for _ in range(6)
            ]
            + [
                {
                    "decision": "allow",
                    "explanation": {
                        "policy_statuses": {"p1": "pass"},
                        "triggered_policy_names": [],
                        "policy": {},
                    },
                }
                for _ in range(4)
            ],
            policies=[{"policy_id": "p1", "policy_name": "Aggressive"}],
        )
        summaries = analyze_policies(ctx)
        flagged = get_high_trigger_policies(summaries)
        assert len(flagged) == 1
        assert flagged[0].trigger_rate == 0.6

    def test_malformed_explanation(self):
        # DecisionRecord validates explanation is a dict, so test with empty dict
        ctx = _make_ctx(
            [{"decision": "allow", "explanation": {}}]
        )
        summaries = analyze_policies(ctx)
        # Empty explanation has no policy_statuses key, so no policies found
        assert len(summaries) == 0


class TestAgentAnalysis:
    def test_empty(self):
        ctx = _make_ctx([])
        summaries = analyze_agents(ctx)
        assert len(summaries) == 0

    def test_single_agent_with_filter(self):
        ctx = _make_ctx(
            [
                {"decision": "allow", "intent_id": "i1", "signal_count": 3},
                {"decision": "review", "intent_id": "i2", "signal_count": 5},
                {"decision": "allow", "intent_id": "i3", "signal_count": 4},
            ],
            agents=[{"agent_id": "a1", "name": "Agent A"}],
            filter_agent_id="a1",
        )
        summaries = analyze_agents(ctx)
        assert len(summaries) == 1
        assert summaries[0].agent_id == "a1"
        assert summaries[0].total_decisions == 3
        assert abs(summaries[0].allow_rate - (2 / 3)) < 0.001

    def test_multiple_agents_resolved(self):
        # Single agent without filter: resolved via heuristic
        ctx = _make_ctx(
            [{"decision": "allow"}],
            agents=[{"agent_id": "a1"}],
        )
        summaries = analyze_agents(ctx)
        assert len(summaries) == 1
        assert summaries[0].agent_id == "a1"

    def test_unstable_agent(self):
        ctx = _make_ctx(
            [{"decision": "review"} for _ in range(4)]
            + [{"decision": "block"} for _ in range(2)]
            + [{"decision": "allow"} for _ in range(4)],
            agents=[{"agent_id": "a1", "name": "Bad Agent"}],
            filter_agent_id="a1",
        )
        summaries = analyze_agents(ctx)
        unstable = identify_unstable_agents(summaries)
        assert len(unstable) == 1
        assert unstable[0].review_rate == 0.4

    def test_stable_agent_not_flagged(self):
        ctx = _make_ctx(
            [{"decision": "allow"} for _ in range(90)]
            + [{"decision": "review"} for _ in range(10)],
            agents=[{"agent_id": "a1", "name": "Good Agent"}],
            filter_agent_id="a1",
        )
        summaries = analyze_agents(ctx)
        unstable = identify_unstable_agents(summaries)
        assert len(unstable) == 0

    def test_drift_severity_distribution(self):
        ctx = _make_ctx(
            [
                {"decision": "allow", "drift_severity": "none"},
                {"decision": "review", "drift_severity": "high"},
                {"decision": "allow", "drift_severity": "none"},
            ],
            agents=[{"agent_id": "a1", "name": "Agent X"}],
            filter_agent_id="a1",
        )
        summaries = analyze_agents(ctx)
        assert summaries[0].drift_severity_distribution["none"] == 2
        assert summaries[0].drift_severity_distribution["high"] == 1

    def test_reputation_snapshot(self):
        ctx = _make_ctx(
            [{"decision": "allow"}],
            agents=[{
                "agent_id": "a1",
                "name": "Rep Agent",
                "reputation_snapshot": {"overall_score": 0.85},
            }],
            filter_agent_id="a1",
        )
        summaries = analyze_agents(ctx)
        assert summaries[0].reputation_score == 0.85

    def test_data_sufficiency(self):
        ctx = _make_ctx(
            [{"decision": "allow"} for _ in range(5)],
            agents=[{"agent_id": "a1", "name": "Agent Y"}],
            filter_agent_id="a1",
        )
        summaries = analyze_agents(ctx)
        assert summaries[0].data_sufficiency.level.value == "insufficient"
