"""Tests for Calibration Intelligence metrics engine."""

from app.services.calibration_intelligence.metrics import (
    compute_agent_effectiveness,
    compute_all_metrics,
    compute_data_sufficiency,
    compute_decision_accuracy,
    compute_false_negative_rate,
    compute_false_positive_rate,
    compute_policy_effectiveness,
    compute_risk_cross_tab,
)
from app.services.calibration_intelligence.models import (
    CalibrationDataset,
    CalibrationSample,
    DataSufficiencyLevel,
)


def _make_sample(
    decision: str,
    feedback: str,
    risk_level: str | None = None,
    risk_available: bool = False,
    policy_id: str | None = None,
    agent_id: str | None = None,
    verification: str = "verified",
    confidence: float = 0.9,
) -> CalibrationSample:
    """Helper to create a calibration sample."""
    return CalibrationSample(
        transaction_id=f"txn-{decision}-{feedback}",
        decision_id=f"dec-{decision}-{feedback}",
        original_decision=decision,
        final_lifecycle_status="completed",
        feedback_type=feedback,
        feedback_confidence=confidence,
        verification_state=verification,
        risk_level=risk_level,
        risk_available=risk_available,
        policy_id=policy_id,
        agent_id=agent_id,
        sample_eligible=True,
    )


def _make_dataset(samples: list[CalibrationSample]) -> CalibrationDataset:
    """Helper to create a dataset from samples."""
    eligible = [s for s in samples if s.sample_eligible]
    return CalibrationDataset(
        samples=samples,
        total_samples=len(samples),
        eligible_samples=len(eligible),
        excluded_samples=len(samples) - len(eligible),
    )


class TestComputeDataSufficiency:
    def test_insufficient(self):
        assert compute_data_sufficiency(0) == DataSufficiencyLevel.INSUFFICIENT

    def test_low(self):
        assert compute_data_sufficiency(10) == DataSufficiencyLevel.LOW

    def test_moderate(self):
        assert compute_data_sufficiency(30) == DataSufficiencyLevel.MODERATE

    def test_high(self):
        assert compute_data_sufficiency(100) == DataSufficiencyLevel.HIGH

    def test_boundary_9(self):
        assert compute_data_sufficiency(9) == DataSufficiencyLevel.INSUFFICIENT

    def test_boundary_29(self):
        assert compute_data_sufficiency(29) == DataSufficiencyLevel.LOW

    def test_boundary_99(self):
        assert compute_data_sufficiency(99) == DataSufficiencyLevel.MODERATE


class TestDecisionAccuracy:
    def test_empty_dataset(self):
        result = compute_decision_accuracy(CalibrationDataset())
        assert result.value is None
        assert result.sample_count == 0

    def test_all_correct(self):
        samples = [
            _make_sample("allow", "correct_allow"),
            _make_sample("block", "correct_block"),
            _make_sample("review", "correct_review"),
        ]
        result = compute_decision_accuracy(_make_dataset(samples))
        assert result.value == 1.0
        assert result.sample_count == 3

    def test_mixed(self):
        samples = [
            _make_sample("allow", "correct_allow"),
            _make_sample("allow", "correct_allow"),
            _make_sample("allow", "possible_false_negative"),
        ]
        result = compute_decision_accuracy(_make_dataset(samples))
        assert result.value is not None
        assert abs(result.value - 2 / 3) < 0.01

    def test_all_wrong(self):
        samples = [
            _make_sample("allow", "possible_false_negative"),
            _make_sample("block", "possible_false_positive"),
        ]
        result = compute_decision_accuracy(_make_dataset(samples))
        assert result.value == 0.0

    def test_deterministic(self):
        samples = [_make_sample("allow", "correct_allow")]
        r1 = compute_decision_accuracy(_make_dataset(samples))
        r2 = compute_decision_accuracy(_make_dataset(samples))
        assert r1.value == r2.value


class TestFalsePositiveRate:
    def test_insufficient_samples(self):
        samples = [_make_sample("block", "correct_block")]
        result = compute_false_positive_rate(_make_dataset(samples))
        assert result.value is None

    def test_no_false_positives(self):
        samples = [_make_sample("block", "correct_block") for _ in range(25)]
        result = compute_false_positive_rate(_make_dataset(samples))
        assert result.value == 0.0

    def test_all_false_positives(self):
        samples = [_make_sample("block", "possible_false_positive") for _ in range(25)]
        result = compute_false_positive_rate(_make_dataset(samples))
        assert result.value == 1.0

    def test_mixed(self):
        samples = [_make_sample("block", "correct_block") for _ in range(15)] + [
            _make_sample("block", "possible_false_positive") for _ in range(5)
        ]
        result = compute_false_positive_rate(_make_dataset(samples))
        assert result.value is not None
        assert abs(result.value - 0.25) < 0.01


