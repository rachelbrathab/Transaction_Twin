"""Intent Engine domain models — the parsing contract.

These Pydantic v2 models define the structured representation of user intent.
They are the source of truth for what the Intent Engine produces.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# ── Enums ──────────────────────────────────────────────────────────


class GoalType(StrEnum):
    PURCHASE = "purchase"
    BOOKING = "booking"
    REFUND = "refund"
    SUBSCRIPTION = "subscription"
    TRANSFER = "transfer"


class TransactionType(StrEnum):
    PURCHASE = "purchase"
    REFUND = "refund"
    BOOKING = "booking"
    SUBSCRIPTION = "subscription"
    TRANSFER = "transfer"


class CurrencySource(StrEnum):
    EXPLICIT = "explicit"
    USER_DEFAULT = "user_default"
    APP_DEFAULT = "app_default"
    UNKNOWN = "unknown"


class AmbiguitySeverity(StrEnum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class ParseStatus(StrEnum):
    PARSED = "parsed"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    ERROR = "error"


class ExtractionMethod(StrEnum):
    LLM = "llm"
    DETERMINISTIC = "deterministic"


# ── Evidence ───────────────────────────────────────────────────────


class Evidence(BaseModel):
    """Source evidence for an extracted constraint."""

    text_span: str = Field(..., description="Exact substring from canonical_request")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Parser confidence in this extraction"
    )


# ── Currency ───────────────────────────────────────────────────────


class CurrencyInfo(BaseModel):
    """Resolved currency with source tracking."""

    code: str | None = Field(
        None, min_length=3, max_length=3, description="ISO 4217 currency code"
    )
    source: CurrencySource = Field(
        ..., description="How this currency was determined"
    )
    evidence: Evidence | None = Field(
        None,
        description="Evidence when source is explicit; null for defaults",
    )


# ── Amount ─────────────────────────────────────────────────────────


class AmountConstraints(BaseModel):
    """Amount constraints extracted from user request."""

    min: float | None = Field(None, ge=0.0, description="Minimum amount")
    max: float | None = Field(None, ge=0.0, description="Maximum amount")
    exact: float | None = Field(None, ge=0.0, description="Exact target amount")
    evidence: Evidence | None = Field(
        None, description="Where the amount came from in the text"
    )

    @model_validator(mode="after")
    def validate_amount_consistency(self) -> AmountConstraints:
        if self.exact is not None:
            if self.min is not None and self.exact < self.min:
                msg = "exact amount cannot be less than min_amount"
                raise ValueError(msg)
            if self.max is not None and self.exact > self.max:
                msg = "exact amount cannot be greater than max_amount"
                raise ValueError(msg)
        if self.min is not None and self.max is not None:
            if self.min > self.max:
                msg = "min_amount cannot exceed max_amount"
                raise ValueError(msg)
        return self


# ── Category ───────────────────────────────────────────────────────


class CategoryConstraints(BaseModel):
    """Product or service category constraints."""

    items: list[str] = Field(default_factory=list, description="Product names")
    attributes: dict[str, str] = Field(
        default_factory=dict, description="Product attributes (color, size, etc.)"
    )
    confidence: float = Field(
        0.0, ge=0.0, le=1.0, description="Extraction confidence for category"
    )
    evidence: Evidence | None = None


# ── Merchant ───────────────────────────────────────────────────────


class MerchantConstraints(BaseModel):
    """Merchant preferences and restrictions."""

    trust_required: bool = Field(False, description="Requires trusted seller")
    preferred: list[str] = Field(default_factory=list, description="Preferred merchants")
    excluded: list[str] = Field(default_factory=list, description="Excluded merchants")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: Evidence | None = None


# ── Geographic ─────────────────────────────────────────────────────


class GeographicConstraints(BaseModel):
    """Location-based constraints."""

    country: str | None = None
    city: str | None = None
    radius_km: float | None = Field(None, ge=0.0)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: Evidence | None = None


# ── Temporal ───────────────────────────────────────────────────────


class TemporalConstraints(BaseModel):
    """Time-based constraints."""

    deadline: datetime | None = None
    duration: str | None = Field(None, description="Duration description (e.g., '2 nights')")
    recurring: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence: Evidence | None = None


# ── Authorization Scope ────────────────────────────────────────────


class AuthorizationScopeValue(StrEnum):
    SINGLE_USE = "single_use"
    RECURRING = "recurring"
    SESSION = "session"


class AuthorizationScope(BaseModel):
    """Authorization scope — null unless explicitly established."""

    value: AuthorizationScopeValue | None = Field(
        None, description="Null when user did not specify scope"
    )
    evidence: Evidence | None = Field(
        None, description="Null when value is null"
    )

    @model_validator(mode="after")
    def validate_evidence_matches_value(self) -> AuthorizationScope:
        if self.value is None and self.evidence is not None:
            msg = "evidence must be null when scope value is null"
            raise ValueError(msg)
        return self


# ── Metadata ───────────────────────────────────────────────────────


class IntentMetadata(BaseModel):
    """Parser metadata for traceability."""

    parser_version: str = Field(..., description="Prompt/version identifier")
    model_provider: str = Field(default="deterministic")
    model_name: str = Field(default="none")
    extraction_method: ExtractionMethod
    parsing_latency_ms: int = Field(0, ge=0)
    canonical_request: str = Field(..., description="Normalized user request")
    reference_timestamp: str = Field(..., description="ISO 8601 timestamp used for parsing")
    injection_detected: bool = Field(False, description="Injection patterns found")


# ── Structured Intent ──────────────────────────────────────────────


class StructuredIntent(BaseModel):
    """Complete structured intent — the parsing contract output."""

    goal: GoalType
    transaction_type: TransactionType
    currency: CurrencyInfo
    amount: AmountConstraints
    category_constraints: CategoryConstraints = Field(default_factory=CategoryConstraints)
    merchant_constraints: MerchantConstraints = Field(default_factory=MerchantConstraints)
    geographic_constraints: GeographicConstraints = Field(
        default_factory=GeographicConstraints
    )
    temporal_constraints: TemporalConstraints = Field(
        default_factory=TemporalConstraints
    )
    authorization_scope: AuthorizationScope = Field(default_factory=AuthorizationScope)
    metadata: IntentMetadata


# ── Ambiguity ──────────────────────────────────────────────────────


class Ambiguity(BaseModel):
    """A missing or unclear constraint."""

    field: str = Field(..., description="Field name that is ambiguous")
    severity: AmbiguitySeverity
    message: str = Field(..., description="Human-readable clarification prompt")


# ── Parse Result ───────────────────────────────────────────────────


class ParseResult(BaseModel):
    """Final result of intent parsing."""

    status: ParseStatus
    intent_id: str | None = Field(None, description="UUID if persisted")
    version: int | None = None
    structured_intent: StructuredIntent | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    rejection_reason: str | None = None


# ── API Request/Response ──────────────────────────────────────────


class IntentParseRequest(BaseModel):
    """Request body for POST /api/v1/intents/parse."""

    user_id: str = Field(..., description="User UUID")
    agent_id: str = Field(..., description="Agent UUID")
    original_request: str = Field(
        ..., min_length=1, max_length=5000, description="Natural language request"
    )
    default_currency: str = Field(
        default="INR", min_length=3, max_length=3, description="User/app default currency"
    )
    transaction_type_hint: TransactionType | None = Field(
        None, description="Optional hint for the parser"
    )


class IntentParseResponse(BaseModel):
    """Response body for POST /api/v1/intents/parse."""

    status: ParseStatus
    intent_id: str | None = None
    version: int | None = None
    structured_intent: dict[str, Any] | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    ambiguities: list[dict[str, str]] = Field(default_factory=list)
    rejection_reason: str | None = None
