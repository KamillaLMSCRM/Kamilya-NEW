"""add user_agent column to audit_logs

Revision ID: 0016
Revises: 0015_add_documents_file_url_updated_at
Create Date: 2026-06-23
"""
import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015_add_documents_file_url_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit_logs")}
    if "user_agent" not in columns:
        with op.batch_alter_table("audit_logs") as batch_op:
            batch_op.add_column(sa.Column("user_agent", sa.Text, nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit_logs")}
    if "user_agent" in columns:
        with op.batch_alter_table("audit_logs") as batch_op:
            batch_op.drop_column("user_agent")
