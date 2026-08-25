"""Tests for Calibration Engine drift detection."""

from app.services.calibration_engine.drift import (
    detect_drift,
    generate_drift_findings,
)
from app.services.calibration_engine.models import (
    CalibrationContext,
    CalibrationFinding,
    DataSufficiencyLevel,
    FindingType,
)


def _make_ctx(decisions: list[dict]) -> CalibrationContext:
    from app.services.calibration_engine.models import DecisionRecord
    records = [
        DecisionRecord(
            decision_id=f"d{i}", decision=d.get("decision", "allow"),
            signal_count=d.get("signal_count", 0),
            policy_triggered_count=d.get("policy_triggered_count", 0),
        )
        for i, d in enumerate(decisions)
    ]
    return CalibrationContext(user_id="u1", decisions=records)


class TestDriftDetection:
    def test_insufficient_baseline(self):
        baseline = _make_ctx([{"decision": "allow"} for _ in range(5)])
        current = _make_ctx([{"decision": "block"} for _ in range(20)])
        detections = detect_drift(baseline, current)
        assert len(detections) == 0  # Below minimum

    def test_insufficient_current(self):
        baseline = _make_ctx([{"decision": "allow"} for _ in range(20)])
        current = _make_ctx([{"decision": "block"} for _ in range(5)])
        detections = detect_drift(baseline, current)
        assert len(detections) == 0

    def test_stable(self):
        baseline = _make_ctx(
            [{"decision": "allow"} for _ in range(80)]
            + [{"decision": "review"} for _ in range(15)]
            + [{"decision": "block"} for _ in range(5)]
        )
        current = _make_ctx(
            [{"decision": "allow"} for _ in range(78)]
            + [{"decision": "review"} for _ in range(17)]
            + [{"decision": "block"} for _ in range(5)]
        )
        detections = detect_drift(baseline, current)
        drifting = [d for d in detections if d.is_drifting]
        assert len(drifting) == 0

    def test_block_rate_increase(self):
        baseline = _make_ctx(
            [{"decision": "allow"} for _ in range(95)]
            + [{"decision": "block"} for _ in range(5)]
        )
        current = _make_ctx(
            [{"decision": "allow"} for _ in range(80)]
            + [{"decision": "block"} for _ in range(20)]
        )
        detections = detect_drift(baseline, current)
        block_drift = next(
            (d for d in detections if d.metric_name == "block_rate"), None
        )
        assert block_drift is not None
        assert block_drift.is_drifting is True

    def test_review_rate_increase(self):
        baseline = _make_ctx(
            [{"decision": "allow"} for _ in range(90)]
            + [{"decision": "review"} for _ in range(10)]
        )
        current = _make_ctx(
            [{"decision": "allow"} for _ in range(70)]
            + [{"decision": "review"} for _ in range(30)]
        )
        detections = detect_drift(baseline, current)
        review_drift = next(
            (d for d in detections if d.metric_name == "review_rate"), None
        )
        assert review_drift is not None
        assert review_drift.is_drifting is True

    def test_allow_rate_decrease(self):
        baseline = _make_ctx(
            [{"decision": "allow"} for _ in range(95)]
            + [{"decision": "review"} for _ in range(5)]
        )
        current = _make_ctx(
            [{"decision": "allow"} for _ in range(50)]
            + [{"decision": "review"} for _ in range(30)]
            + [{"decision": "block"} for _ in range(20)]
        )
        detections = detect_drift(baseline, current)
        allow_drift = next(
            (d for d in detections if d.metric_name == "allow_rate"), None
        )
        assert allow_drift is not None
        assert allow_drift.is_drifting is True

    def test_zero_baseline_block(self):
        baseline = _make_ctx(
            [{"decision": "allow"} for _ in range(20)]
        )
        current = _make_ctx(
            [{"decision": "allow"} for _ in range(15)]
            + [{"decision": "block"} for _ in range(5)]
        )
        detections = detect_drift(baseline, current)
        block_drift = next(
            (d for d in detections if d.metric_name == "block_rate"), None
        )
        assert block_drift is not None
        assert block_drift.is_drifting is True

    def test_boundary_just_below_minimum(self):
        baseline = _make_ctx(
            [{"decision": "allow"} for _ in range(8)]
            + [{"decision": "block"} for _ in range(1)]
        )
        current = _make_ctx(
            [{"decision": "allow"} for _ in range(8)]
            + [{"decision": "block"} for _ in range(1)]
        )
        detections = detect_drift(baseline, current)
        assert len(detections) == 0  # Below minimum of 10

    def test_policy_trigger_drift(self):
        baseline = _make_ctx(
            [{"decision": "allow", "policy_triggered_count": 1} for _ in range(20)]
        )
        current = _make_ctx(
            [{"decision": "review", "policy_triggered_count": 3} for _ in range(20)]
        )
        detections = detect_drift(baseline, current)
        policy_drift = next(
            (d for d in detections if d.metric_name == "policy_trigger_rate"), None
        )
        assert policy_drift is not None
        assert policy_drift.is_drifting is True


class TestDriftFindings:
    def test_drifting_generates_findings(self):
        from app.services.calibration_engine.models import DriftDetection
        detections = [
            DriftDetection(
                metric_name="block_rate",
                baseline_value=0.05, current_value=0.20,
                change_ratio=4.0, is_drifting=True,
                explanation="Block rate increased",
                baseline_sample_count=100,
                current_sample_count=80,
            ),
        ]
        findings = generate_drift_findings(detections)
        assert len(findings) == 1
        assert findings[0].finding_type == FindingType.DRIFT_DETECTED

    def test_stable_no_findings(self):
        from app.services.calibration_engine.models import DriftDetection
        detections = [
            DriftDetection(
                metric_name="block_rate",
                baseline_value=0.05, current_value=0.06,
                change_ratio=1.2, is_drifting=False,
                explanation="Stable",
                baseline_sample_count=100,
                current_sample_count=80,
            ),
        ]
        findings = generate_drift_findings(detections)
        assert len(findings) == 0
