"""Secure learner access without email.

Revision ID: 0096
Revises: 0095
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_access_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.Text()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_assignment_access_tenant_user", "assignment_access_credentials", ["tenant_id", "user_id"])
    op.create_index(
        "uq_assignment_access_active_enrollment",
        "assignment_access_credentials",
        ["enrollment_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.execute("ALTER TABLE assignment_access_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assignment_access_credentials FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE assignment_access_credentials FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE assignment_access_credentials TO lms_app")
    op.execute(
        """CREATE POLICY assignment_access_tenant ON assignment_access_credentials USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
    )
    op.execute(
        """
        CREATE FUNCTION validate_assignment_access_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM enrollments e
                JOIN users u ON u.id = e.user_id
                WHERE e.id = NEW.enrollment_id
                  AND e.tenant_id = NEW.tenant_id
                  AND e.user_id = NEW.user_id
                  AND u.tenant_id = NEW.tenant_id
                  AND (
                      u.role = 'student'
                      OR EXISTS (
                          SELECT 1 FROM user_roles ur
                          WHERE ur.user_id = u.id
                            AND ur.tenant_id = NEW.tenant_id
                            AND ur.role = 'student'
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'assignment access tenant/enrollment/user mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER assignment_access_ownership BEFORE INSERT OR UPDATE ON assignment_access_credentials FOR EACH ROW EXECUTE FUNCTION validate_assignment_access_ownership()"
    )
    op.execute(
        """CREATE FUNCTION lookup_assignment_access_tenant_by_token(access_token_hash text) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$ SELECT tenant_id FROM assignment_access_credentials WHERE token_hash = access_token_hash AND revoked_at IS NULL AND expires_at > now() LIMIT 1 $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION lookup_assignment_access_tenant_by_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_assignment_access_tenant_by_token(text) TO lms_app")


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN IF EXISTS (SELECT 1 FROM assignment_access_credentials) THEN RAISE EXCEPTION '0096 downgrade refused: assignment access credential/revocation history exists; archive or explicitly revoke and remove it before downgrade'; END IF; END $$"""
    )
    op.execute("DROP FUNCTION IF EXISTS lookup_assignment_access_tenant_by_token(text)")
    op.execute("DROP FUNCTION IF EXISTS validate_assignment_access_ownership() CASCADE")
    op.drop_index("uq_assignment_access_active_enrollment", table_name="assignment_access_credentials")
    op.drop_index("ix_assignment_access_tenant_user", table_name="assignment_access_credentials")
    op.drop_table("assignment_access_credentials")
