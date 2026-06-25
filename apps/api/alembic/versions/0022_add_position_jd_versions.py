"""add position_jd_versions table

Stores historical snapshots of position.responsibilities and
position.requirements so the methodologist can review changes over
time and roll back if needed.

Each row is a snapshot taken either:
- manually via POST /positions/{id}/jd-versions
- automatically before any update via PUT /positions/{id}

We snapshot responsibilities+requirements (the only fields that
represent the "job description" — the human-readable part). Other
fields (name, department, level) are stable enough to be tracked
via audit logs if needed.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_jd_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("position_id", UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("responsibilities", sa.Text, nullable=False, default=""),
        sa.Column("requirements", sa.Text, nullable=False, default=""),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),  # user.id or NULL for system snapshots
        sa.Column("source", sa.String(32), nullable=False, server_default="auto"),  # "auto" | "manual"
        sa.Column("note", sa.Text, nullable=True),  # optional note like "before Q4 compliance update"
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # Index for "latest version per position" queries
    op.create_index(
        "ix_position_jd_versions_position_created",
        "position_jd_versions",
        ["position_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_position_jd_versions_position_created", table_name="position_jd_versions")
    op.drop_table("position_jd_versions")
