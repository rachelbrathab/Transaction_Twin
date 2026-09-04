"""Simulate Outcome API endpoint.

POST /api/v1/transactions/{transaction_id}/simulate-outcome — convenience
endpoint that walks the state machine from the current transaction state
to the desired final outcome.

Creates intermediate events as needed. All events are created with
source="payment_provider" and verification_state="verified" so they
are eligible for calibration intelligence analysis.

Does NOT execute payments. Does NOT call LLMs.
Does NOT expose real payment provider integration.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.identity import get_current_user
from app.models.agent import Agent
from app.models.audit_event import AuditEvent
from app.models.decision import Decision
from app.models.intent import Intent
from app.models.transaction import Transaction
from app.models.transaction_event import TransactionEvent
from app.models.user import User
from app.services.outcome_engine.models import OutcomeEventType, VerificationState
from app.services.outcome_engine.state_machine import get_next_status

logger = structlog.get_logger()
router = APIRouter()

# Valid target event types for simulation
_VALID_TARGETS = frozenset({
    "payment_initiated",
    "payment_success",
    "payment_failed",
    "payment_cancelled",
    "payment_expired",
    "manual_approved",
    "manual_rejected",
    "chargeback_received",
    "fraud_confirmed",
    "fraud_false_positive",
})

# The path from "decided" to each target — intermediate events needed
_TRANSITION_PATHS: dict[str, list[str]] = {
    "payment_initiated": ["payment_initiated"],
    "payment_success": ["payment_initiated", "payment_success"],
    "payment_failed": ["payment_initiated", "payment_failed"],
    "payment_cancelled": ["payment_initiated", "payment_cancelled"],
    "payment_expired": ["payment_initiated", "payment_expired"],
    "manual_approved": ["manual_approved"],
    "manual_rejected": ["manual_rejected"],
    "chargeback_received": [
        "payment_initiated",
        "payment_success",
        "chargeback_received",
    ],
    "fraud_confirmed": [
        "payment_initiated",
        "payment_success",
        "fraud_confirmed",
    ],
    "fraud_false_positive": [
        "payment_initiated",
        "payment_success",
        "fraud_false_positive",
    ],
}

# Map event type string to OutcomeEventType enum
_EVENT_TYPE_MAP: dict[str, OutcomeEventType] = {
    "payment_initiated": OutcomeEventType.PAYMENT_INITIATED,
    "payment_success": OutcomeEventType.PAYMENT_SUCCESS,
    "payment_failed": OutcomeEventType.PAYMENT_FAILED,
    "payment_cancelled": OutcomeEventType.PAYMENT_CANCELLED,
    "payment_expired": OutcomeEventType.PAYMENT_EXPIRED,
    "manual_approved": OutcomeEventType.MANUAL_APPROVED,
    "manual_rejected": OutcomeEventType.MANUAL_REJECTED,
    "chargeback_received": OutcomeEventType.CHARGEBACK_RECEIVED,
    "fraud_confirmed": OutcomeEventType.FRAUD_CONFIRMED,
    "fraud_false_positive": OutcomeEventType.FRAUD_FALSE_POSITIVE,
}


class SimulateOutcomeRequest(BaseModel):
    """Request to simulate an outcome event for a decided transaction."""

    event_type: str = Field(
        ...,
        description=(
            "Target outcome event type. "
            "Intermediate events will be created automatically."
        ),
    )


class SimulateEventResult(BaseModel):
    """A single event created during simulation."""

    event_id: str
    event_type: str
    sequence_number: int
    verification_state: str


class SimulateOutcomeResponse(BaseModel):
    """Response from outcome simulation."""

    transaction_id: str
    final_status: str
    events_created: list[SimulateEventResult]
    target_event: str


@router.post(
    "/transactions/{transaction_id}/simulate-outcome",
    response_model=SimulateOutcomeResponse,
)
async def simulate_outcome(
    transaction_id: uuid.UUID,
    request: SimulateOutcomeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SimulateOutcomeResponse:
    """Simulate an outcome event for a decided transaction.

    Walks the transaction lifecycle state machine from the current state
    to the desired final state. Creates all intermediate events with
    source="payment_provider" and verification_state="verified".

    Useful for testing calibration intelligence with realistic outcome data.
    """
    try:
        return await _simulate_outcome_impl(
            transaction_id, request, current_user.id, db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("simulate_outcome_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal outcome simulation error",
        ) from e


async def _simulate_outcome_impl(
    transaction_id: uuid.UUID,
    request: SimulateOutcomeRequest,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> SimulateOutcomeResponse:
    """Implementation of outcome simulation."""
    # 1. Validate event type
    target_event = request.event_type.lower().strip()
    if target_event not in _VALID_TARGETS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid event_type: {request.event_type}. "
                f"Valid types: {sorted(_VALID_TARGETS)}"
            ),
        )

    # 2. Load transaction
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id),
    )
    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # 3. Validate ownership
    if transaction.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Transaction does not belong to the specified user",
        )

    # 4. Validate transaction is in a simulatable state
    if transaction.status not in ("decided", "processing", "approved"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaction is in '{transaction.status}' status. "
                "Only transactions in 'decided', 'processing', or 'approved' "
                "status can have outcomes simulated."
            ),
        )

    # 5. Get the transition path
    full_path = _TRANSITION_PATHS.get(target_event)
    if full_path is None:
        raise HTTPException(
            status_code=422,
            detail=f"No transition path for target event: {target_event}",
        )

    # Determine which events to create based on current status
    current_status = transaction.status
    events_to_create: list[str] = []

    if current_status == "decided":
        # Use the full path
        events_to_create = list(full_path)
    elif current_status == "processing":
        # Skip payment_initiated if present
        events_to_create = [e for e in full_path if e != "payment_initiated"]
    elif current_status == "approved":
        # Skip manual_approved
        events_to_create = [e for e in full_path if e != "manual_approved"]

    if not events_to_create:
        raise HTTPException(
            status_code=409,
            detail="Transaction is already in the target state",
        )

    # 6. Get starting sequence number
    seq_result = await db.execute(
        select(TransactionEvent.sequence_number)
        .where(TransactionEvent.transaction_id == transaction_id)
        .order_by(TransactionEvent.sequence_number.desc())
        .limit(1),
    )
    last_seq_row = seq_result.scalar_one_or_none()
    next_seq = (last_seq_row + 1) if last_seq_row is not None else 1

    # 7. Create all events
    created_events: list[SimulateEventResult] = []
    status = current_status

    for event_name in events_to_create:
        event_type = _EVENT_TYPE_MAP[event_name]
        next_status = get_next_status(status, event_type.value)

        if next_status is None:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid transition from '{status}' to '{event_name}'",
            )

        db_event = TransactionEvent(
            transaction_id=transaction_id,
            agent_id=transaction.agent_id,
            sequence_number=next_seq,
            event_type=event_type.value,
            source="payment_provider",
            verification_state=VerificationState.VERIFIED.value,
            payload={"simulated": True, "event_type": event_type.value},
        )
        db.add(db_event)

        created_events.append(SimulateEventResult(
            event_id=str(db_event.id),
            event_type=event_type.value,
            sequence_number=next_seq,
            verification_state=VerificationState.VERIFIED.value,
        ))

        status = next_status
        next_seq += 1

    # 8. Update transaction status
    transaction.status = status

    # 9. Create audit event
    audit_event = AuditEvent(
        entity_type="transaction",
        entity_id=transaction_id,
        event_type="outcome_simulated",
        actor_type="system",
        actor_id=None,
        metadata_={
            "target_event": target_event,
            "events_created": [e.event_type for e in created_events],
            "final_status": status,
            "user_id": str(user_id),
        },
    )
    db.add(audit_event)

    await db.flush()

    logger.info(
        "outcome_simulated",
        transaction_id=str(transaction_id),
        target_event=target_event,
        events_created=len(created_events),
        final_status=status,
    )

    return SimulateOutcomeResponse(
        transaction_id=str(transaction_id),
        final_status=status,
        events_created=created_events,
        target_event=target_event,
    )


# ── Test Data Setup ──────────────────────────────────────────


class TestTransactionSpec(BaseModel):
    """A single transaction to create in the test scenario."""

    decision: str = Field(
        default="allow",
        description="Decision: allow, block, or review",
    )
    amount: float = Field(
        default=50000.0,
        description="Transaction amount",
    )
    outcome: str = Field(
        default="payment_success",
        description="Outcome event type",
    )


class SetupTestDataRequest(BaseModel):
    """Request to set up a complete calibration test scenario."""

    transactions: list[TestTransactionSpec] = Field(
        default_factory=lambda: [
            TestTransactionSpec(decision="allow", amount=10000, outcome="payment_success"),
            TestTransactionSpec(decision="allow", amount=25000, outcome="payment_success"),
            TestTransactionSpec(decision="allow", amount=50000, outcome="payment_success"),
            TestTransactionSpec(decision="block", amount=100000, outcome="payment_cancelled"),
            TestTransactionSpec(decision="block", amount=200000, outcome="payment_cancelled"),
        ],
        description="Transactions to create (default: 5 mixed scenarios)",
    )


class TestTransactionResult(BaseModel):
    """Result of creating a test transaction."""

    transaction_id: str
    decision: str
    outcome: str
    final_status: str
    amount: float


class SetupTestDataResponse(BaseModel):
    """Response from test data setup."""

    agent_id: str
    intent_id: str
    transactions: list[TestTransactionResult]
    message: str


# Minimal structured intent for test data
_TEST_STRUCTURED_INTENT = {
    "goal": "purchase",
    "transaction_type": "purchase",
    "currency": {
        "code": "INR",
        "source": "explicit",
        "evidence": None,
    },
    "amount": {
        "min": 10000,
        "max": 200000,
        "exact": None,
        "confidence": 0.9,
        "evidence": None,
    },
    "category_constraints": {
        "items": ["general"],
        "attributes": {},
        "confidence": 0.5,
        "evidence": None,
    },
    "merchant_constraints": {
        "trust_required": False,
        "preferred": [],
        "excluded": [],
        "confidence": 0.5,
        "evidence": None,
    },
    "geographic_constraints": {
        "country": "IN",
        "city": None,
        "radius_km": None,
        "confidence": 0.5,
        "evidence": None,
    },
    "temporal_constraints": {
        "deadline": None,
        "duration": None,
        "recurring": False,
        "confidence": 0.5,
        "evidence": None,
    },
    "authorization_scope": {
        "value": None,
        "evidence": None,
    },
    "metadata": {
        "parser_version": "test-setup",
        "model_provider": "deterministic",
        "model_name": "test",
        "extraction_method": "deterministic",
        "parsing_latency_ms": 0,
        "canonical_request": "test scenario",
        "reference_timestamp": "2024-01-01T00:00:00Z",
        "injection_detected": False,
    },
}


@router.post(
    "/calibration/test-data",
    response_model=SetupTestDataResponse,
)
async def setup_test_data(
    request: SetupTestDataRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SetupTestDataResponse:
    """Create a complete calibration test scenario.

    Creates an agent, intent, decided transactions, and verified outcomes
    in a single call. Useful for populating calibration intelligence data.
    """
    if request is None:
        request = SetupTestDataRequest()

    user_id = current_user.id

    # 1. Create agent
    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        user_id=user_id,
        name="Test Calibration Agent",
        status="active",
    )
    db.add(agent)
    await db.flush()

    # 2. Create intent
    intent_id = uuid.uuid4()
    intent = Intent(
        id=intent_id,
        user_id=user_id,
        agent_id=agent_id,
        original_request="Test calibration scenario",
        structured_intent=_TEST_STRUCTURED_INTENT,
        confidence=0.9,
        status="parsed",
        version=1,
    )
    db.add(intent)
    await db.flush()

    # 3. Create transactions with decisions and outcomes
    results: list[TestTransactionResult] = []

    for spec in request.transactions:
        # Create transaction
        txn_id = uuid.uuid4()
        txn = Transaction(
            id=txn_id,
            user_id=user_id,
            agent_id=agent_id,
            intent_id=intent_id,
            idempotency_key=uuid.uuid4(),
            transaction_type="purchase",
            amount=spec.amount,
            currency="INR",
            status="decided",
        )
        db.add(txn)
        await db.flush()

        # Create decision
        decision_record = Decision(
            transaction_id=txn_id,
            decision=spec.decision,
            reason=f"Test {spec.decision} decision",
            explanation={
                "risk": {"level": "low", "available": True},
                "policy": {"triggered_count": 0},
            },
            version=1,
        )
        db.add(decision_record)
        await db.flush()

        # Create initial event
        init_event = TransactionEvent(
            transaction_id=txn_id,
            agent_id=agent_id,
            sequence_number=1,
            event_type="decision_created",
            source="system",
            verification_state="verified",
            payload={"decision": spec.decision},
        )
        db.add(init_event)
        await db.flush()

        # Simulate outcome
        event_type_enum = _EVENT_TYPE_MAP.get(spec.outcome)
        if event_type_enum is None:
            continue

        path = _TRANSITION_PATHS.get(spec.outcome, [])
        current_status = "decided"
        next_seq = 2
        final_status = current_status

        for event_name in path:
            et = _EVENT_TYPE_MAP.get(event_name)
            if et is None:
                continue
            ns = get_next_status(current_status, et.value)
            if ns is None:
                break

            db_event = TransactionEvent(
                transaction_id=txn_id,
                agent_id=agent_id,
                sequence_number=next_seq,
                event_type=et.value,
                source="payment_provider",
                verification_state=VerificationState.VERIFIED.value,
                payload={"simulated": True},
            )
            db.add(db_event)
            current_status = ns
            final_status = ns
            next_seq += 1

        txn.status = final_status
        await db.flush()

        results.append(TestTransactionResult(
            transaction_id=str(txn_id),
            decision=spec.decision,
            outcome=spec.outcome,
            final_status=final_status,
            amount=spec.amount,
        ))

    # 4. Create audit event
    audit = AuditEvent(
        entity_type="calibration_test_data",
        entity_id=agent_id,
        event_type="test_data_created",
        actor_type="user",
        actor_id=user_id,
        metadata_={
            "agent_id": str(agent_id),
            "intent_id": str(intent_id),
            "transaction_count": len(results),
        },
    )
    db.add(audit)
    await db.flush()

    logger.info(
        "test_data_setup_complete",
        user_id=str(user_id),
        agent_id=str(agent_id),
        transaction_count=len(results),
    )

    return SetupTestDataResponse(
        agent_id=str(agent_id),
        intent_id=str(intent_id),
        transactions=results,
        message=f"Created {len(results)} test transactions with verified outcomes",
    )
