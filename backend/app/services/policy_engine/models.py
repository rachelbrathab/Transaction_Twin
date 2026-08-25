"""Policy Engine domain models.

Strongly typed Pydantic models for policy rules, conditions, evaluation context,
and results. Includes operator registry and security limits.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Enums ──────────────────────────────────────────────────────────


class Operator(StrEnum):
    """Supported policy condition operators. All deterministic — no eval/exec."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    CONTAINS_ANY = "contains_any"
    MATCHES = "matches"
    BETWEEN = "between"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class ValueType(StrEnum):
    """Value types for condition values."""

    STRING = "string"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    LIST = "list"
    DATETIME = "datetime"


class PolicySeverity(StrEnum):
    """Policy severity — not a risk score."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyCategory(StrEnum):
    """Policy categories."""

    AMOUNT_LIMIT = "amount_limit"
    MERCHANT_RESTRICTION = "merchant_restriction"
    CATEGORY_RESTRICTION = "category_restriction"
    GEOGRAPHIC_RESTRICTION = "geographic_restriction"
    TEMPORAL_RESTRICTION = "temporal_restriction"
    CURRENCY_RESTRICTION = "currency_restriction"
    TRANSACTION_TYPE_RESTRICTION = "transaction_type_restriction"
    AUTHORIZATION_SCOPE = "authorization_scope"
    DRIFT_THRESHOLD = "drift_threshold"
    AGENT_RESTRICTION = "agent_restriction"
    FREQUENCY_LIMIT = "frequency_limit"
    APPROVAL_REQUIREMENT = "approval_requirement"


class PolicyEvaluationStatus(StrEnum):
    """Per-policy evaluation status. Never ALLOW/BLOCK/REVIEW."""

    PASS = "pass"
    TRIGGERED = "triggered"
    UNKNOWN = "unknown"
    INVALID_POLICY = "invalid_policy"


class ConditionStatus(StrEnum):
    """Per-condition comparison status."""

    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class LogicOperator(StrEnum):
    """Rule-level logic for combining conditions."""

    ALL = "all"
    ANY = "any"


# ── Limits ─────────────────────────────────────────────────────────

MAX_RULES_PER_POLICY = 50
MAX_CONDITIONS_PER_RULE = 10
MAX_REGEX_LENGTH = 200


# ── Policy Condition ───────────────────────────────────────────────


class PolicyCondition(BaseModel):
    """A single condition within a rule."""

    field: str = Field(..., min_length=1, description="Context field name")
    operator: Operator = Field(..., description="Comparison operator")
    value: Any = Field(None, description="Expected value for comparison")
    value_type: ValueType = Field(default=ValueType.STRING, description="Value type hint")
    description: str = Field(default="", description="Human-readable condition description")


# ── Policy Rule ────────────────────────────────────────────────────


class PolicyRule(BaseModel):
    """A single rule containing one or more conditions."""

    name: str = Field(..., min_length=1, description="Rule name")
    description: str = Field(default="", description="Human-readable rule description")
    severity: PolicySeverity = Field(default=PolicySeverity.MEDIUM, description="Rule severity")
    category: PolicyCategory = Field(
        default=PolicyCategory.AMOUNT_LIMIT,
        description="Rule category"
    )
    logic: LogicOperator = Field(default=LogicOperator.ALL, description="How to combine conditions")
    conditions: list[PolicyCondition] = Field(
        ..., min_length=1, description="Conditions to evaluate"
    )

    @field_validator("conditions")
    @classmethod
    def validate_conditions_count(cls, v: list[PolicyCondition]) -> list[PolicyCondition]:
        if len(v) > MAX_CONDITIONS_PER_RULE:
            msg = f"Maximum {MAX_CONDITIONS_PER_RULE} conditions per rule"
            raise ValueError(msg)
        return v


# ── Policy Rule Set ────────────────────────────────────────────────


class PolicyRuleSet(BaseModel):
    """Complete rule set for a policy. Stored in policies.rules JSONB."""

    rules: list[PolicyRule] = Field(
        ..., min_length=1, description="List of rules to evaluate"
    )

    @field_validator("rules")
    @classmethod
    def validate_rules_count(cls, v: list[PolicyRule]) -> list[PolicyRule]:
        if len(v) > MAX_RULES_PER_POLICY:
            msg = f"Maximum {MAX_RULES_PER_POLICY} rules per policy"
            raise ValueError(msg)
        return v


# ── Policy Scope ───────────────────────────────────────────────────


class PolicyScope(BaseModel):
    """Applicability scope for a policy. Stored in policies.scope JSONB."""

    transaction_types: list[str] | None = Field(None, description="Applicable transaction types")
    agent_ids: list[str] | None = Field(None, description="Applicable agent UUIDs")
    categories: list[str] | None = Field(None, description="Applicable categories")
    countries: list[str] | None = Field(None, description="Applicable country codes")
    currencies: list[str] | None = Field(None, description="Applicable currency codes")
    merchant_names: list[str] | None = Field(None, description="Applicable merchant names")

    # Exclusions
    exclude_agent_ids: list[str] | None = Field(None, description="Excluded agent UUIDs")
    exclude_merchant_names: list[str] | None = Field(None, description="Excluded merchant names")


# ── Evaluation Context ─────────────────────────────────────────────


class EvaluationContext(BaseModel):
    """Flat typed context for policy condition evaluation.

    Contains all fields that policy conditions may reference.
    Built from StructuredIntent + TransactionProposal + DriftResult.
    """

    # Proposal fields
    proposal_amount: Decimal | None = None
    proposal_currency: str | None = None
    proposal_transaction_type: str | None = None
    proposal_category: str | None = None
    proposal_merchant_name: str | None = None
    proposal_merchant_trusted: bool | None = None
    proposal_country: str | None = None
    proposal_city: str | None = None
    proposal_scheduled_at: datetime | None = None
    proposal_authorization_scope: str | None = None

    # Intent fields
    intent_transaction_type: str | None = None
    intent_currency: str | None = None
    intent_amount_min: Decimal | None = None
    intent_amount_max: Decimal | None = None
    intent_category: str | None = None
    intent_merchant_trust_required: bool | None = None

    # Drift fields
    drift_overall_status: str | None = None
    drift_severity: str | None = None
    drift_amount_status: str | None = None
    drift_amount_deviation_percent: Decimal | None = None
    drift_currency_status: str | None = None
    drift_category_status: str | None = None
    drift_merchant_status: str | None = None
    drift_geographic_status: str | None = None
    drift_temporal_status: str | None = None
    drift_transaction_type_status: str | None = None
    drift_authorization_scope_status: str | None = None

    # Identity
    user_id: str | None = None
    agent_id: str | None = None

    def get_field_value(self, field_name: str) -> Any:
        """Get a field value by name. Returns None if field doesn't exist."""
        return getattr(self, field_name, None)


