"""Add tenant-scoped support requests.

Revision ID: 0121
Revises: 0120
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0121"
down_revision = "0120"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "support_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requester_email", sa.Text(), nullable=True),
        sa.Column("requester_name", sa.Text(), nullable=False),
        sa.Column("requester_role", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("current_path", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("delivery_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("delivery_failure_category", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("category IN ('access', 'technical', 'learning', 'staff', 'billing', 'other')", name="ck_support_requests_category"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_support_requests_status"),
        sa.CheckConstraint("delivery_status IN ('pending', 'sent', 'deferred', 'failed')", name="ck_support_requests_delivery_status"),
    )
    op.create_index("ix_support_requests_tenant_id", "support_requests", ["tenant_id"])
    op.create_index("ix_support_requests_created_by", "support_requests", ["created_by"])
    op.create_index("ix_support_requests_created_at", "support_requests", ["created_at"])

    op.execute(
        """
        CREATE FUNCTION validate_support_request_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
            IF NEW.created_by IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM users
                 WHERE id = NEW.created_by
                   AND tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'support request user tenant mismatch'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_support_request_ownership
        BEFORE INSERT OR UPDATE OF tenant_id, created_by ON support_requests
        FOR EACH ROW EXECUTE FUNCTION validate_support_request_ownership()
        """
    )
    op.execute("ALTER TABLE support_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE support_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_support_requests_isolation ON support_requests FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("REVOKE ALL ON TABLE support_requests FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON support_requests TO lms_app")


def downgrade() -> None:
    op.execute("ALTER TABLE support_requests NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM support_requests LIMIT 1) THEN
            RAISE EXCEPTION '0121 downgrade refused: support requests exist and require an approved retention export';
          END IF;
        END $$;
        """
    )
    op.execute("DROP POLICY IF EXISTS tenant_support_requests_isolation ON support_requests")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_support_request_ownership ON support_requests")
    op.execute("DROP FUNCTION IF EXISTS validate_support_request_ownership()")
    op.drop_index("ix_support_requests_created_at", table_name="support_requests")
    op.drop_index("ix_support_requests_created_by", table_name="support_requests")
    op.drop_index("ix_support_requests_tenant_id", table_name="support_requests")
    op.drop_table("support_requests")
