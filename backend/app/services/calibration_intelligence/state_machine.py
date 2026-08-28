"""Calibration Intelligence — governance state machine.

Pure, database-independent functions for validating recommendation
and version state transitions.

Deterministic — same inputs always produce the same result.
No SQLAlchemy, no external calls, no mutable global state.
"""

from __future__ import annotations

# ── Recommendation transitions ──────────────────────────────────

_RECOMMENDATION_TRANSITIONS: dict[str, set[str]] = {
    "generated": {"reviewed", "rejected"},
    "reviewed": {"approved", "rejected"},
    "approved": {"activated"},
    "activated": {"superseded"},
}

_RECOMMENDATION_TERMINAL: frozenset[str] = frozenset({
    "rejected",
    "superseded",
})


def validate_recommendation_transition(
    current_status: str,
    requested_status: str,
) -> tuple[bool, str | None]:
    """Validate a recommendation state transition.

    Args:
        current_status: Current recommendation status.
        requested_status: Desired new status.

    Returns:
        (is_valid, error_message) — error_message is None when valid.
    """
    current = current_status.lower().strip()
    requested = requested_status.lower().strip()

    if current == requested:
        # Idempotent — already in the target state
        return True, None

    allowed = _RECOMMENDATION_TRANSITIONS.get(current)
    if allowed is None:
        return False, f"Unknown current status: {current}"

    if requested not in allowed:
        return False, (
            f"Cannot transition recommendation from "
            f"'{current}' to '{requested}'. "
            f"Allowed transitions: {sorted(allowed)}"
        )

    return True, None


def is_terminal_recommendation(status: str) -> bool:
    """Check whether a recommendation status is terminal."""
    return status.lower().strip() in _RECOMMENDATION_TERMINAL


# ── Version transitions ─────────────────────────────────────────

_VERSION_TRANSITIONS: dict[str, set[str]] = {
    "generated": {"active"},
    "active": {"superseded"},
    "superseded": {"active"},  # rollback: re-enable a previously superseded version
}

_VERSION_TERMINAL: frozenset[str] = frozenset()


def validate_version_transition(
    current_status: str,
    requested_status: str,
) -> tuple[bool, str | None]:
    """Validate a version state transition.

    Args:
        current_status: Current version status.
        requested_status: Desired new status.

    Returns:
        (is_valid, error_message) — error_message is None when valid.
    """
    current = current_status.lower().strip()
    requested = requested_status.lower().strip()

    if current == requested:
        # Idempotent — already in the target state
        return True, None

    allowed = _VERSION_TRANSITIONS.get(current)
    if allowed is None:
        return False, f"Unknown current status: {current}"

    if requested not in allowed:
        return False, (
            f"Cannot transition version from "
            f"'{current}' to '{requested}'. "
            f"Allowed transitions: {sorted(allowed)}"
        )

    return True, None


def is_terminal_version(status: str) -> bool:
    """Check whether a version status is terminal."""
    return status.lower().strip() in _VERSION_TERMINAL


def can_activate_version(
    version_status: str,
    recommendation_statuses: list[str],
) -> tuple[bool, str | None]:
    """Determine whether a version can be activated.

    The version lifecycle is GENERATED → ACTIVE → SUPERSEDED.
    A version may activate when:
    - its own status is 'generated' or 'active' (idempotent)
    - all belonging recommendations are in a terminal governance state
      (approved, rejected, activated, or superseded)
    - no recommendations are in 'generated' or 'reviewed' state

    Args:
        version_status: The version's current status.
        recommendation_statuses: Statuses of all recommendations
            belonging to this version.

    Returns:
        (can_activate, error_message) — error_message is None when valid.
    """
    vs = version_status.lower().strip()

    # Idempotent: already active
    if vs == "active":
        return True, None

    # Allow generated and superseded versions to activate
    # (superseded → active is valid for rollback operations)
    if vs not in ("generated", "superseded"):
        return False, (
            f"Version status is '{vs}'. "
            f"Only 'generated' or 'superseded' versions can be activated."
        )

    # Check that all recommendations have reached a terminal state
    # (approved, rejected, activated, or superseded) — none should
    # be pending review
    _pending = {"generated", "reviewed"}
    pending = [
        s for s in recommendation_statuses
        if s.lower().strip() in _pending
    ]
    if pending:
        return False, (
            f"Version has {len(pending)} recommendation(s) still pending: "
            f"{pending}. All recommendations must be approved or rejected "
            f"before activation."
        )

    return True, None