class TestFalseNegativeRate:
    def test_insufficient_samples(self):
        samples = [_make_sample("allow", "correct_allow")]
        result = compute_false_negative_rate(_make_dataset(samples))
        assert result.value is None

    def test_no_false_negatives(self):
        samples = [_make_sample("allow", "correct_allow") for _ in range(25)]
        result = compute_false_negative_rate(_make_dataset(samples))
        assert result.value == 0.0

    def test_all_false_negatives(self):
        samples = [_make_sample("allow", "possible_false_negative") for _ in range(25)]
        result = compute_false_negative_rate(_make_dataset(samples))
        assert result.value == 1.0


class TestRiskCrossTab:
    def test_insufficient_samples(self):
        samples = [
            _make_sample("allow", "correct_allow", risk_level="high", risk_available=True),
        ]
        result = compute_risk_cross_tab(_make_dataset(samples))
        assert result == []

    def test_risk_levels_grouped(self):
        # Need >=50 samples total to meet MIN_SAMPLES_RISK_CALIBRATION
        samples = (
            [
                _make_sample("allow", "correct_allow", risk_level="low", risk_available=True)
                for _ in range(28)
            ]
            + [
                _make_sample(
                    "allow", "possible_false_negative", risk_level="low", risk_available=True
                )
                for _ in range(2)
            ]
            + [
                _make_sample("block", "correct_block", risk_level="high", risk_available=True)
                for _ in range(15)
            ]
            + [
                _make_sample(
                    "block", "possible_false_positive", risk_level="high", risk_available=True
                )
                for _ in range(5)
            ]
        )
        result = compute_risk_cross_tab(_make_dataset(samples))
        assert len(result) >= 2
        low = next(ct for ct in result if ct.risk_level == "low")
        assert low.correct_allow == 28
        assert low.false_negative == 2
        high = next(ct for ct in result if ct.risk_level == "high")
        assert high.correct_block == 15
        assert high.false_positive == 5


class TestPolicyEffectiveness:
    def test_insufficient_samples(self):
        samples = [
            _make_sample("block", "correct_block", policy_id="p1"),
        ]
        result = compute_policy_effectiveness(_make_dataset(samples))
        assert result == []

    def test_effective_policy(self):
        samples = [_make_sample("block", "correct_block", policy_id="p1") for _ in range(15)]
        result = compute_policy_effectiveness(_make_dataset(samples))
        assert len(result) == 1
        assert result[0].effectiveness_score == 1.0

    def test_ineffective_policy(self):
        samples = [_make_sample("block", "correct_block", policy_id="p1") for _ in range(5)] + [
            _make_sample("block", "possible_false_positive", policy_id="p1") for _ in range(8)
        ]
        result = compute_policy_effectiveness(_make_dataset(samples))
        assert len(result) == 1
        assert result[0].effectiveness_score is not None
        assert result[0].effectiveness_score < 0.5


class TestAgentEffectiveness:
    def test_insufficient_samples(self):
        samples = [
            _make_sample("allow", "correct_allow", agent_id="a1"),
        ]
        result = compute_agent_effectiveness(_make_dataset(samples))
        assert result == []

    def test_effective_agent(self):
        samples = [_make_sample("allow", "correct_allow", agent_id="a1") for _ in range(15)]
        result = compute_agent_effectiveness(_make_dataset(samples))
        assert len(result) == 1
        assert result[0].correct_rate == 1.0

    def test_ineffective_agent(self):
        samples = [_make_sample("allow", "correct_allow", agent_id="a1") for _ in range(3)] + [
            _make_sample("allow", "possible_false_negative", agent_id="a1") for _ in range(12)
        ]
        result = compute_agent_effectiveness(_make_dataset(samples))
        assert len(result) == 1
        assert result[0].correct_rate is not None
        assert result[0].correct_rate < 0.5


class TestComputeAllMetrics:
    def test_returns_all_metrics(self):
        samples = [_make_sample("allow", "correct_allow") for _ in range(35)]
        result = compute_all_metrics(_make_dataset(samples))
        assert len(result) == 3
        names = [m.metric_name for m in result]
        assert "decision_accuracy" in names
        assert "false_positive_rate" in names
        assert "false_negative_rate" in names

    def test_empty_dataset(self):
        result = compute_all_metrics(CalibrationDataset())
        assert len(result) == 3
        assert all(m.value is None for m in result)
