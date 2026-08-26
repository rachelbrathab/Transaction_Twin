"""Outcome Engine — deterministic transaction lifecycle state machine.

Pure functions only. No I/O, no database, no side effects.

Rules:
  1. Invalid transitions must be rejected.
  2. Terminal states cannot transition except:
     PARTIALLY_REFUNDED → REFUNDED.
  3. Duplicate events are idempotent when the transaction is
     already in the desired state.
  4. Event timestamps must be non-decreasing, allowing a 5-minute
     clock-skew tolerance.
  5. Sequence numbers are strictly monotonic.
"""

from __future__ import annotations

from datetime import datetime

from app.services.outcome_engine.constants import CLOCK_SKEW_TOLERANCE_SECONDS
from app.services.outcome_engine.models import OutcomeEventType, TransactionLifecycle

# ── Allowed transitions ────────────────────────────────────────────

# Maps (current_status, event_type) → next_status
# Only explicitly allowed transitions are defined.
_TRANSITIONS: dict[tuple[str, str], str] = {
    # PROPOSED → DECIDED
    (TransactionLifecycle.PROPOSED, OutcomeEventType.DECISION_CREATED): (
        TransactionLifecycle.DECIDED
    ),
    # DECIDED → APPROVED / REJECTED / PROCESSING
    (TransactionLifecycle.DECIDED, OutcomeEventType.MANUAL_APPROVED): (
        TransactionLifecycle.APPROVED
    ),
    (TransactionLifecycle.DECIDED, OutcomeEventType.MANUAL_REJECTED): (
        TransactionLifecycle.REJECTED
    ),
    (TransactionLifecycle.DECIDED, OutcomeEventType.PAYMENT_INITIATED): (
        TransactionLifecycle.PROCESSING
    ),
    # APPROVED → PROCESSING
    (TransactionLifecycle.APPROVED, OutcomeEventType.PAYMENT_INITIATED): (
        TransactionLifecycle.PROCESSING
    ),
    # PROCESSING → COMPLETED / FAILED / CANCELLED / EXPIRED
    (TransactionLifecycle.PROCESSING, OutcomeEventType.PAYMENT_SUCCESS): (
        TransactionLifecycle.COMPLETED
    ),
    (TransactionLifecycle.PROCESSING, OutcomeEventType.PAYMENT_FAILED): (
        TransactionLifecycle.FAILED
    ),
    (TransactionLifecycle.PROCESSING, OutcomeEventType.PAYMENT_CANCELLED): (
        TransactionLifecycle.CANCELLED
    ),
    (TransactionLifecycle.PROCESSING, OutcomeEventType.PAYMENT_EXPIRED): (
        TransactionLifecycle.EXPIRED
    ),
    # FAILED → PROCESSING (retry)
    (TransactionLifecycle.FAILED, OutcomeEventType.PAYMENT_INITIATED): (
        TransactionLifecycle.PROCESSING
    ),
    # COMPLETED → REFUNDED / PARTIALLY_REFUNDED / CHARGEBACK / DISPUTED
    (TransactionLifecycle.COMPLETED, OutcomeEventType.REFUND_COMPLETED): (
        TransactionLifecycle.REFUNDED
    ),
    (TransactionLifecycle.COMPLETED, OutcomeEventType.PARTIAL_REFUND): (
        TransactionLifecycle.PARTIALLY_REFUNDED
    ),
    (TransactionLifecycle.COMPLETED, OutcomeEventType.CHARGEBACK_RECEIVED): (
        TransactionLifecycle.CHARGEBACK
    ),
    (TransactionLifecycle.COMPLETED, OutcomeEventType.DISPUTE_OPENED): (
        TransactionLifecycle.DISPUTED
    ),
    # PARTIALLY_REFUNDED → REFUNDED
    (TransactionLifecycle.PARTIALLY_REFUNDED, OutcomeEventType.REFUND_COMPLETED): (
        TransactionLifecycle.REFUNDED
    ),
    (TransactionLifecycle.PARTIALLY_REFUNDED, OutcomeEventType.PARTIAL_REFUND): (
        TransactionLifecycle.PARTIALLY_REFUNDED
    ),
    # DISPUTED → RESOLVED
    (TransactionLifecycle.DISPUTED, OutcomeEventType.DISPUTE_RESOLVED): (
        TransactionLifecycle.DISPUTED  # remains disputed but resolved
    ),
}


