"""Risk Engine signal extractors.

Each function takes a RiskContext and returns a RiskEvidence or None.
All extractors are pure functions — no I/O, no database, no side effects.
"""

from __future__ import annotations

from typing import Any

from app.services.risk_engine.models import (
    RiskContext,
    RiskEvidence,
    RiskSignalType,
    SourceEngine,
)

# ── INTENT DRIFT ───────────────────────────────────────────────────


def extract_intent_drift_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract intent drift risk signal from DriftResult fields.

    Maps drift severity to risk contribution.
    Does NOT compute drift — consumes pre-computed drift results.
    """
    if not ctx.drift_available:
        return None

    status = ctx.drift_overall_status
    severity = ctx.drift_severity

    if status is None:
        return None

    # Invalid proposal is handled by Decision Engine hard blocks, not risk
    if status == "invalid_proposal":
        return None

    # Determine contribution from status + severity
    contribution = 0.0
    confidence = 1.0
    what = ""
    why = ""

    if status == "match":
        contribution = 0.0
        what = "Transaction matches authorized intent"
        why = "No drift risk — proposal aligns with user authorization"
    elif status == "partial_match":
        contribution = 0.05
        what = "Transaction partially matches authorized intent"
        why = "Minor deviation detected — low drift risk"
    elif status == "drift_detected":
        if severity is None:
            contribution = 0.10
        else:
            severity_map = {
                "none": 0.0,
                "low": 0.10,
                "medium": 0.25,
                "high": 0.45,
                "critical": 0.65,
            }
            contribution = severity_map.get(severity, 0.0)
        what = (
            f"Drift detected: severity {severity} — "
            f"proposal deviates from authorized intent"
        )
        why = (
            f"Transaction deviates from authorized intent at {severity} severity"
        )
    elif status == "insufficient_data":
        contribution = 0.0
        confidence = 0.5
        what = "Insufficient data to determine intent drift"
        why = "Cannot assess drift risk — missing comparison data"
    else:
        return None

    # Amount deviation adds a small incremental contribution
    # (capped to avoid double-counting with AMOUNT_ANOMALY)
    if (
        ctx.drift_amount_deviation_percent is not None
        and ctx.drift_amount_deviation_percent > 0
    ):
        deviation = float(ctx.drift_amount_deviation_percent)
        amount_increment = min(deviation / 200.0, 0.15)
        contribution = min(contribution + amount_increment, 0.75)

    evidence_data: dict[str, Any] = {
        "drift_overall_status": status,
        "drift_severity": severity,
    }
    if ctx.drift_amount_deviation_percent is not None:
        evidence_data["amount_deviation_percent"] = float(
            ctx.drift_amount_deviation_percent
        )

    return RiskEvidence(
        signal_type=RiskSignalType.INTENT_DRIFT,
        risk_contribution=round(contribution, 4),
        confidence=confidence,
        what=what,
        why=why,
        evidence=evidence_data,
        risk_level=_contribution_to_level(contribution),
        source_engine=SourceEngine.TRANSACTION_TWIN,
        source_fields=["drift_overall_status", "drift_severity"],
    )


# ── AMOUNT ANOMALY ────────────────────────────────────────────────


def extract_amount_anomaly_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract amount anomaly risk signal.

    Compares proposal amount against intent bounds.
    Missing proposal amount → 0.0 risk, reduced confidence.
    """
    if ctx.proposal_amount is None:
        return RiskEvidence(
            signal_type=RiskSignalType.AMOUNT_ANOMALY,
            risk_contribution=0.0,
            confidence=0.7,
            what="Proposal amount is not specified",
            why="Cannot assess amount anomaly — amount is unknown",
            evidence={},
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["proposal_amount"],
        )

    proposal = float(ctx.proposal_amount)

    # No intent bounds → cannot assess anomaly
    if ctx.intent_amount_max is None and ctx.intent_amount_min is None:
        return RiskEvidence(
            signal_type=RiskSignalType.AMOUNT_ANOMALY,
            risk_contribution=0.0,
            confidence=0.7,
            what=f"Proposal amount is ₹{proposal:.2f} but no intent bounds available",
            why="Cannot assess amount anomaly — authorization bounds unknown",
            evidence={"proposal_amount": proposal},
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["proposal_amount", "intent_amount_max", "intent_amount_min"],
        )

    contribution = 0.0
    what = ""
    why = ""

    # Check against max
    if ctx.intent_amount_max is not None:
        max_amount = float(ctx.intent_amount_max)
        if proposal > max_amount:
            deviation = proposal - max_amount
            deviation_pct = (deviation / max_amount * 100) if max_amount > 0 else 0
            # Contribution scales with deviation: 0% → 0.0, 100%+ → 0.40
            contribution = min(deviation_pct / 250.0, 0.40)
            what = (
                f"Proposal amount ₹{proposal:.2f} exceeds authorized "
                f"maximum ₹{max_amount:.2f} by ₹{deviation:.2f} ({deviation_pct:.0f}%)"
            )
            why = "Amount exceeds the boundary the user authorized"
        elif proposal == max_amount:
            what = f"Proposal amount ₹{proposal:.2f} equals authorized maximum"
            why = "Amount is at the authorized boundary"
        else:
            what = f"Proposal amount ₹{proposal:.2f} is within authorized maximum ₹{max_amount:.2f}"
            why = "Amount is within authorized bounds"

    # Check against min
    if ctx.intent_amount_min is not None:
        min_amount = float(ctx.intent_amount_min)
        if proposal < min_amount:
            deviation = min_amount - proposal
            contribution = max(contribution, min(deviation / (min_amount + 1), 0.30))
            what = (
                f"Proposal amount ₹{proposal:.2f} is below authorized "
                f"minimum ₹{min_amount:.2f}"
            )
            why = "Amount is below the authorized minimum"

    evidence_data: dict[str, Any] = {
        "proposal_amount": proposal,
    }
    if ctx.intent_amount_max is not None:
        evidence_data["intent_amount_max"] = float(ctx.intent_amount_max)
    if ctx.intent_amount_min is not None:
        evidence_data["intent_amount_min"] = float(ctx.intent_amount_min)

    return RiskEvidence(
        signal_type=RiskSignalType.AMOUNT_ANOMALY,
        risk_contribution=round(contribution, 4),
        confidence=1.0,
        what=what,
        why=why,
        evidence=evidence_data,
        risk_level=_contribution_to_level(contribution),
        source_engine=SourceEngine.RISK_ENGINE,
        source_fields=["proposal_amount", "intent_amount_max", "intent_amount_min"],
    )# ── AGENT BEHAVIOR (Sprint 8) ───────────────────────────────────
