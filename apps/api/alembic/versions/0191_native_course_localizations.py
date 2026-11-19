"""Add immutable, tenant-scoped native course language editions.

Revision ID: 0191
Revises: 0190
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0191"
down_revision = "0190"
branch_labels = depends_on = None

TABLE = "native_course_localizations"


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Invalid schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    op.create_table(
        TABLE,
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey(f"{schema}.tenants.id"), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey(f"{schema}.courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_sha256", sa.String(64), primary_key=True),
        sa.Column("language", sa.String(2), primary_key=True),
        sa.Column("source_language", sa.String(2), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("generation_pending", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("language IN ('ru','kk','en') AND source_language IN ('ru','kk','en') AND language<>source_language"),
        sa.CheckConstraint("length(source_sha256)=64 AND jsonb_typeof(content)='object'"),
        schema=schema,
    )
    name = f'"{schema}"."{TABLE}"'
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY native_course_localizations_tenant ON {name} TO lms_app
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {name} TO lms_app")


def downgrade() -> None:
    op.drop_table(TABLE, schema=_schema())