# ── Condition Result ───────────────────────────────────────────────


class ConditionResult(BaseModel):
    """Result of evaluating a single condition."""

    field: str
    operator: str
    expected_value: Any = None
    observed_value: Any = None
    status: ConditionStatus
    explanation: str = ""


# ── Rule Result ────────────────────────────────────────────────────


class RuleResult(BaseModel):
    """Result of evaluating a single rule."""

    name: str
    description: str
    category: str
    severity: PolicySeverity
    status: PolicyEvaluationStatus
    condition_results: list[ConditionResult] = Field(default_factory=list)
    explanation: str = ""


# ── Policy Result ──────────────────────────────────────────────────


class PolicyResult(BaseModel):
    """Result of evaluating a single policy."""

    policy_id: str
    policy_version: int
    policy_name: str
    status: PolicyEvaluationStatus
    rule_results: list[RuleResult] = Field(default_factory=list)
    matched_rule_count: int = Field(default=0, ge=0)
    triggered_rule_count: int = Field(default=0, ge=0)
    unknown_rule_count: int = Field(default=0, ge=0)
    highest_triggered_severity: PolicySeverity = PolicySeverity.NONE
    explanation: str = ""
    evaluated_at: str = ""
    evaluator_version: str = "policy-v1"


# ── Policy Evaluation Result (aggregate) ───────────────────────────


class PolicyEvaluationResult(BaseModel):
    """Complete result of evaluating all applicable policies."""

    intent_id: str
    proposal_intent_id: str
    evaluation_id: str
    policy_results: list[PolicyResult] = Field(default_factory=list)
    total_policies: int = Field(default=0, ge=0)
    triggered_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    invalid_count: int = Field(default=0, ge=0)
    pass_count: int = Field(default=0, ge=0)
    highest_severity: PolicySeverity = PolicySeverity.NONE
    summary: str = ""
    evaluated_at: str = ""
    evaluator_version: str = "policy-v1"