def extract_agent_behavior_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract agent behavioral reputation risk signal.

    Consumes Reputation Engine output (agent_reputation_score).
    When available, this REPLACES the legacy AGENT_TRUST signal.
    Only ONE of (AGENT_TRUST, AGENT_BEHAVIOR) is ever emitted per evaluation.
    """
    if not ctx.agent_reputation_available:
        return None  # Legacy path: AGENT_TRUST will handle it

    score = ctx.agent_reputation_score
    level = ctx.agent_reputation_level

    if score is None:
        return RiskEvidence(
            signal_type=RiskSignalType.AGENT_BEHAVIOR,
            risk_contribution=0.0,
            confidence=0.5,
            what="Agent reputation score is not available",
            why="Cannot assess agent behavioral reputation",
            evidence={"agent_id": ctx.agent_id},
            source_engine=SourceEngine.REPUTATION_ENGINE,
            source_fields=["agent_reputation_score"],
        )

    if score >= 0.70:
        contribution = 0.0
        what = f"Agent reputation is {score:.2f} ({level}) -- well-established trust"
        why = "No risk contribution from agent behavioral reputation"
    elif score >= 0.40:
        contribution = 0.05
        what = f"Agent reputation is {score:.2f} ({level}) -- moderate trust"
        why = "Agent has moderate behavioral reputation"
    elif score >= 0.20:
        contribution = 0.15
        what = f"Agent reputation is {score:.2f} ({level}) -- below threshold"
        why = "Agent behavioral reputation indicates elevated risk"
    else:
        contribution = 0.30
        what = f"Agent reputation is {score:.2f} ({level}) -- low trust"
        why = "Agent has low behavioral reputation"

    return RiskEvidence(
        signal_type=RiskSignalType.AGENT_BEHAVIOR,
        risk_contribution=round(contribution, 4),
        confidence=1.0,
        what=what,
        why=why,
        evidence={
            "reputation_score": score,
            "reputation_level": level,
            "agent_id": ctx.agent_id,
        },
        risk_level=_contribution_to_level(contribution),
        source_engine=SourceEngine.REPUTATION_ENGINE,
        source_fields=["agent_reputation_score", "agent_reputation_level"],
    )


# ── AGENT TRUST ────────────────────────────────────────────────────

def extract_agent_trust_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract agent trust risk signal.

    Known low trust → NEGATIVE evidence (contribution > 0).
    Unknown trust → UNKNOWN (contribution 0, reduced confidence).

    Sprint 8: When behavioral reputation is available, this returns None.
    AGENT_BEHAVIOR replaces AGENT_TRUST — only ONE trust signal per evaluation.
    """
    # Sprint 8: Skip when behavioral reputation is available
    if ctx.agent_reputation_available:
        return None  # AGENT_BEHAVIOR handles it

    score = ctx.agent_trust_score

    if score is None:
        return RiskEvidence(
            signal_type=RiskSignalType.AGENT_TRUST,
            risk_contribution=0.0,
            confidence=0.8,
            what="Agent trust score is not available",
            why="Cannot assess agent trust — score unknown",
            evidence={"agent_id": ctx.agent_id},
            source_engine=SourceEngine.DATABASE,
            source_fields=["agent_trust_score"],
        )

    if score >= 0.8:
        contribution = 0.0
        what = f"Agent trust score is {score:.2f} — well-established trust"
        why = "No risk contribution from agent trust"
    elif score >= 0.6:
        contribution = 0.05
        what = f"Agent trust score is {score:.2f} — acceptable trust"
        why = "Agent has moderate trust level"
    elif score >= 0.4:
        contribution = 0.15
        what = f"Agent trust score is {score:.2f} — moderate concern"
        why = "Agent trust is below typical threshold"
    elif score >= 0.2:
        contribution = 0.30
        what = f"Agent trust score is {score:.2f} — elevated risk"
        why = "Agent has low trust level"
    else:
        contribution = 0.45
        what = f"Agent trust score is {score:.2f} — high risk"
        why = "Agent has very low trust level"

    return RiskEvidence(
        signal_type=RiskSignalType.AGENT_TRUST,
        risk_contribution=round(contribution, 4),
        confidence=1.0,
        what=what,
        why=why,
        evidence={
            "trust_score": score,
            "agent_id": ctx.agent_id,
        },
        risk_level=_contribution_to_level(contribution),
        source_engine=SourceEngine.DATABASE,
        source_fields=["agent_trust_score"],
    )


