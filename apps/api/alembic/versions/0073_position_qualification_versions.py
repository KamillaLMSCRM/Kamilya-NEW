"""Add immutable full snapshots for the position qualification card.

Revision ID: 0073
Revises: 0072
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_qualification_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("change_kind", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "position_id",
            "version_no",
            name="uq_position_qualification_version",
        ),
    )
    op.create_index(
        "ix_position_qualification_versions_tenant_id",
        "position_qualification_versions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_position_qualification_versions_position_id",
        "position_qualification_versions",
        ["position_id"],
    )
    op.create_index(
        "ix_position_qualification_versions_tenant_position_version",
        "position_qualification_versions",
        ["tenant_id", "position_id", "version_no"],
    )
    op.create_index(
        "ix_position_qualification_versions_tenant_position_created",
        "position_qualification_versions",
        ["tenant_id", "position_id", "created_at"],
    )

    # The application establishes app.tenant_id with set_current_tenant()
    # before any tenant-scoped request. Keep the policy fail-closed when the
    # setting is absent or empty.
    op.execute("ALTER TABLE position_qualification_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE position_qualification_versions FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON position_qualification_versions")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON position_qualification_versions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON position_qualification_versions TO lms_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON position_qualification_versions")
    op.drop_index(
        "ix_position_qualification_versions_tenant_position_created",
        table_name="position_qualification_versions",
    )
    op.drop_index(
        "ix_position_qualification_versions_tenant_position_version",
        table_name="position_qualification_versions",
    )
    op.drop_index("ix_position_qualification_versions_position_id", table_name="position_qualification_versions")
    op.drop_index("ix_position_qualification_versions_tenant_id", table_name="position_qualification_versions")
    op.drop_table("position_qualification_versions")
