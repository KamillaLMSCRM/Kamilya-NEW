"""Add explicit delivery and time windows for employee enrollments.

Revision ID: 0106
Revises: 0105
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enrollment_access_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_mode", sa.String(), nullable=False, server_default="email"),
        sa.Column("link_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completion_window_minutes", sa.Integer()),
        sa.Column("completion_window_started_at", sa.DateTime(timezone=True)),
        sa.Column("completion_window_expires_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "delivery_mode IN ('email', 'personal_link')", name="ck_enrollment_access_policy_delivery_mode"
        ),
        sa.CheckConstraint(
            "completion_window_minutes IS NULL OR completion_window_minutes BETWEEN 1 AND 1440",
            name="ck_enrollment_access_policy_window_minutes",
        ),
    )
    op.create_index("ix_enrollment_access_policies_tenant_user", "enrollment_access_policies", ["tenant_id", "user_id"])
    op.execute("ALTER TABLE enrollment_access_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE enrollment_access_policies FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE enrollment_access_policies FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE enrollment_access_policies TO lms_app")
    op.execute(
        """CREATE POLICY enrollment_access_policies_tenant ON enrollment_access_policies
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
    )
    op.execute(
        """CREATE FUNCTION validate_enrollment_access_policy_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM enrollments e JOIN users u ON u.id = e.user_id
            WHERE e.id = NEW.enrollment_id AND e.tenant_id = NEW.tenant_id
              AND e.user_id = NEW.user_id AND u.tenant_id = NEW.tenant_id
          ) THEN RAISE EXCEPTION 'enrollment access policy tenant/enrollment/user mismatch'; END IF;
          RETURN NEW;
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER enrollment_access_policy_ownership BEFORE INSERT OR UPDATE ON enrollment_access_policies
        FOR EACH ROW EXECUTE FUNCTION validate_enrollment_access_policy_ownership()"""
    )


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM enrollment_access_policies) THEN
          RAISE EXCEPTION '0106 downgrade refused: enrollment delivery/access policy history exists; archive it before downgrade';
        END IF; END $$"""
    )
    op.execute("DROP FUNCTION IF EXISTS validate_enrollment_access_policy_ownership() CASCADE")
    op.drop_index("ix_enrollment_access_policies_tenant_user", table_name="enrollment_access_policies")
    op.drop_table("enrollment_access_policies")
