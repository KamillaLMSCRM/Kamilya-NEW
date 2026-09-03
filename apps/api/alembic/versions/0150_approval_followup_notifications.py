"""Add safe approval follow-up delivery kinds and notification inbox."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0150"
down_revision = "0149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_deliveries", sa.Column("message_kind", sa.String(32), nullable=False, server_default="invitation"))
    op.create_check_constraint(
        "ck_workflow_delivery_message_kind",
        "workflow_deliveries",
        "message_kind IN ('invitation','course_review_assigned','course_review_reminder','course_review_overdue')",
    )
    op.create_table(
        "notification_inbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_delivery_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("context", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("action_path", sa.Text, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_delivery_id"], ["workflow_deliveries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_delivery_id", name="uq_notification_inbox_source_delivery"),
        sa.CheckConstraint("kind IN ('course_review_assigned','course_review_reminder','course_review_overdue')", name="ck_notification_inbox_kind"),
    )
    op.create_index("ix_notification_inbox_tenant_id", "notification_inbox", ["tenant_id"])
    op.create_index("ix_notification_inbox_recipient_user_id", "notification_inbox", ["recipient_user_id"])
    op.execute("ALTER TABLE notification_inbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_inbox FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE FUNCTION enforce_notification_inbox_tenant_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE delivery_tenant uuid; delivery_recipient uuid; user_tenant uuid;
        BEGIN
            SELECT tenant_id, recipient_user_id INTO delivery_tenant, delivery_recipient
              FROM workflow_deliveries WHERE id = NEW.source_delivery_id;
            SELECT tenant_id INTO user_tenant FROM users WHERE id = NEW.recipient_user_id;
            IF delivery_tenant IS DISTINCT FROM NEW.tenant_id THEN
                RAISE EXCEPTION 'notification source delivery tenant mismatch' USING ERRCODE='check_violation';
            END IF;
            IF user_tenant IS DISTINCT FROM NEW.tenant_id THEN
                RAISE EXCEPTION 'notification recipient tenant mismatch' USING ERRCODE='check_violation';
            END IF;
            IF delivery_recipient IS DISTINCT FROM NEW.recipient_user_id THEN
                RAISE EXCEPTION 'notification source recipient mismatch' USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("CREATE TRIGGER notification_inbox_tenant_integrity BEFORE INSERT OR UPDATE ON notification_inbox FOR EACH ROW EXECUTE FUNCTION enforce_notification_inbox_tenant_integrity()")
    op.execute("""
        CREATE POLICY notification_inbox_tenant_policy ON notification_inbox
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE ON notification_inbox TO lms_app")


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM notification_inbox LIMIT 1) THEN
                RAISE EXCEPTION 'Refusing destructive notification-inbox downgrade: rows remain'
                    USING ERRCODE = 'dependent_objects_still_exist';
            END IF;
        END
        $$
    """)
    op.execute("DROP POLICY IF EXISTS notification_inbox_tenant_policy ON notification_inbox")
    op.execute("DROP TRIGGER IF EXISTS notification_inbox_tenant_integrity ON notification_inbox")
    op.execute("DROP FUNCTION IF EXISTS enforce_notification_inbox_tenant_integrity()")
    op.drop_index("ix_notification_inbox_recipient_user_id", table_name="notification_inbox")
    op.drop_index("ix_notification_inbox_tenant_id", table_name="notification_inbox")
    op.drop_table("notification_inbox")
    op.drop_constraint("ck_workflow_delivery_message_kind", "workflow_deliveries", type_="check")
    op.drop_column("workflow_deliveries", "message_kind")