# ── MERCHANT TRUST ─────────────────────────────────────────────────


def extract_merchant_trust_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract merchant trust risk signal.

    Explicitly untrusted → NEGATIVE evidence.
    Unknown → UNKNOWN (0.10 unknown penalty, reduced confidence).
    """
    trusted = ctx.proposal_merchant_trusted
    merchant_name = ctx.proposal_merchant_name or "unknown"

    # Both merchant_trust_score and proposal_merchant_trusted are available
    # Use proposal_merchant_trusted as primary (boolean), merchant_trust_score as detail
    if trusted is None and ctx.merchant_trust_score is None:
        return RiskEvidence(
            signal_type=RiskSignalType.MERCHANT_TRUST,
            risk_contribution=0.10,
            confidence=0.8,
            what=f"Merchant '{merchant_name}' trust status is unknown",
            why="Merchant is not in the trust registry — cannot verify",
            evidence={"merchant_name": merchant_name},
            risk_level=_contribution_to_level(0.10),
            source_engine=SourceEngine.DATABASE,
            source_fields=["proposal_merchant_trusted", "merchant_trust_score"],
        )

    if trusted is False:
        contribution = 0.25
        what = f"Merchant '{merchant_name}' is explicitly untrusted"
        why = "Merchant trust verification failed"
        evidence_data: dict[str, Any] = {
            "merchant_name": merchant_name,
            "trusted": False,
        }
        if ctx.merchant_trust_score is not None:
            evidence_data["trust_score"] = ctx.merchant_trust_score
        return RiskEvidence(
            signal_type=RiskSignalType.MERCHANT_TRUST,
            risk_contribution=contribution,
            confidence=1.0,
            what=what,
            why=why,
            evidence=evidence_data,
            risk_level=_contribution_to_level(contribution),
            source_engine=SourceEngine.DATABASE,
            source_fields=["proposal_merchant_trusted"],
        )

    if trusted is True:
        contribution = 0.0
        what = f"Merchant '{merchant_name}' is verified and trusted"
        why = "No risk contribution from merchant trust"
        return RiskEvidence(
            signal_type=RiskSignalType.MERCHANT_TRUST,
            risk_contribution=0.0,
            confidence=1.0,
            what=what,
            why=why,
            evidence={
                "merchant_name": merchant_name,
                "trusted": True,
                **(
                    {"trust_score": ctx.merchant_trust_score}
                    if ctx.merchant_trust_score is not None
                    else {}
                ),
            },
            source_engine=SourceEngine.DATABASE,
            source_fields=["proposal_merchant_trusted"],
        )

    # trusted is None but merchant_trust_score is available
    if ctx.merchant_trust_score is not None:
        score = ctx.merchant_trust_score
        if score >= 0.8:
            contribution = 0.0
            what = f"Merchant '{merchant_name}' has trust score {score:.2f}"
            why = "No risk contribution from merchant trust"
        elif score >= 0.5:
            contribution = 0.05
            what = f"Merchant '{merchant_name}' has trust score {score:.2f}"
            why = "Merchant has moderate trust"
        elif score >= 0.3:
            contribution = 0.15
            what = f"Merchant '{merchant_name}' has trust score {score:.2f} — low trust"
            why = "Merchant trust is below typical threshold"
        else:
            contribution = 0.30
            what = f"Merchant '{merchant_name}' has trust score {score:.2f} — very low trust"
            why = "Merchant has very low trust level"

        return RiskEvidence(
            signal_type=RiskSignalType.MERCHANT_TRUST,
            risk_contribution=contribution,
            confidence=1.0,
            what=what,
            why=why,
            evidence={
                "merchant_name": merchant_name,
                "trust_score": score,
            },
            risk_level=_contribution_to_level(contribution),
            source_engine=SourceEngine.DATABASE,
            source_fields=["merchant_trust_score"],
        )

    return None


# ── POLICY INTERACTION ─────────────────────────────────────────────


def extract_policy_interaction_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract policy interaction risk signal.

    Consumes PolicyEngine output. Does not re-evaluate policies.
    """
    if not ctx.policy_available:
        return None

    triggered = ctx.policy_triggered_count
    unknown = ctx.policy_unknown_count
    invalid = ctx.policy_invalid_count
    highest_sev = ctx.policy_highest_severity

    if triggered == 0 and unknown == 0 and invalid == 0:
        return RiskEvidence(
            signal_type=RiskSignalType.POLICY_INTERACTION,
            risk_contribution=0.0,
            confidence=1.0,
            what="All policies passed",
            why="No policy violations detected",
            evidence={
                "triggered_count": 0,
                "unknown_count": 0,
                "invalid_count": 0,
            },
            source_engine=SourceEngine.POLICY_ENGINE,
            source_fields=[
                "policy_triggered_count",
                "policy_unknown_count",
                "policy_invalid_count",
            ],
        )

    contribution = 0.0
    confidence = 1.0

    # CRITICAL policy trigger
    if highest_sev == "critical":
        contribution = 0.50
    elif triggered >= 3:
        contribution = 0.30
    elif triggered >= 1:
        # Scale by highest severity
        sev_scale = {
            "low": 0.08,
            "medium": 0.12,
            "high": 0.20,
        }
        contribution = sev_scale.get(highest_sev or "medium", 0.12)

    # Unknown/invalid policies reduce confidence
    if unknown > 0:
        confidence -= 0.05 * unknown
    if invalid > 0:
        confidence -= 0.05 * invalid
    confidence = max(0.1, confidence)

    what = f"{triggered} policy triggered"
    if unknown > 0:
        what += f", {unknown} unknown"
    if invalid > 0:
        what += f", {invalid} invalid"

    why_parts: list[str] = []
    if triggered > 0:
        why_parts.append(f"{triggered} policy violation(s) detected")
    if unknown > 0:
        why_parts.append(f"{unknown} policy evaluation(s) unknown")
    if invalid > 0:
        why_parts.append(f"{invalid} policy structure(s) invalid")

    return RiskEvidence(
        signal_type=RiskSignalType.POLICY_INTERACTION,
        risk_contribution=round(contribution, 4),
        confidence=round(max(0.1, confidence), 4),
        what=what,
        why="; ".join(why_parts),
        evidence={
            "triggered_count": triggered,
            "unknown_count": unknown,
            "invalid_count": invalid,
            "highest_severity": highest_sev,
        },
        risk_level=_contribution_to_level(contribution),
        source_engine=SourceEngine.POLICY_ENGINE,
        source_fields=[
            "policy_triggered_count",
            "policy_highest_severity",
        ],
    )


