"""Tests for Calibration Intelligence domain models."""

import pytest

from app.services.calibration_intelligence.models import (
    CalibrationDataset,
    CalibrationIntelligenceResult,
    CalibrationRecommendation,
    CalibrationSample,
    CalibrationVersion,
    DataSufficiencyLevel,
    MetricResult,
    RecommendationStatus,
    RecommendationType,
    RiskOutcomeCrossTab,
    SampleExclusionReason,
)


class TestRecommendationStatus:
    def test_all_statuses(self):
        statuses = list(RecommendationStatus)
        assert len(statuses) == 6
        assert RecommendationStatus.GENERATED in statuses
        assert RecommendationStatus.REVIEWED in statuses
        assert RecommendationStatus.APPROVED in statuses
        assert RecommendationStatus.REJECTED in statuses
        assert RecommendationStatus.ACTIVATED in statuses
        assert RecommendationStatus.SUPERSEDED in statuses

    def test_string_values(self):
        assert RecommendationStatus.GENERATED.value == "generated"
        assert RecommendationStatus.ACTIVATED.value == "activated"


class TestRecommendationType:
    def test_all_types(self):
        types = list(RecommendationType)
        assert len(types) == 8

    def test_values(self):
        assert RecommendationType.WEIGHT_REVIEW.value == "weight_review"
        assert RecommendationType.THRESHOLD_REVIEW.value == "threshold_review"
        assert RecommendationType.POLICY_REVIEW.value == "policy_review"
        assert RecommendationType.REPUTATION_REVIEW.value == "reputation_review"
        assert RecommendationType.BEHAVIORAL_REVIEW.value == "behavioral_review"
        assert RecommendationType.NETWORK_REVIEW.value == "network_review"
        assert RecommendationType.SUMMARY.value == "summary"


class TestDataSufficiencyLevel:
    def test_all_levels(self):
        levels = list(DataSufficiencyLevel)
        assert len(levels) == 4

    def test_values(self):
        assert DataSufficiencyLevel.INSUFFICIENT.value == "insufficient"
        assert DataSufficiencyLevel.LOW.value == "low"
        assert DataSufficiencyLevel.MODERATE.value == "moderate"
        assert DataSufficiencyLevel.HIGH.value == "high"


class TestSampleExclusionReason:
    def test_all_reasons(self):
        reasons = list(SampleExclusionReason)
        assert len(reasons) == 6


class TestCalibrationSample:
    def test_valid_sample(self):
        sample = CalibrationSample(
            transaction_id="txn-1",
            decision_id="dec-1",
            original_decision="allow",
            final_lifecycle_status="completed",
            feedback_type="correct_allow",
            feedback_confidence=0.9,
            verification_state="verified",
        )
        assert sample.sample_eligible is True
        assert sample.exclusion_reason is None

    def test_excluded_sample(self):
        sample = CalibrationSample(
            transaction_id="txn-1",
            decision_id="",
            original_decision="",
            final_lifecycle_status="completed",
            feedback_type="unknown",
            feedback_confidence=0.0,
            verification_state="unknown",
            sample_eligible=False,
            exclusion_reason="unknown_feedback",
        )
        assert sample.sample_eligible is False
        assert sample.exclusion_reason == "unknown_feedback"

    def test_defaults(self):
        sample = CalibrationSample(
            transaction_id="txn-1",
            decision_id="dec-1",
            original_decision="allow",
            final_lifecycle_status="completed",
            feedback_type="correct_allow",
            feedback_confidence=0.9,
            verification_state="verified",
        )
        assert sample.risk_level is None
        assert sample.risk_available is False
        assert sample.signal_count == 0
        assert sample.amount is None


class TestCalibrationDataset:
    def test_empty_dataset(self):
        dataset = CalibrationDataset()
        assert dataset.total_samples == 0
        assert dataset.eligible_samples == 0
        assert dataset.excluded_samples == 0
        assert dataset.samples == []

    def test_dataset_with_samples(self):
        dataset = CalibrationDataset(
            samples=[
                CalibrationSample(
                    transaction_id="txn-1",
                    decision_id="dec-1",
                    original_decision="allow",
                    final_lifecycle_status="completed",
                    feedback_type="correct_allow",
                    feedback_confidence=0.9,
                    verification_state="verified",
                ),
            ],
            total_samples=1,
            eligible_samples=1,
            excluded_samples=0,
        )
        assert dataset.total_samples == 1
        assert dataset.eligible_samples == 1


class TestMetricResult:
    def test_valid_metric(self):
        metric = MetricResult(
            metric_name="decision_accuracy",
            value=0.85,
            sample_count=100,
            data_sufficiency=DataSufficiencyLevel.HIGH,
            confidence=0.95,
        )
        assert metric.value == 0.85

    def test_metric_no_value(self):
        metric = MetricResult(
            metric_name="decision_accuracy",
            value=None,
            sample_count=5,
            data_sufficiency=DataSufficiencyLevel.INSUFFICIENT,
        )
        assert metric.value is None


class TestRiskOutcomeCrossTab:
    def test_valid_crosstab(self):
        ct = RiskOutcomeCrossTab(
            risk_level="high",
            correct_allow=5,
            correct_block=10,
            false_positive=2,
            false_negative=1,
            total=18,
        )
        assert ct.total == 18


class TestCalibrationRecommendation:
    def test_valid_recommendation(self):
        rec = CalibrationRecommendation(
            recommendation_id="rec-1",
            recommendation_type=RecommendationType.WEIGHT_REVIEW,
            engine="risk_engine",
            parameter="INTENT_DRIFT",
            current_value=0.25,
            proposed_range=(0.20, 0.30),
            evidence={"samples": 50},
            sample_count=50,
            data_sufficiency=DataSufficiencyLevel.MODERATE,
            rationale="Test rationale",
            severity="warning",
            calibration_version="calibration-v1",
        )
        assert rec.status == RecommendationStatus.GENERATED

    def test_recommendation_bounds(self):
        with pytest.raises(Exception):
            CalibrationRecommendation(
                recommendation_id="rec-1",
                recommendation_type=RecommendationType.WEIGHT_REVIEW,
                engine="risk_engine",
                sample_count=-1,  # invalid
                rationale="test",
                calibration_version="calibration-v1",
            )


class TestCalibrationVersion:
    def test_valid_version(self):
        version = CalibrationVersion(
            version_id="calibration-v1",
            total_samples=100,
            eligible_samples=85,
            excluded_samples=15,
            recommendation_count=3,
        )
        assert version.status == RecommendationStatus.GENERATED
        assert version.activated_at is None


class TestCalibrationIntelligenceResult:
    def test_empty_result(self):
        result = CalibrationIntelligenceResult(
            dataset=CalibrationDataset(),
        )
        assert result.metrics == []
        assert result.recommendations == []
        assert result.version is None
