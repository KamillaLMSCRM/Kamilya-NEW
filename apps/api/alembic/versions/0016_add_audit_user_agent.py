"""add user_agent column to audit_logs

Revision ID: 0016
Revises: 0015_add_documents_file_url_updated_at
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015_add_documents_file_url_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(sa.Column("user_agent", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_column("user_agent")
