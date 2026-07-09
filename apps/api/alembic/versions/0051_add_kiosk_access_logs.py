"""Add kiosk access logs.

Revision ID: 0051
Revises: 0050
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiosk_access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kiosk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("personnel_number", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["kiosk_id"], ["kiosk_links.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_kiosk_access_logs_tenant_id", "kiosk_access_logs", ["tenant_id"])
    op.create_index("ix_kiosk_access_logs_kiosk_id", "kiosk_access_logs", ["kiosk_id"])
    op.create_index("ix_kiosk_access_logs_user_id", "kiosk_access_logs", ["user_id"])
    op.create_index("ix_kiosk_access_logs_tenant_created", "kiosk_access_logs", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_kiosk_access_logs_tenant_created", table_name="kiosk_access_logs")
    op.drop_index("ix_kiosk_access_logs_user_id", table_name="kiosk_access_logs")
    op.drop_index("ix_kiosk_access_logs_kiosk_id", table_name="kiosk_access_logs")
    op.drop_index("ix_kiosk_access_logs_tenant_id", table_name="kiosk_access_logs")
    op.drop_table("kiosk_access_logs")
