"""bootstrap: create positions + sync documents columns

Revision ID: 0011
Revises: 0010_sync_schema_positions_and_documents
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def column_exists(bind, table, column):
    result = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c)"),
        {"t": table, "c": column},
    )
    return result.scalar()


def table_exists(bind, table):
    result = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name=:t)"),
        {"t": table},
    )
    return result.scalar()


def upgrade() -> None:
    bind = op.get_bind()

    # Documents: add missing columns
    for col, typ, default in [
        ("filename", "TEXT", "'unknown'"),
        ("s3_key", "TEXT", "''"),
        ("description", "TEXT", "''"),
    ]:
        if not column_exists(bind, "documents", col):
            bind.execute(sa.text(f'ALTER TABLE documents ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}'))

    # Positions: create if not exists
    if not table_exists(bind, "positions"):
        op.create_table(
            "positions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("department", sa.Text, nullable=False, server_default=""),
            sa.Column("level", sa.Text, nullable=False, server_default=""),
            sa.Column("responsibilities", sa.Text, nullable=False, server_default=""),
            sa.Column("requirements", sa.Text, nullable=False, server_default=""),
            sa.Column("course_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("employee_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    else:
        # Add missing columns to existing positions table
        for col, typ, nullable, default in [
            ("responsibilities", "TEXT", False, "''"),
            ("requirements", "TEXT", False, "''"),
            ("course_id", "UUID", True, None),
        ]:
            if not column_exists(bind, "positions", col):
                if default:
                    bind.execute(sa.text(f"ALTER TABLE positions ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}"))
                else:
                    bind.execute(sa.text(f"ALTER TABLE positions ADD COLUMN {col} {typ}"))


def downgrade() -> None:
    pass
