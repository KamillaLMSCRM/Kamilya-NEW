"""Add tenant registration and trial bookkeeping.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("billing_contact_email", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("billing_company_name", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("billing_identifier", sa.Text(), nullable=True))

    op.create_table(
        "tenant_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("employee_count_range", sa.Text(), nullable=True),
        sa.Column("preferred_language", sa.Text(), nullable=False, server_default="ru"),
        sa.Column("intent", sa.Text(), nullable=False, server_default="try"),
        sa.Column("status", sa.Text(), nullable=False, server_default="lead_submitted"),
        sa.Column("source", sa.Text(), nullable=False, server_default="landing"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_leads_tenant_id", "tenant_leads", ["tenant_id"])
    op.create_index("ix_tenant_leads_email", "tenant_leads", ["email"])

    op.create_table(
        "tenant_usage",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ai_course_generations_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jd_course_generations_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_students_count_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("system_users_count_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_leads TO lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_usage TO lms_app")


def downgrade() -> None:
    op.drop_table("tenant_usage")
    op.drop_index("ix_tenant_leads_email", table_name="tenant_leads")
    op.drop_index("ix_tenant_leads_tenant_id", table_name="tenant_leads")
    op.drop_table("tenant_leads")
    op.drop_column("tenants", "billing_identifier")
    op.drop_column("tenants", "billing_company_name")
    op.drop_column("tenants", "billing_contact_email")
    op.drop_column("tenants", "trial_started_at")
