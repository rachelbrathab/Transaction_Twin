"""Tests for Calibration Intelligence recommendation generator."""

from app.services.calibration_intelligence.models import (
    AgentEffectiveness,
    DataSufficiencyLevel,
    MetricResult,
    PolicyEffectiveness,
    RecommendationStatus,
    RecommendationType,
    RiskOutcomeCrossTab,
)
from app.services.calibration_intelligence.recommendations import (
    _stable_id,
    generate_recommendations,
)


class TestStableId:
    def test_deterministic(self):
        id1 = _stable_id("test-seed")
        id2 = _stable_id("test-seed")
        assert id1 == id2

    def test_different_seeds(self):
        id1 = _stable_id("seed-1")
        id2 = _stable_id("seed-2")
        assert id1 != id2

    def test_length(self):
        id1 = _stable_id("test")
        assert len(id1) == 16


class TestGenerateRecommendations:
    def test_no_data(self):
        recs, version = generate_recommendations(
            metrics=[],
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        assert recs == []
        assert version.version_id == "calibration-v1"
        assert version.recommendation_count == 0

    def test_fpr_recommendation(self):
        metrics = [
            MetricResult(
                metric_name="false_positive_rate",
                value=0.40,
                sample_count=30,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
            ),
        ]
        recs, version = generate_recommendations(
            metrics=metrics,
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        summary_recs = [r for r in recs if r.recommendation_type == RecommendationType.SUMMARY]
        assert len(summary_recs) >= 1
        assert "false-positive" in summary_recs[0].rationale.lower()

    def test_fnr_recommendation(self):
        metrics = [
            MetricResult(
                metric_name="false_negative_rate",
                value=0.30,
                sample_count=30,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
            ),
        ]
        recs, version = generate_recommendations(
            metrics=metrics,
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        summary_recs = [r for r in recs if r.recommendation_type == RecommendationType.SUMMARY]
        assert len(summary_recs) >= 1
        assert "false-negative" in summary_recs[0].rationale.lower()

    def test_over_risking_recommendation(self):
        cross_tab = [
            RiskOutcomeCrossTab(
                risk_level="high",
                correct_allow=8,
                correct_block=2,
                total=15,
            ),
        ]
        recs, version = generate_recommendations(
            metrics=[],
            risk_cross_tab=cross_tab,
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        threshold_recs = [
            r for r in recs if r.recommendation_type == RecommendationType.THRESHOLD_REVIEW
        ]
        assert len(threshold_recs) >= 1
        assert "over-risking" in threshold_recs[0].rationale.lower()

    def test_under_risking_recommendation(self):
        cross_tab = [
            RiskOutcomeCrossTab(
                risk_level="low",
                correct_allow=10,
                false_negative=5,
                total=20,
            ),
        ]
        recs, version = generate_recommendations(
            metrics=[],
            risk_cross_tab=cross_tab,
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        threshold_recs = [
            r for r in recs if r.recommendation_type == RecommendationType.THRESHOLD_REVIEW
        ]
        assert len(threshold_recs) >= 1
        assert "under-risking" in threshold_recs[0].rationale.lower()

    def test_policy_fp_recommendation(self):
        policy_eff = [
            PolicyEffectiveness(
                policy_id="p1",
                policy_name="Test Policy",
                total_evaluations=25,
                false_positive_count=10,
                correct_block_count=15,
                fp_rate=0.40,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
            ),
        ]
        recs, version = generate_recommendations(
            metrics=[],
            risk_cross_tab=[],
            policy_effectiveness=policy_eff,
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        policy_recs = [r for r in recs if r.recommendation_type == RecommendationType.POLICY_REVIEW]
        assert len(policy_recs) >= 1

    def test_agent_fn_recommendation(self):
        agent_eff = [
            AgentEffectiveness(
                agent_id="a1",
                agent_name="Test Agent",
                total_verified=10,
                correct_count=2,
                false_negative_count=8,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
            ),
        ]
        recs, version = generate_recommendations(
            metrics=[],
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=agent_eff,
            calibration_version="calibration-v1",
        )
        rep_recs = [
            r for r in recs if r.recommendation_type == RecommendationType.REPUTATION_REVIEW
        ]
        assert len(rep_recs) >= 1
        assert "reputation" in rep_recs[0].rationale.lower()

    def test_version_metadata(self):
        recs, version = generate_recommendations(
            metrics=[],
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v2",
            window_days=60,
            total_samples=100,
            eligible_samples=80,
        )
        assert version.version_id == "calibration-v2"
        assert version.source_window_days == 60
        assert version.total_samples == 100
        assert version.eligible_samples == 80
        assert version.excluded_samples == 20

    def test_all_recommendations_have_required_fields(self):
        metrics = [
            MetricResult(
                metric_name="false_positive_rate",
                value=0.40,
                sample_count=30,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
            ),
        ]
        recs, _ = generate_recommendations(
            metrics=metrics,
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        for rec in recs:
            assert rec.recommendation_id
            assert rec.recommendation_type
            assert rec.engine
            assert rec.rationale
            assert rec.calibration_version == "calibration-v1"
            assert rec.status == RecommendationStatus.GENERATED

    def test_deterministic_output(self):
        metrics = [
            MetricResult(
                metric_name="false_positive_rate",
                value=0.40,
                sample_count=30,
                data_sufficiency=DataSufficiencyLevel.MODERATE,
            ),
        ]
        r1, v1 = generate_recommendations(
            metrics=metrics,
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        r2, v2 = generate_recommendations(
            metrics=metrics,
            risk_cross_tab=[],
            policy_effectiveness=[],
            agent_effectiveness=[],
            calibration_version="calibration-v1",
        )
        assert len(r1) == len(r2)
        for rec1, rec2 in zip(r1, r2):
            assert rec1.recommendation_type == rec2.recommendation_type
            assert rec1.rationale == rec2.rationale