# ── Terminal states ────────────────────────────────────────────────

_TERMINAL_STATES = frozenset({
    TransactionLifecycle.REJECTED,
    TransactionLifecycle.COMPLETED,
    TransactionLifecycle.CANCELLED,
    TransactionLifecycle.EXPIRED,
    TransactionLifecycle.REFUNDED,
    TransactionLifecycle.CHARGEBACK,
})


# ── Public API ─────────────────────────────────────────────────────


def get_next_status(
    current_status: str,
    event_type: str,
) -> str | None:
    """Return the next transaction status for a given transition.

    Returns None if the transition is invalid.
    """
    return _TRANSITIONS.get((current_status, event_type))


def validate_transition(
    current_status: str,
    event_type: str,
) -> tuple[bool, str | None, str | None]:
    """Validate whether a transition is allowed.

    Returns:
        (is_valid, next_status, error_message)
    """
    next_status = get_next_status(current_status, event_type)
    if next_status is not None:
        return True, next_status, None

    # Check if already in the desired state (idempotent)
    if _is_event_already_applied(current_status, event_type):
        return True, current_status, None

    return (
        False,
        None,
        f"Invalid transition: {current_status} + {event_type}",
    )


def is_terminal(status: str) -> bool:
    """Check whether a status is terminal (no further transitions allowed)."""
    return status in _TERMINAL_STATES


def validate_event_order(
    previous_timestamp: datetime | None,
    current_timestamp: datetime,
    previous_sequence: int,
    current_sequence: int,
) -> tuple[bool, str | None]:
    """Validate event ordering constraints.

    Rules:
      - Timestamps must be non-decreasing (with clock-skew tolerance)
      - Sequence numbers must be strictly monotonic

    Returns:
        (is_valid, error_message)
    """
    # Sequence check
    if current_sequence <= previous_sequence:
        return (
            False,
            f"Sequence number {current_sequence} must be > {previous_sequence}",
        )

    # Timestamp check (with clock-skew tolerance)
    if previous_timestamp is not None:
        skew_limit = previous_timestamp.timestamp() - CLOCK_SKEW_TOLERANCE_SECONDS
        if current_timestamp.timestamp() < skew_limit:
            return (
                False,
                f"Timestamp {current_timestamp.isoformat()} is before "
                f"allowed window (previous: {previous_timestamp.isoformat()}, "
                f"tolerance: {CLOCK_SKEW_TOLERANCE_SECONDS}s)",
            )

    return True, None


def get_terminal_states() -> frozenset[str]:
    """Return the set of terminal transaction states."""
    return _TERMINAL_STATES


# ── Internal helpers ───────────────────────────────────────────────


def _is_event_already_applied(current_status: str, event_type: str) -> bool:
    """Check if an event is idempotent because the status already reflects it."""
    # DECISION_CREATED is idempotent if already DECIDED
    if (
        event_type == OutcomeEventType.DECISION_CREATED
        and current_status == TransactionLifecycle.DECIDED
    ):
        return True

    # PAYMENT_SUCCESS is idempotent if already COMPLETED
    if (
        event_type == OutcomeEventType.PAYMENT_SUCCESS
        and current_status == TransactionLifecycle.COMPLETED
    ):
        return True

    # PAYMENT_FAILED is idempotent if already FAILED
    if (
        event_type == OutcomeEventType.PAYMENT_FAILED
        and current_status == TransactionLifecycle.FAILED
    ):
        return True

    # MANUAL_APPROVED is idempotent if already APPROVED
    if (
        event_type == OutcomeEventType.MANUAL_APPROVED
        and current_status == TransactionLifecycle.APPROVED
    ):
        return True

    # MANUAL_REJECTED is idempotent if already REJECTED
    if (
        event_type == OutcomeEventType.MANUAL_REJECTED
        and current_status == TransactionLifecycle.REJECTED
    ):
        return True

    return False
