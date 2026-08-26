"""Tests for Calibration Engine domain models."""

from app.services.calibration_engine.models import (
    AgentDecisionSummary,
    CalibrationContext,
    CalibrationFinding,
    CalibrationResult,
    DataSufficiency,
    DataSufficiencyLevel,
    DecisionDistribution,
    DecisionRecord,
    DriftDetection,
    FindingSeverity,
    FindingType,
    PolicyDecisionSummary,
    RiskLevelDistribution,
    SignalContribution,
    SignalContributionDistribution,
)


class TestDataSufficiency:
    def test_levels(self):
        assert DataSufficiencyLevel.INSUFFICIENT == "insufficient"
        assert DataSufficiencyLevel.LOW == "low"
        assert DataSufficiencyLevel.MODERATE == "moderate"
        assert DataSufficiencyLevel.HIGH == "high"

    def test_sufficiency_model(self):
        ds = DataSufficiency(
            sample_count=50, level=DataSufficiencyLevel.MODERATE
        )
        assert ds.sample_count == 50
        assert ds.level == DataSufficiencyLevel.MODERATE


class TestDecisionDistribution:
    def test_valid(self):
        dist = DecisionDistribution(
            total=100, allow_count=70, review_count=20,
            block_count=10, allow_rate=0.7, review_rate=0.2,
            block_rate=0.1, sample_count=100,
        )
        assert dist.total == 100
        assert dist.allow_rate == 0.7

    def test_bounds(self):
        import pytest
        with pytest.raises(Exception):
            DecisionDistribution(
                total=10, allow_count=5, review_count=3,
                block_count=2, allow_rate=1.5, review_rate=0.3,
                block_rate=0.2, sample_count=10,
            )

    def test_negative_rejected(self):
        import pytest
        with pytest.raises(Exception):
            DecisionDistribution(
                total=-1, allow_count=0, review_count=0,
                block_count=0, allow_rate=0.0, review_rate=0.0,
                block_rate=0.0, sample_count=0,
            )


class TestRiskLevelDistribution:
    def test_valid(self):
        dist = RiskLevelDistribution(
            total_with_risk=50, low_count=30, medium_count=15,
            high_count=4, critical_count=1, risk_unavailable_count=50,
        )
        assert dist.total_with_risk == 50
        assert dist.risk_unavailable_count == 50


class TestSignalContribution:
    def test_valid(self):
        sig = SignalContribution(
            source="policy", appeared_count=80, positive_count=60,
            negative_count=15, unknown_count=5, violation_count=0,
            contribution_rate=0.8,
        )
        assert sig.source == "policy"
        assert sig.contribution_rate == 0.8

    def test_bounds(self):
        import pytest
        with pytest.raises(Exception):
            SignalContribution(
                source="x", appeared_count=0, positive_count=0,
                negative_count=0, unknown_count=0, violation_count=0,
                contribution_rate=1.5,
            )


class TestPolicyDecisionSummary:
    def test_valid(self):
        s = PolicyDecisionSummary(
            policy_id="p1", policy_name="Test",
            evaluation_count=100, trigger_count=10,
            trigger_rate=0.1, invalid_count=0,
        )
        assert s.trigger_rate == 0.1


class TestAgentDecisionSummary:
    def test_valid(self):
        s = AgentDecisionSummary(
            agent_id="a1", total_decisions=50,
            allow_rate=0.8, review_rate=0.15,
            block_rate=0.05, avg_signal_count=4.5,
        )
        assert s.allow_rate == 0.8


class TestDriftDetection:
    def test_valid(self):
        d = DriftDetection(
            metric_name="block_rate",
            baseline_value=0.05, current_value=0.15,
            change_ratio=3.0, is_drifting=True,
            explanation="Block rate increased",
            baseline_sample_count=100,
            current_sample_count=80,
        )
        assert d.is_drifting is True


class TestCalibrationFinding:
    def test_valid(self):
        f = CalibrationFinding(
            finding_type=FindingType.DRIFT_DETECTED,
            severity=FindingSeverity.WARNING,
            title="Test finding",
            explanation="Test explanation",
            sample_count=50,
            data_sufficiency=DataSufficiencyLevel.MODERATE,
        )
        assert f.finding_type == FindingType.DRIFT_DETECTED
        assert f.severity == FindingSeverity.WARNING


class TestFindingTypes:
    def test_all_types(self):
        assert FindingType.DRIFT_DETECTED == "drift_detected"
        assert FindingType.HIGH_TRIGGER_RATE == "high_trigger_rate"
        assert FindingType.UNSTABLE_AGENT == "unstable_agent"
        assert FindingType.SYSTEM_SUMMARY == "system_summary"
        assert len(FindingType) >= 5


class TestDecisionRecord:
    def test_valid(self):
        r = DecisionRecord(
            decision_id="d1", decision="allow",
            signal_count=5, policy_triggered_count=0,
        )
        assert r.decision == "allow"

    def test_defaults(self):
        r = DecisionRecord(decision_id="d1", decision="block")
        assert r.explanation == {}
        assert r.signal_count == 0


class TestCalibrationContext:
    def test_empty(self):
        ctx = CalibrationContext(user_id="u1")
        assert len(ctx.decisions) == 0
        assert ctx.window_days == 30

    def test_with_data(self):
        ctx = CalibrationContext(
            user_id="u1",
            decisions=[
                DecisionRecord(decision_id="d1", decision="allow"),
            ],
            window_days=60,
        )
        assert len(ctx.decisions) == 1
        assert ctx.window_days == 60


class TestCalibrationResult:
    def test_valid(self):
        r = CalibrationResult(
            decision_distribution=DecisionDistribution(
                total=0, allow_count=0, review_count=0,
                block_count=0, allow_rate=0.0, review_rate=0.0,
                block_rate=0.0, sample_count=0,
            ),
            risk_level_distribution=RiskLevelDistribution(
                total_with_risk=0, low_count=0, medium_count=0,
                high_count=0, critical_count=0, risk_unavailable_count=0,
            ),
            signal_distribution=SignalContributionDistribution(),
            data_sufficiency=DataSufficiency(
                sample_count=0, level=DataSufficiencyLevel.INSUFFICIENT,
            ),
        )
        assert r.total_decisions_analyzed == 0
        assert "NOT_AVAILABLE" in r.merchant_analysis
