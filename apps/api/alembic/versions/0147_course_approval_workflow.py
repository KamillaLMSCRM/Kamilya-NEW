"""Add tenant-scoped immutable course approval and review workflow tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0147"
down_revision = "0146"
branch_labels = None
depends_on = None


def _tenant_table(name: str) -> None:
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {name}_tenant ON {name} FOR ALL TO lms_app USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")
    op.execute(f"REVOKE ALL ON {name} FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO lms_app")


def upgrade() -> None:
    UUID = postgresql.UUID(as_uuid=True)
    JSONB = postgresql.JSONB
    op.create_table("course_approval_policies",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID, nullable=False), sa.Column("course_id", UUID, nullable=False, unique=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", UUID), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"))
    op.create_table("course_approval_revisions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("course_id", UUID, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False), sa.Column("snapshot", JSONB, nullable=False), sa.Column("snapshot_sha256", sa.String(64), nullable=False), sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"), sa.Column("created_by", UUID), sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("published_release_id", UUID), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["published_release_id"], ["content_releases.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "course_id", "revision_number", name="uq_course_approval_revision_number"), sa.CheckConstraint("state IN ('pending','approved','changes_requested','cancelled','superseded','published')", name="ck_course_approval_revision_state"), sa.CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_course_approval_revision_sha256"))
    op.create_table("course_approval_requests",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("revision_id", UUID, nullable=False, unique=True), sa.Column("requested_by", UUID), sa.Column("delivery_mode", sa.String(16), nullable=False), sa.Column("outcome", sa.String(24), nullable=False, server_default="pending"), sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["revision_id"], ["course_approval_revisions.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"), sa.CheckConstraint("delivery_mode IN ('email','personal_link')", name="ck_course_approval_request_delivery"), sa.CheckConstraint("outcome IN ('pending','approved','changes_requested','cancelled','superseded')", name="ck_course_approval_request_outcome"))
    op.create_table("course_approval_reviewers",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("revision_id", UUID, nullable=False), sa.Column("reviewer_user_id", UUID, nullable=False), sa.Column("required", sa.Boolean(), nullable=False, server_default="true"), sa.Column("decision", sa.String(24), nullable=False, server_default="pending"), sa.Column("decision_reason", sa.Text()), sa.Column("decision_at", sa.DateTime(timezone=True)), sa.Column("warning_acknowledged", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["revision_id"], ["course_approval_revisions.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"), sa.UniqueConstraint("revision_id", "reviewer_user_id", name="uq_course_approval_reviewer"), sa.CheckConstraint("decision IN ('pending','approved','changes_requested')", name="ck_course_approval_reviewer_decision"), sa.CheckConstraint("decision <> 'changes_requested' OR length(btrim(decision_reason)) > 0", name="ck_course_approval_return_reason"))
    op.create_table("course_review_attempts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("revision_id", UUID, nullable=False), sa.Column("reviewer_user_id", UUID, nullable=False), sa.Column("purpose", sa.String(32), nullable=False, server_default="course_review"), sa.Column("activity_state", sa.String(24), nullable=False, server_default="not_started"), sa.Column("snapshot_sha256", sa.String(64), nullable=False), sa.Column("lesson_position", sa.Integer()), sa.Column("diagnostics", JSONB, nullable=False, server_default="{}"), sa.Column("warning_acknowledged", sa.Boolean(), nullable=False, server_default="false"), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("last_activity_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["revision_id"], ["course_approval_revisions.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"), sa.UniqueConstraint("revision_id", "reviewer_user_id", name="uq_course_review_attempt_reviewer"))
    op.create_table("course_review_attempt_events",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("attempt_id", UUID, nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("event_type", sa.String(48), nullable=False), sa.Column("payload", JSONB, nullable=False, server_default="{}"), sa.Column("payload_sha256", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["attempt_id"], ["course_review_attempts.id"], ondelete="CASCADE"), sa.UniqueConstraint("attempt_id", "sequence", name="uq_course_review_attempt_event_sequence"))
    op.create_table("workflow_work_items",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("kind", sa.String(24), nullable=False), sa.Column("target_user_id", UUID), sa.Column("enrollment_id", UUID), sa.Column("review_revision_id", UUID), sa.Column("delivery_state", sa.String(24), nullable=False, server_default="queued"), sa.Column("access_state", sa.String(24), nullable=False, server_default="issued"), sa.Column("activity_state", sa.String(24), nullable=False, server_default="not_started"), sa.Column("deadline_state", sa.String(24), nullable=False, server_default="unset"), sa.Column("outcome", sa.String(32), nullable=False, server_default="pending"), sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["review_revision_id"], ["course_approval_revisions.id"], ondelete="SET NULL"), sa.CheckConstraint("(enrollment_id IS NOT NULL) <> (review_revision_id IS NOT NULL)", name="ck_work_item_exact_binding"), sa.CheckConstraint("delivery_state IN ('queued','accepted','delivered','failed')", name="ck_work_item_delivery_state"), sa.CheckConstraint("access_state IN ('issued','opened','pin_verified','active','expired','revoked')", name="ck_work_item_access_state"), sa.CheckConstraint("activity_state IN ('not_started','in_progress','completed','decision_pending')", name="ck_work_item_activity_state"), sa.CheckConstraint("deadline_state IN ('unset','scheduled','due','overdue','closed')", name="ck_work_item_deadline_state"), sa.CheckConstraint("outcome IN ('pending','approved','changes_requested','cancelled','superseded')", name="ck_work_item_outcome"))
    op.create_table("workflow_deliveries",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("work_item_id", UUID, nullable=False), sa.Column("channel", sa.String(16), nullable=False), sa.Column("generation", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.String(24), nullable=False, server_default="queued"), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("provider_message_id", sa.Text()), sa.Column("error_category", sa.String(64)), sa.Column("claim_token", UUID), sa.Column("next_attempt_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["work_item_id"], ["workflow_work_items.id"], ondelete="CASCADE"), sa.UniqueConstraint("work_item_id", "channel", "generation", name="uq_workflow_delivery_generation"), sa.CheckConstraint("channel IN ('cabinet','email')", name="ck_workflow_delivery_channel"), sa.CheckConstraint("status IN ('queued','accepted','delivered','failed')", name="ck_workflow_delivery_status"), sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 8", name="ck_workflow_delivery_attempts"))
    op.create_table("workflow_access_credentials", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("work_item_id", UUID, nullable=False), sa.Column("reviewer_user_id", UUID, nullable=False), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("pin_hash", sa.Text(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("opened_at", sa.DateTime(timezone=True)), sa.Column("verified_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("locked_until", sa.DateTime(timezone=True)), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["work_item_id"], ["workflow_work_items.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"), sa.CheckConstraint("failed_attempts >= 0 AND failed_attempts <= 5", name="ck_workflow_access_failed_attempts"))
    op.create_table("workflow_reminders", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("work_item_id", UUID, nullable=False), sa.Column("rule_key", sa.String(64), nullable=False), sa.Column("channel", sa.String(16), nullable=False, server_default="cabinet"), sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False, server_default="queued"), sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False), sa.Column("recipient_user_id", UUID), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["work_item_id"], ["workflow_work_items.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"), sa.CheckConstraint("channel IN ('cabinet','email')", name="ck_workflow_reminder_channel"))
    op.create_table("workflow_escalations", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("tenant_id", UUID, nullable=False), sa.Column("work_item_id", UUID, nullable=False), sa.Column("rule_key", sa.String(64), nullable=False), sa.Column("channel", sa.String(16), nullable=False, server_default="email"), sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False, server_default="queued"), sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False), sa.Column("recipient_user_id", UUID), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["work_item_id"], ["workflow_work_items.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"), sa.CheckConstraint("channel IN ('cabinet','email')", name="ck_workflow_escalation_channel"))
    for name in ("workflow_work_items", "workflow_deliveries", "workflow_access_credentials", "workflow_reminders", "workflow_escalations", "course_approval_policies", "course_approval_revisions", "course_approval_requests", "course_approval_reviewers", "course_review_attempts", "course_review_attempt_events"):
        _tenant_table(name)
    op.execute("""
        CREATE FUNCTION enforce_course_approval_tenant_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE owner_tenant uuid;
        BEGIN
            IF TG_TABLE_NAME = 'course_approval_policies' THEN
                SELECT tenant_id INTO owner_tenant FROM courses WHERE id = NEW.course_id;
            ELSIF TG_TABLE_NAME = 'course_approval_revisions' THEN
                SELECT tenant_id INTO owner_tenant FROM courses WHERE id = NEW.course_id;
            ELSIF TG_TABLE_NAME = 'course_approval_requests' THEN
                SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.revision_id;
            ELSIF TG_TABLE_NAME = 'course_approval_reviewers' THEN
                SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.revision_id;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'course approval reviewer tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.reviewer_user_id;
            ELSIF TG_TABLE_NAME = 'course_review_attempts' THEN
                SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.revision_id;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'course review attempt tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.reviewer_user_id;
            ELSIF TG_TABLE_NAME = 'course_review_attempt_events' THEN
                SELECT tenant_id INTO owner_tenant FROM course_review_attempts WHERE id = NEW.attempt_id;
            ELSIF TG_TABLE_NAME = 'workflow_work_items' THEN
                IF NEW.review_revision_id IS NOT NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.review_revision_id;
                ELSIF NEW.enrollment_id IS NOT NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM enrollments WHERE id = NEW.enrollment_id;
                END IF;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'workflow work item tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                IF NEW.target_user_id IS NOT NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.target_user_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'workflow_access_credentials' THEN
                SELECT tenant_id INTO owner_tenant FROM workflow_work_items WHERE id = NEW.work_item_id;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'workflow credential tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.reviewer_user_id;
            ELSE
                SELECT tenant_id INTO owner_tenant FROM workflow_work_items WHERE id = NEW.work_item_id;
            END IF;
            IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                RAISE EXCEPTION 'course approval tenant ownership mismatch' USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END $$;
    """)
    for name in ("course_approval_policies", "course_approval_revisions", "course_approval_requests", "course_approval_reviewers", "course_review_attempts", "course_review_attempt_events", "workflow_work_items", "workflow_deliveries", "workflow_access_credentials", "workflow_reminders", "workflow_escalations"):
        op.execute(f"CREATE TRIGGER {name}_tenant_integrity BEFORE INSERT OR UPDATE ON {name} FOR EACH ROW EXECUTE FUNCTION enforce_course_approval_tenant_integrity()")
    op.create_index("uq_workflow_access_active_item", "workflow_access_credentials", ["work_item_id"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.execute("""CREATE FUNCTION lookup_course_review_tenant_by_token(access_token_hash text) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$ SELECT tenant_id FROM workflow_access_credentials WHERE token_hash = access_token_hash AND revoked_at IS NULL AND expires_at > now() LIMIT 1 $$""")
    op.execute("REVOKE ALL ON FUNCTION lookup_course_review_tenant_by_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_course_review_tenant_by_token(text) TO lms_app")
    op.execute("""CREATE FUNCTION prevent_course_approval_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.snapshot IS DISTINCT FROM OLD.snapshot OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256 OR NEW.source_fingerprint IS DISTINCT FROM OLD.source_fingerprint OR NEW.revision_number IS DISTINCT FROM OLD.revision_number OR NEW.course_id IS DISTINCT FROM OLD.course_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN RAISE EXCEPTION 'Course approval revision identity is immutable' USING ERRCODE='check_violation'; END IF; RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER course_approval_revision_immutable BEFORE UPDATE ON course_approval_revisions FOR EACH ROW EXECUTE FUNCTION prevent_course_approval_revision_mutation()")


def downgrade() -> None:
    for name in ("course_approval_policies", "course_approval_revisions", "course_approval_requests", "course_approval_reviewers", "course_review_attempts", "course_review_attempt_events", "workflow_work_items", "workflow_deliveries", "workflow_access_credentials", "workflow_reminders", "workflow_escalations"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}_tenant_integrity ON {name}")
    op.execute("DROP FUNCTION IF EXISTS enforce_course_approval_tenant_integrity()")
    op.execute("DROP FUNCTION IF EXISTS lookup_course_review_tenant_by_token(text)")
    op.execute("DROP TRIGGER IF EXISTS course_approval_revision_immutable ON course_approval_revisions")
    op.execute("DROP FUNCTION IF EXISTS prevent_course_approval_revision_mutation()")
    op.drop_index("uq_workflow_access_active_item", table_name="workflow_access_credentials")
    for name in ("workflow_escalations", "workflow_reminders", "workflow_access_credentials", "workflow_deliveries", "workflow_work_items", "course_review_attempt_events", "course_review_attempts", "course_approval_reviewers", "course_approval_requests", "course_approval_revisions", "course_approval_policies"):
        op.execute(f"DROP POLICY IF EXISTS {name}_tenant ON {name}")
        op.drop_table(name)
