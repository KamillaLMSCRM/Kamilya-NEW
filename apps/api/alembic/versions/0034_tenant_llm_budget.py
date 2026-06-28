"""Add per-tenant LLM budget tracking (audit §6.3).

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-28

Adds:
  - tenant_settings.monthly_llm_budget_usd_cents (default 5000 = $50/month)
  - tenant_llm_usage table (one row per tenant per UTC month)
"""

from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-tenant budget cap (USD cents). Default $50/month.
    op.add_column(
        "tenant_settings",
        sa.Column(
            "monthly_llm_budget_usd_cents",
            sa.Integer(),
            nullable=False,
            server_default="5000",
        ),
    )
    op.create_check_constraint(
        "ck_tenant_llm_budget_nonneg",
        "tenant_settings",
        "monthly_llm_budget_usd_cents >= 0",
    )

    # Usage tracking table — one row per (tenant, UTC month).
    op.create_table(
        "tenant_llm_usage",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("month_key", sa.String(7), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "month_key", name="uq_tenant_llm_usage_tenant_month"),
    )


def downgrade() -> None:
    op.drop_table("tenant_llm_usage")
    op.drop_constraint("ck_tenant_llm_budget_nonneg", "tenant_settings", type_="check")
    op.drop_column("tenant_settings", "monthly_llm_budget_usd_cents")