# ── VELOCITY ───────────────────────────────────────────────────────


def extract_velocity_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract velocity risk signal from pre-computed VelocityContext.

    Unknown velocity → 0.0 risk, reduced confidence.
    """
    vel = ctx.velocity

    if vel is None or not vel.history_available:
        return RiskEvidence(
            signal_type=RiskSignalType.VELOCITY,
            risk_contribution=0.0,
            confidence=0.85,
            what="No transaction history available for velocity analysis",
            why="Cannot assess velocity risk — no historical data",
            evidence={"history_available": False},
            source_engine=SourceEngine.VELOCITY_AGGREGATOR,
            source_fields=["velocity.history_available"],
        )

    contribution = 0.0
    reasons: list[str] = []

    # High frequency
    if vel.transactions_last_hour > 5:
        contribution += 0.20
        reasons.append(f"{vel.transactions_last_hour} transactions in the last hour (high)")
    elif vel.transactions_last_hour > 2:
        contribution += 0.10
        reasons.append(f"{vel.transactions_last_hour} transactions in the last hour (moderate)")

    # Repeat merchant
    if vel.same_merchant_count_last_hour > 3:
        contribution += 0.15
        reasons.append(
            f"{vel.same_merchant_count_last_hour} transactions to same merchant in last hour"
        )

    # Amount velocity spike
    if (
        vel.total_amount_last_hour is not None
        and ctx.intent_amount_max is not None
        and ctx.intent_amount_max > 0
    ):
        ratio = float(vel.total_amount_last_hour) / float(ctx.intent_amount_max)
        if ratio > 3.0:
            contribution += 0.25
            reasons.append(
                f"Amount velocity spike: ₹{vel.total_amount_last_hour} in last hour "
                f"exceeds {ratio:.1f}x authorized max"
            )

    # Merchant diversity
    if vel.unique_merchants_last_day > 10:
        contribution += 0.10
        reasons.append(
            f"{vel.unique_merchants_last_day} unique merchants in last day (unusual diversity)"
        )

    contribution = min(contribution, 0.50)

    evidence_data: dict[str, Any] = {
        "transactions_last_hour": vel.transactions_last_hour,
        "transactions_last_day": vel.transactions_last_day,
        "same_merchant_count_last_hour": vel.same_merchant_count_last_hour,
        "unique_merchants_last_day": vel.unique_merchants_last_day,
    }
    if vel.total_amount_last_hour is not None:
        evidence_data["total_amount_last_hour"] = float(vel.total_amount_last_hour)

    what = (
        f"Velocity: {vel.transactions_last_hour} txns/hour, "
        f"{vel.transactions_last_day}/day"
    )
    why = "; ".join(reasons) if reasons else "Velocity within normal parameters"

    return RiskEvidence(
        signal_type=RiskSignalType.VELOCITY,
        risk_contribution=round(contribution, 4),
        confidence=1.0,
        what=what,
        why=why,
        evidence=evidence_data,
        risk_level=_contribution_to_level(contribution),
        source_engine=SourceEngine.VELOCITY_AGGREGATOR,
        source_fields=[
            "transactions_last_hour",
            "transactions_last_day",
            "same_merchant_count_last_hour",
        ],
    )


# ── DATA QUALITY ───────────────────────────────────────────────────


def extract_data_quality_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract data quality signal.

    DATA_QUALITY never contributes to risk score.
    It only reduces confidence via the confidence computation.
    Returns evidence listing missing fields for explainability.
    """
    missing: list[str] = []

    if ctx.drift_available is False:
        missing.append("drift_result")
    if ctx.agent_trust_score is None:
        missing.append("agent_trust_score")
    if ctx.merchant_trust_score is None and ctx.proposal_merchant_trusted is None:
        missing.append("merchant_trust")
    if ctx.velocity is None or not ctx.velocity.history_available:
        missing.append("velocity_history")
    if ctx.intent_confidence is None:
        missing.append("intent_confidence")
    if ctx.policy_available is False:
        missing.append("policy_result")
    if ctx.proposal_amount is None:
        missing.append("proposal_amount")

    if not missing:
        return None

    return RiskEvidence(
        signal_type=RiskSignalType.DATA_QUALITY,
        risk_contribution=0.0,  # Never contributes to risk score
        confidence=1.0,
        what=f"{len(missing)} data source(s) missing",
        why="Missing data reduces assessment confidence",
        evidence={"missing_fields": missing},
        risk_level=None,
        source_engine=SourceEngine.RISK_ENGINE,
        source_fields=missing,
    )


