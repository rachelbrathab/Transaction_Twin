"""Tests for Calibration Intelligence dataset builder."""

from app.services.calibration_intelligence.dataset import (
    _check_eligibility,
    _classify_feedback_type,
    build_dataset,
)
from app.services.calibration_intelligence.models import SampleExclusionReason


class TestClassifyFeedbackType:
    def test_allow_payment_success(self):
        assert _classify_feedback_type("allow", "payment_success") == "correct_allow"

    def test_allow_chargeback(self):
        assert _classify_feedback_type("allow", "chargeback_received") == "possible_false_negative"

    def test_allow_fraud_confirmed(self):
        assert _classify_feedback_type("allow", "fraud_confirmed") == "possible_false_negative"

    def test_block_cancelled(self):
        assert _classify_feedback_type("block", "payment_cancelled") == "correct_block"

    def test_block_expired(self):
        assert _classify_feedback_type("block", "payment_expired") == "correct_block"

    def test_block_false_positive(self):
        assert _classify_feedback_type("block", "fraud_false_positive") == "possible_false_positive"

    def test_review_approved(self):
        assert _classify_feedback_type("review", "manual_approved") == "correct_review"

    def test_review_rejected(self):
        assert _classify_feedback_type("review", "manual_rejected") == "correct_review"

    def test_unknown_combination(self):
        assert _classify_feedback_type("allow", "payment_failed") == "unknown"

    def test_case_insensitive(self):
        assert _classify_feedback_type("ALLOW", "PAYMENT_SUCCESS") == "correct_allow"


class TestCheckEligibility:
    def test_eligible_correct_allow(self):
        result = _check_eligibility("correct_allow", "verified", 0.9)
        assert result is None

    def test_eligible_correct_block(self):
        result = _check_eligibility("correct_block", "verified", 0.9)
        assert result is None

    def test_eligible_false_positive(self):
        result = _check_eligibility("possible_false_positive", "verified", 0.8)
        assert result is None

    def test_eligible_false_negative(self):
        result = _check_eligibility("possible_false_negative", "verified", 0.8)
        assert result is None

    def test_excluded_unknown_feedback(self):
        result = _check_eligibility("unknown", "verified", 0.9)
        assert result == SampleExclusionReason.UNKNOWN_FEEDBACK

    def test_excluded_unverified(self):
        result = _check_eligibility("correct_allow", "unverified", 0.9)
        assert result == SampleExclusionReason.UNVERIFIED_OUTCOME

    def test_excluded_pending(self):
        result = _check_eligibility("correct_allow", "pending", 0.9)
        assert result == SampleExclusionReason.PENDING_OUTCOME

    def test_excluded_low_confidence(self):
        result = _check_eligibility("correct_allow", "verified", 0.3)
        assert result == SampleExclusionReason.LOW_CONFIDENCE

    def test_eligible_boundary_confidence(self):
        result = _check_eligibility("correct_allow", "verified", 0.5)
        assert result is None

    def test_excluded_below_boundary_confidence(self):
        result = _check_eligibility("correct_allow", "verified", 0.49)
        assert result == SampleExclusionReason.LOW_CONFIDENCE


class TestBuildDataset:
    def test_empty_records(self):
        dataset = build_dataset([], [], [])
        assert dataset.total_samples == 0
        assert dataset.eligible_samples == 0

    def test_eligible_sample(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
                "signal_count": 5,
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            }
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.total_samples == 1
        assert dataset.eligible_samples == 1
        assert dataset.excluded_samples == 0
        assert dataset.samples[0].sample_eligible is True
        assert dataset.samples[0].feedback_type == "correct_allow"

    def test_unknown_excluded(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_failed",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            }
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.eligible_samples == 0
        assert dataset.excluded_samples == 1
        assert dataset.samples[0].exclusion_reason == "unknown_feedback"

    def test_unverified_excluded(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "unverified",
                "created_at": "2026-01-01T01:00:00Z",
            }
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.eligible_samples == 0
        assert dataset.excluded_samples == 1
        assert dataset.samples[0].exclusion_reason == "unverified_outcome"

    def test_missing_decision_excluded(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = []
        outcomes = []

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.eligible_samples == 0
        assert dataset.excluded_samples == 1
        assert dataset.samples[0].exclusion_reason == "missing_decision"

    def test_pending_outcome_excluded(self):
        txns = [
            {
                "id": "txn-1",
                "status": "decided",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = []

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.eligible_samples == 0
        assert dataset.excluded_samples == 1
        assert dataset.samples[0].exclusion_reason == "pending_outcome"

    def test_multiple_outcomes_most_recent(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            },
            {
                "transaction_id": "txn-1",
                "event_type": "chargeback_received",
                "verification_state": "verified",
                "created_at": "2026-01-02T01:00:00Z",
            },
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.eligible_samples == 1
        # Most recent outcome (chargeback) should be used
        assert dataset.samples[0].feedback_type == "possible_false_negative"

    def test_decision_created_events_ignored(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "decision_created",
                "verification_state": "verified",
                "created_at": "2026-01-01T00:00:01Z",
            },
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            },
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.eligible_samples == 1
        assert dataset.samples[0].feedback_type == "correct_allow"

    def test_risk_level_extracted(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {"risk": {"available": True, "level": "high"}},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            }
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.samples[0].risk_level == "high"
        assert dataset.samples[0].risk_available is True

    def test_mixed_eligible_and_excluded(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            },
            {
                "id": "txn-2",
                "status": "decided",
                "amount": 200,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "agent-1",
            },
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "dec-2",
                "transaction_id": "txn-2",
                "decision": "block",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            },
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.total_samples == 2
        assert dataset.eligible_samples == 1
        assert dataset.excluded_samples == 1

    def test_exclusion_summary(self):
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
                "status": "decided",
                "amount": 200,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "a",
            },
            {
                "id": "txn-3",
                "status": "completed",
                "amount": 300,
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
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "dec-2",
                "transaction_id": "txn-2",
                "decision": "block",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "dec-3",
                "transaction_id": "txn-3",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
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
                "transaction_id": "txn-3",
                "event_type": "payment_failed",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            },
        ]

        dataset = build_dataset(txns, decisions, outcomes)
        assert dataset.exclusion_summary.get("pending_outcome", 0) >= 1
        assert dataset.exclusion_summary.get("unknown_feedback", 0) >= 1

    def test_deterministic_output(self):
        txns = [
            {
                "id": "txn-1",
                "status": "completed",
                "amount": 100,
                "currency": "INR",
                "transaction_type": "purchase",
                "agent_id": "a",
            }
        ]
        decisions = [
            {
                "id": "dec-1",
                "transaction_id": "txn-1",
                "decision": "allow",
                "explanation": {},
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        outcomes = [
            {
                "transaction_id": "txn-1",
                "event_type": "payment_success",
                "verification_state": "verified",
                "created_at": "2026-01-01T01:00:00Z",
            }
        ]

        d1 = build_dataset(txns, decisions, outcomes)
        d2 = build_dataset(txns, decisions, outcomes)
        assert d1.total_samples == d2.total_samples
        assert d1.eligible_samples == d2.eligible_samples
        assert d1.samples[0].feedback_type == d2.samples[0].feedback_type
