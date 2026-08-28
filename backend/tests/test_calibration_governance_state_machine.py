"""Tests for Calibration Intelligence governance state machine."""

from app.services.calibration_intelligence.state_machine import (
    can_activate_version,
    is_terminal_recommendation,
    is_terminal_version,
    validate_recommendation_transition,
    validate_version_transition,
)

# ══════════════════════════════════════════════════════════════
# Recommendation transitions
# ══════════════════════════════════════════════════════════════


class TestRecommendationTransitions:
    def test_generated_to_reviewed(self):
        ok, err = validate_recommendation_transition(
            "generated", "reviewed",
        )
        assert ok is True
        assert err is None

    def test_generated_to_rejected(self):
        ok, err = validate_recommendation_transition(
            "generated", "rejected",
        )
        assert ok is True

    def test_reviewed_to_approved(self):
        ok, err = validate_recommendation_transition(
            "reviewed", "approved",
        )
        assert ok is True

    def test_reviewed_to_rejected(self):
        ok, err = validate_recommendation_transition(
            "reviewed", "rejected",
        )
        assert ok is True

    def test_approved_to_activated(self):
        ok, err = validate_recommendation_transition(
            "approved", "activated",
        )
        assert ok is True

    def test_activated_to_superseded(self):
        ok, err = validate_recommendation_transition(
            "activated", "superseded",
        )
        assert ok is True

    def test_generated_to_activated_forbidden(self):
        ok, err = validate_recommendation_transition(
            "generated", "activated",
        )
        assert ok is False
        assert "Cannot transition" in err

    def test_reviewed_to_activated_forbidden(self):
        ok, err = validate_recommendation_transition(
            "reviewed", "activated",
        )
        assert ok is False

    def test_generated_to_superseded_forbidden(self):
        ok, err = validate_recommendation_transition(
            "generated", "superseded",
        )
        assert ok is False

    def test_rejected_to_approved_forbidden(self):
        ok, err = validate_recommendation_transition(
            "rejected", "approved",
        )
        assert ok is False

    def test_rejected_to_activated_forbidden(self):
        ok, err = validate_recommendation_transition(
            "rejected", "activated",
        )
        assert ok is False

    def test_superseded_to_activated_forbidden(self):
        ok, err = validate_recommendation_transition(
            "superseded", "activated",
        )
        assert ok is False

    def test_downgrade_activated_to_approved_forbidden(self):
        ok, err = validate_recommendation_transition(
            "activated", "approved",
        )
        assert ok is False

    def test_downgrade_approved_to_reviewed_forbidden(self):
        ok, err = validate_recommendation_transition(
            "approved", "reviewed",
        )
        assert ok is False

    def test_downgrade_reviewed_to_generated_forbidden(self):
        ok, err = validate_recommendation_transition(
            "reviewed", "generated",
        )
        assert ok is False

    def test_same_state_idempotent_generated(self):
        ok, err = validate_recommendation_transition(
            "generated", "generated",
        )
        assert ok is True

    def test_same_state_idempotent_reviewed(self):
        ok, err = validate_recommendation_transition(
            "reviewed", "reviewed",
        )
        assert ok is True

    def test_same_state_idempotent_approved(self):
        ok, err = validate_recommendation_transition(
            "approved", "approved",
        )
        assert ok is True

    def test_unknown_current_status(self):
        ok, err = validate_recommendation_transition(
            "unknown", "reviewed",
        )
        assert ok is False
        assert "Unknown current status" in err

    def test_case_insensitive(self):
        ok, err = validate_recommendation_transition(
            "Generated", "Reviewed",
        )
        assert ok is True


class TestRecommendationTerminal:
    def test_rejected_is_terminal(self):
        assert is_terminal_recommendation("rejected") is True

    def test_superseded_is_terminal(self):
        assert is_terminal_recommendation("superseded") is True

    def test_generated_not_terminal(self):
        assert is_terminal_recommendation("generated") is False

    def test_reviewed_not_terminal(self):
        assert is_terminal_recommendation("reviewed") is False

    def test_approved_not_terminal(self):
        assert is_terminal_recommendation("approved") is False

    def test_activated_not_terminal(self):
        assert is_terminal_recommendation("activated") is False


# ══════════════════════════════════════════════════════════════
# Version transitions
# ══════════════════════════════════════════════════════════════


class TestVersionTransitions:
    def test_generated_to_active(self):
        ok, err = validate_version_transition("generated", "active")
        assert ok is True
        assert err is None

    def test_active_to_superseded(self):
        ok, err = validate_version_transition("active", "superseded")
        assert ok is True

    def test_generated_to_superseded_forbidden(self):
        ok, err = validate_version_transition(
            "generated", "superseded",
        )
        assert ok is False

    def test_superseded_to_active_allowed_for_rollback(self):
        ok, err = validate_version_transition(
            "superseded", "active",
        )
        assert ok is True

    def test_active_to_generated_forbidden(self):
        ok, err = validate_version_transition(
            "active", "generated",
        )
        assert ok is False

    def test_same_state_idempotent(self):
        ok, err = validate_version_transition("active", "active")
        assert ok is True

    def test_unknown_status(self):
        ok, err = validate_version_transition("bogus", "active")
        assert ok is False
        assert "Unknown" in err


class TestVersionTerminal:
    def test_superseded_not_terminal_for_rollback(self):
        assert is_terminal_version("superseded") is False

    def test_generated_not_terminal(self):
        assert is_terminal_version("generated") is False

    def test_active_not_terminal(self):
        assert is_terminal_version("active") is False


# ══════════════════════════════════════════════════════════════
# can_activate_version
# ══════════════════════════════════════════════════════════════


class TestCanActivateVersion:
    def test_generated_no_recommendations(self):
        ok, err = can_activate_version("generated", [])
        assert ok is True
        assert err is None

    def test_generated_all_approved(self):
        ok, err = can_activate_version(
            "generated", ["approved", "approved"],
        )
        assert ok is True

    def test_generated_all_rejected(self):
        ok, err = can_activate_version(
            "generated", ["rejected", "rejected"],
        )
        assert ok is True

    def test_generated_mixed_approved_rejected(self):
        ok, err = can_activate_version(
            "generated", ["approved", "rejected", "approved"],
        )
        assert ok is True

    def test_generated_has_generated_rejects(self):
        ok, err = can_activate_version(
            "generated", ["approved", "generated"],
        )
        assert ok is False
        assert "pending" in err.lower()

    def test_generated_has_reviewed_rejects(self):
        ok, err = can_activate_version(
            "generated", ["approved", "reviewed"],
        )
        assert ok is False
        assert "pending" in err.lower()

    def test_active_idempotent(self):
        ok, err = can_activate_version("active", [])
        assert ok is True

    def test_active_idempotent_with_recommendations(self):
        ok, err = can_activate_version(
            "active", ["activated", "superseded"],
        )
        assert ok is True

    def test_superseded_can_activate_for_rollback(self):
        """Superseded versions can be reactivated for rollback."""
        ok, err = can_activate_version("superseded", [])
        assert ok is True

    def test_approved_status_cannot_activate(self):
        """'approved' is not a valid version status in the two-state lifecycle."""
        ok, err = can_activate_version("approved", [])
        assert ok is False
        assert "generated" in err.lower()

    def test_rejected_status_cannot_activate(self):
        ok, err = can_activate_version("rejected", ["rejected"])
        assert ok is False
        assert "rejected" in err.lower()