# ── CURRENCY MISMATCH ──────────────────────────────────────────────


def extract_currency_mismatch_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract currency mismatch risk signal."""
    intent_cur = ctx.intent_currency
    proposal_cur = ctx.proposal_currency

    if intent_cur is None and proposal_cur is None:
        return RiskEvidence(
            signal_type=RiskSignalType.CURRENCY_MISMATCH,
            risk_contribution=0.0,
            confidence=0.8,
            what="Both intent and proposal currencies are unknown",
            why="Cannot assess currency mismatch — currencies unknown",
            evidence={},
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["intent_currency", "proposal_currency"],
        )

    if intent_cur is None or proposal_cur is None:
        return RiskEvidence(
            signal_type=RiskSignalType.CURRENCY_MISMATCH,
            risk_contribution=0.0,
            confidence=0.85,
            what=f"Currency partially known: intent={intent_cur}, proposal={proposal_cur}",
            why="Cannot fully assess currency mismatch — one currency unknown",
            evidence={
                "intent_currency": intent_cur,
                "proposal_currency": proposal_cur,
            },
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["intent_currency", "proposal_currency"],
        )

    if intent_cur.upper() == proposal_cur.upper():
        return RiskEvidence(
            signal_type=RiskSignalType.CURRENCY_MISMATCH,
            risk_contribution=0.0,
            confidence=1.0,
            what=f"Currencies match: {intent_cur.upper()}",
            why="No currency mismatch risk",
            evidence={
                "intent_currency": intent_cur,
                "proposal_currency": proposal_cur,
            },
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["intent_currency", "proposal_currency"],
        )

    # Mismatch
    return RiskEvidence(
        signal_type=RiskSignalType.CURRENCY_MISMATCH,
        risk_contribution=0.15,
        confidence=1.0,
        what=f"Currency mismatch: intent={intent_cur.upper()}, proposal={proposal_cur.upper()}",
        why="Proposed currency differs from authorized currency",
        evidence={
            "intent_currency": intent_cur,
            "proposal_currency": proposal_cur,
        },
        risk_level=_contribution_to_level(0.15),
        source_engine=SourceEngine.RISK_ENGINE,
        source_fields=["intent_currency", "proposal_currency"],
    )


# ── GEOGRAPHIC ANOMALY ────────────────────────────────────────────


def extract_geographic_anomaly_signal(ctx: RiskContext) -> RiskEvidence | None:
    """Extract geographic anomaly risk signal."""
    intent_country = ctx.intent_country
    proposal_country = ctx.proposal_country

    if intent_country is None and proposal_country is None:
        return RiskEvidence(
            signal_type=RiskSignalType.GEOGRAPHIC_ANOMALY,
            risk_contribution=0.0,
            confidence=0.85,
            what="Both intent and proposal countries are unknown",
            why="Cannot assess geographic anomaly — locations unknown",
            evidence={},
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["intent_country", "proposal_country"],
        )

    if intent_country is None or proposal_country is None:
        return RiskEvidence(
            signal_type=RiskSignalType.GEOGRAPHIC_ANOMALY,
            risk_contribution=0.0,
            confidence=0.9,
            what=f"Geography partially known: intent={intent_country}, proposal={proposal_country}",
            why="Cannot fully assess geographic anomaly — one location unknown",
            evidence={
                "intent_country": intent_country,
                "proposal_country": proposal_country,
            },
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["intent_country", "proposal_country"],
        )

    if intent_country.upper() == proposal_country.upper():
        return RiskEvidence(
            signal_type=RiskSignalType.GEOGRAPHIC_ANOMALY,
            risk_contribution=0.0,
            confidence=1.0,
            what=f"Countries match: {intent_country.upper()}",
            why="No geographic anomaly",
            evidence={
                "intent_country": intent_country,
                "proposal_country": proposal_country,
            },
            source_engine=SourceEngine.RISK_ENGINE,
            source_fields=["intent_country", "proposal_country"],
        )

    return RiskEvidence(
        signal_type=RiskSignalType.GEOGRAPHIC_ANOMALY,
        risk_contribution=0.10,
        confidence=1.0,
        what=(
            f"Geographic mismatch: intent={intent_country.upper()}, "
            f"proposal={proposal_country.upper()}"
        ),
        why="Proposed location differs from authorized geography",
        evidence={
            "intent_country": intent_country,
            "proposal_country": proposal_country,
        },
        risk_level=_contribution_to_level(0.10),
        source_engine=SourceEngine.RISK_ENGINE,
        source_fields=["intent_country", "proposal_country"],
    )


# ── Helper ─────────────────────────────────────────────────────────


def _contribution_to_level(contribution: float) -> str | None:
    """Map a risk contribution to a human-readable level."""
    if contribution >= 0.50:
        return "critical"
    if contribution >= 0.30:
        return "high"
    if contribution >= 0.10:
        return "medium"
    if contribution > 0.0:
        return "low"
    return None
