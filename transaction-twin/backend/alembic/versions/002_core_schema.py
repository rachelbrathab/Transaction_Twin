"""create core transaction twin schema

Revision ID: 002_core_schema
Revises: 001_initial
Create Date: 2026-08-22

Creates all 11 core business tables:
  users, agents, agent_capabilities, intents, policies, merchants,
  transactions, transaction_events, risk_assessments, decisions, audit_events
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_core_schema"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("external_reference", sa.String(255), unique=True, nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── agents ─────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("trust_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("reputation_snapshot", postgresql.JSONB, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)",
            name="ck_agents_trust_score_range",
        ),
    )
    op.create_index("ix_agents_user_id", "agents", ["user_id"])

    # ── agent_capabilities ─────────────────────────────────────────
    op.create_table(
        "agent_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_id", "capability", name="uq_agent_capability"),
    )

    # ── intents ────────────────────────────────────────────────────
    op.create_table(
        "intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_request", sa.Text, nullable=False),
        sa.Column("structured_intent", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("min_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("category_constraints", postgresql.JSONB, nullable=True),
        sa.Column("merchant_constraints", postgresql.JSONB, nullable=True),
        sa.Column("geographic_constraints", postgresql.JSONB, nullable=True),
        sa.Column("authorization_scope", sa.String(50), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "max_amount IS NULL OR min_amount IS NULL OR max_amount >= min_amount",
            name="ck_intents_amount_bounds",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_intents_confidence_range",
        ),
    )
    op.create_index("ix_intents_user_id", "intents", ["user_id"])
    op.create_index("ix_intents_agent_id", "intents", ["agent_id"])

    # ── policies ───────────────────────────────────────────────────
    op.create_table(
        "policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("rules", postgresql.JSONB, nullable=True),
        sa.Column("scope", postgresql.JSONB, nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "name", "version", name="uq_policy_user_name_version"),
    )
    op.create_index("ix_policies_user_id", "policies", ["user_id"])

    # ── merchants ──────────────────────────────────────────────────
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("external_reference", sa.String(255), unique=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("trust_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)",
            name="ck_merchants_trust_score_range",
        ),
    )

    # ── transactions ───────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(50), nullable=False, server_default="proposed"),
        sa.Column("payment_provider_reference", sa.String(255), nullable=True),
        sa.Column("payment_provider_status", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_id", "idempotency_key", name="uq_transaction_agent_idempotency"),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_agent_id", "transactions", ["agent_id"])
    op.create_index("ix_transactions_intent_id", "transactions", ["intent_id"])
    op.create_index("ix_transactions_policy_id", "transactions", ["policy_id"])
    op.create_index("ix_transactions_merchant_id", "transactions", ["merchant_id"])

    # ── transaction_events ─────────────────────────────────────────
    op.create_table(
        "transaction_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("transaction_id", "sequence_number", name="uq_event_transaction_sequence"),
        sa.CheckConstraint("sequence_number > 0", name="ck_events_sequence_positive"),
    )
    op.create_index("ix_transaction_events_transaction_id", "transaction_events", ["transaction_id"])

    # ── risk_assessments ───────────────────────────────────────────
    op.create_table(
        "risk_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("intent_match_score", sa.Float, nullable=True),
        sa.Column("behavioral_risk", sa.Float, nullable=True),
        sa.Column("agent_trust_score", sa.Float, nullable=True),
        sa.Column("policy_risk", sa.Float, nullable=True),
        sa.Column("velocity_risk", sa.Float, nullable=True),
        sa.Column("merchant_risk", sa.Float, nullable=True),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("features", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 1)",
            name="ck_risk_overall_score_range",
        ),
        sa.CheckConstraint(
            "intent_match_score IS NULL OR (intent_match_score >= 0 AND intent_match_score <= 1)",
            name="ck_risk_intent_match_score_range",
        ),
        sa.CheckConstraint(
            "behavioral_risk IS NULL OR (behavioral_risk >= 0 AND behavioral_risk <= 1)",
            name="ck_risk_behavioral_risk_range",
        ),
        sa.CheckConstraint(
            "agent_trust_score IS NULL OR (agent_trust_score >= 0 AND agent_trust_score <= 1)",
            name="ck_risk_agent_trust_score_range",
        ),
        sa.CheckConstraint(
            "policy_risk IS NULL OR (policy_risk >= 0 AND policy_risk <= 1)",
            name="ck_risk_policy_risk_range",
        ),
        sa.CheckConstraint(
            "velocity_risk IS NULL OR (velocity_risk >= 0 AND velocity_risk <= 1)",
            name="ck_risk_velocity_risk_range",
        ),
        sa.CheckConstraint(
            "merchant_risk IS NULL OR (merchant_risk >= 0 AND merchant_risk <= 1)",
            name="ck_risk_merchant_risk_range",
        ),
    )
    op.create_index("ix_risk_assessments_transaction_id", "risk_assessments", ["transaction_id"])

    # ── decisions ──────────────────────────────────────────────────
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("risk_assessment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("risk_assessments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("explanation", postgresql.JSONB, nullable=True),
        sa.Column("override_status", sa.String(50), nullable=True),
        sa.Column("override_actor_id", sa.String(255), nullable=True),
        sa.Column("override_reason", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("transaction_id", "version", name="uq_decision_transaction_version"),
    )
    op.create_index("ix_decisions_transaction_id", "decisions", ["transaction_id"])

    # ── audit_events ───────────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor_type", sa.String(50), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("previous_hash", sa.String(64), nullable=True),
        sa.Column("current_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("decisions")
    op.drop_table("risk_assessments")
    op.drop_table("transaction_events")
    op.drop_table("transactions")
    op.drop_table("merchants")
    op.drop_table("policies")
    op.drop_table("intents")
    op.drop_table("agent_capabilities")
    op.drop_table("agents")
    op.drop_table("users")
