"""Behavioral Engine domain models.

Strongly typed Pydantic models for agent-specific behavioral analysis.
Framework-independent. No database/HTTP/LLM dependencies.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────


class AnomalyDimension(StrEnum):
    """Individual anomaly dimensions."""

    AMOUNT = "amount"
    FREQUENCY = "frequency"
    MERCHANT = "merchant"


# ── Behavioral Context ─────────────────────────────────────────────


class TransactionRecord(BaseModel):
    """A single historical transaction for baseline computation."""

    transaction_id: str
    amount: float = Field(ge=0.0)
    currency: str = "INR"
    transaction_type: str = ""
    merchant_id: str | None = None
    created_at: str = ""  # ISO 8601


class AnomalyContext(BaseModel):
    """Pre-computed behavioral data for an agent.

    Built by the API service layer from bounded SQL queries.
    Behavioral Engine consumes but does not query the database.

    IMPORTANT: Must NOT include the current transaction being evaluated.
    Only historical transactions should be present.
    """

    agent_id: str
    user_id: str

    # Historical transactions (sorted by created_at ASC for time-series)
    transactions: list[TransactionRecord] = Field(default_factory=list)

    # Current proposal (for comparison only — NOT part of baseline)
    proposal_amount: float | None = None
    proposal_merchant_id: str | None = None

    # Metadata
    history_window_days: int = 90
    history_available: bool = False


# ── Anomaly Dimension Result ───────────────────────────────────────


class DimensionAnomaly(BaseModel):
    """A single anomaly dimension with full explainability."""

    dimension: AnomalyDimension

    # Anomaly score [0.0, 1.0]
    score: float = Field(ge=0.0, le=1.0)

    # Confidence in this dimension [0.0, 1.0]
    confidence: float = Field(ge=0.0, le=1.0)

    # Human-readable: what was observed
    what: str = ""

    # Human-readable: why it is unusual
    why: str = ""

    # Structured evidence for the frontend
    evidence: dict[str, Any] = Field(default_factory=dict)

    # Baseline description
    baseline_used: str = ""


# ── Behavioral Anomaly Result ──────────────────────────────────────


class BehavioralAnomalyResult(BaseModel):
    """Complete behavioral anomaly assessment.

    Standalone result from BehavioralBaselineEngine. Integrates with
    Risk Engine through confidence modification, not weighted scoring.
    """

    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    dimensions: list[DimensionAnomaly] = Field(default_factory=list)
    dimension_count: int = Field(default=0, ge=0)

    # Baseline metadata
    baseline_sample_size: int = Field(default=0, ge=0)
    baseline_history_days: int = Field(default=0, ge=0)

    # Explainability
    summary: str = ""

    # Metadata
    evaluation_id: str = ""
    model_version: str = "behavioral-v1"
    evaluated_at: str = ""
