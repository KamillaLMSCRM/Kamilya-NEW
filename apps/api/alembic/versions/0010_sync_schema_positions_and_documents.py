"""sync schema: add filename/s3_key/description to documents, add columns to positions

Revision ID: 0010
Revises: 0009_add_document_description
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009_add_document_description"
branch_labels = None
depends_on = None


def column_exists(table, column):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column)"
        ),
        {"table": table, "column": column},
    )
    return result.scalar()


def table_exists(table):
    """Check if a table exists."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table)"
        ),
        {"table": table},
    )
    return result.scalar()


def upgrade() -> None:
    # Documents: add missing columns
    if not column_exists("documents", "filename"):
        op.add_column("documents", sa.Column("filename", sa.Text, nullable=False, server_default="unknown"))
    if not column_exists("documents", "s3_key"):
        op.add_column("documents", sa.Column("s3_key", sa.Text, nullable=False, server_default=""))
    if not column_exists("documents", "description"):
        op.add_column("documents", sa.Column("description", sa.Text, nullable=False, server_default=""))

    # Positions: add missing columns (table may or may not exist)
    if not table_exists("positions"):
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
        for col, typ, default in [
            ("responsibilities", sa.Text, ""),
            ("requirements", sa.Text, ""),
            ("course_id", sa.dialects.postgresql.UUID(as_uuid=True), None),
        ]:
            if not column_exists("positions", col):
                if default is not None:
                    op.add_column("positions", sa.Column(col, typ, nullable=False, server_default=default))
                else:
                    op.add_column("positions", sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    if column_exists("positions", "requirements"):
        op.drop_column("positions", "requirements")
    if column_exists("positions", "responsibilities"):
        op.drop_column("positions", "responsibilities")
    if column_exists("positions", "course_id"):
        op.drop_column("positions", "course_id")
    op.drop_column("documents", "description")
    op.drop_column("documents", "s3_key")
    op.drop_column("documents", "filename")
