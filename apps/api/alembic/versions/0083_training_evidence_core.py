"""Add append-only training procedure evidence core.

Revision ID: 0083
Revises: 0082
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "training_evidence_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("enrollments.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("content_release_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_releases.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("procedure_type", sa.Text(), nullable=False),
        sa.Column("source_event_key", sa.Text(), nullable=True),
        sa.Column("record_type", sa.Text(), nullable=False, server_default="original"),
        sa.Column("related_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("training_evidence_events.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "procedure_type IN ('acknowledgement', 'training', 'knowledge_check', 'internal_attestation', 'admission_decision')",
            name="ck_training_evidence_event_procedure_type",
        ),
        sa.CheckConstraint(
            "record_type IN ('original', 'correction', 'revocation')",
            name="ck_training_evidence_event_record_type",
        ),
        sa.CheckConstraint(
            "(record_type = 'original' AND related_event_id IS NULL AND reason IS NULL) OR (record_type IN ('correction', 'revocation') AND related_event_id IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_training_evidence_event_relation",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_evidence_event_sha256",
        ),
        sa.CheckConstraint(
            "source_event_key IS NULL OR length(btrim(source_event_key)) > 0",
            name="ck_training_evidence_event_source_key",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_event_key",
            name="uq_training_evidence_events_tenant_source_key",
        ),
    )
    for name, columns in (
        ("ix_training_evidence_events_tenant_id", ["tenant_id"]),
        ("ix_training_evidence_events_user_id", ["user_id"]),
        ("ix_training_evidence_events_enrollment_id", ["enrollment_id"]),
        ("ix_training_evidence_events_release_id", ["content_release_id"]),
        ("ix_training_evidence_events_related_id", ["related_event_id"]),
        ("ix_training_evidence_events_occurred_at", ["tenant_id", "occurred_at"]),
    ):
        op.create_index(name, "training_evidence_events", columns)

    op.create_table(
        "training_evidence_step_up_confirmations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("training_evidence_events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("object_version", sa.Text(), nullable=False),
        sa.Column("reauth_method", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("confirmation_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("length(btrim(action_text)) > 0", name="ck_training_evidence_confirmation_action"),
        sa.CheckConstraint("length(btrim(object_version)) > 0", name="ck_training_evidence_confirmation_version"),
        sa.CheckConstraint("reauth_method IN ('email_otp', 'telegram', 'sso', 'password')", name="ck_training_evidence_confirmation_method"),
        sa.CheckConstraint("confirmation_sha256 ~ '^[0-9a-f]{64}$'", name="ck_training_evidence_confirmation_sha256"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "user_id",
            name="uq_training_evidence_confirmation_subject",
        ),
    )
    op.create_index("ix_training_evidence_confirmations_tenant_event", "training_evidence_step_up_confirmations", ["tenant_id", "event_id"])

    op.create_table(
        "training_evidence_legal_holds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("training_evidence_events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("acted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("action IN ('placed', 'released')", name="ck_training_evidence_hold_action"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_training_evidence_hold_reason"),
        sa.CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_training_evidence_hold_sha256"),
    )
    op.create_index("ix_training_evidence_holds_tenant_event", "training_evidence_legal_holds", ["tenant_id", "event_id"])

    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_ownership()
        RETURNS trigger AS $$
        DECLARE target_tenant uuid;
        DECLARE target_user uuid;
        DECLARE enrollment_course uuid;
        DECLARE release_course uuid;
        DECLARE release_tenant uuid;
        DECLARE related_tenant uuid;
        DECLARE recorder_tenant uuid;
        BEGIN
            SELECT tenant_id INTO target_tenant FROM users WHERE id = NEW.user_id;
            IF target_tenant IS NULL OR target_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Evidence user must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF NEW.recorded_by_user_id IS NOT NULL THEN
                SELECT tenant_id INTO recorder_tenant FROM users WHERE id = NEW.recorded_by_user_id;
                IF recorder_tenant IS NULL OR recorder_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Evidence recorder must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            IF NEW.enrollment_id IS NOT NULL THEN
                SELECT tenant_id, user_id, course_id INTO target_tenant, target_user, enrollment_course FROM enrollments WHERE id = NEW.enrollment_id;
                IF target_tenant IS NULL OR target_tenant <> NEW.tenant_id OR target_user <> NEW.user_id THEN
                    RAISE EXCEPTION 'Evidence enrollment must belong to the same tenant and user' USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            IF NEW.content_release_id IS NOT NULL THEN
                SELECT tenant_id, course_id INTO release_tenant, release_course FROM content_releases WHERE id = NEW.content_release_id;
                IF release_tenant IS NULL OR release_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Evidence content release must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
                END IF;
                IF NEW.enrollment_id IS NOT NULL AND enrollment_course <> release_course THEN
                    RAISE EXCEPTION 'Evidence release must match enrollment course' USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            IF NEW.related_event_id IS NOT NULL THEN
                SELECT tenant_id INTO related_tenant FROM training_evidence_events WHERE id = NEW.related_event_id;
                IF related_tenant IS NULL OR related_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Related evidence must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_events_validate_ownership
        BEFORE INSERT ON training_evidence_events
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_ownership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_training_evidence_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1 FROM training_evidence_legal_holds h
                WHERE h.event_id = OLD.id AND h.action = 'placed'
                  AND NOT EXISTS (
                    SELECT 1 FROM training_evidence_legal_holds r
                    WHERE r.event_id = OLD.id AND r.action = 'released' AND r.occurred_at > h.occurred_at
                  )
            ) THEN
                RAISE EXCEPTION 'Legal hold blocks deletion of training evidence' USING ERRCODE = 'check_violation';
            END IF;
            RAISE EXCEPTION 'Training evidence events are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_events_prevent_mutation
        BEFORE UPDATE OR DELETE ON training_evidence_events
        FOR EACH ROW EXECUTE FUNCTION prevent_training_evidence_event_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_confirmation_ownership()
        RETURNS trigger AS $$
        DECLARE event_tenant uuid;
        DECLARE event_user uuid;
        DECLARE user_tenant uuid;
        BEGIN
            SELECT tenant_id, user_id INTO event_tenant, event_user FROM training_evidence_events WHERE id = NEW.event_id;
            SELECT tenant_id INTO user_tenant FROM users WHERE id = NEW.user_id;
            IF event_tenant IS NULL OR event_tenant <> NEW.tenant_id OR event_user <> NEW.user_id OR user_tenant IS NULL OR user_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Confirmation event, subject and user must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_confirmations_validate_ownership
        BEFORE INSERT ON training_evidence_step_up_confirmations
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_confirmation_ownership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_training_evidence_confirmation_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Step-up confirmations are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_confirmations_prevent_mutation
        BEFORE UPDATE OR DELETE ON training_evidence_step_up_confirmations
        FOR EACH ROW EXECUTE FUNCTION prevent_training_evidence_confirmation_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_hold_ownership()
        RETURNS trigger AS $$
        DECLARE event_tenant uuid;
        DECLARE user_tenant uuid;
        BEGIN
            SELECT tenant_id INTO event_tenant FROM training_evidence_events WHERE id = NEW.event_id;
            SELECT tenant_id INTO user_tenant FROM users WHERE id = NEW.acted_by_user_id;
            IF event_tenant IS NULL OR event_tenant <> NEW.tenant_id OR user_tenant IS NULL OR user_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Legal hold event and actor must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_holds_validate_ownership
        BEFORE INSERT ON training_evidence_legal_holds
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_hold_ownership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_training_evidence_hold_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Legal hold records are append-only' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_holds_prevent_mutation
        BEFORE UPDATE OR DELETE ON training_evidence_legal_holds
        FOR EACH ROW EXECUTE FUNCTION prevent_training_evidence_hold_mutation();
        """
    )

    for table in ("training_evidence_events", "training_evidence_step_up_confirmations", "training_evidence_legal_holds"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} FOR ALL TO lms_app USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO lms_app")


def downgrade() -> None:
    for table in ("training_evidence_legal_holds", "training_evidence_step_up_confirmations", "training_evidence_events"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_holds_prevent_mutation ON training_evidence_legal_holds")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_holds_validate_ownership ON training_evidence_legal_holds")
    op.execute("DROP FUNCTION IF EXISTS prevent_training_evidence_hold_mutation()")
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_hold_ownership()")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_confirmations_prevent_mutation ON training_evidence_step_up_confirmations")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_confirmations_validate_ownership ON training_evidence_step_up_confirmations")
    op.execute("DROP FUNCTION IF EXISTS prevent_training_evidence_confirmation_mutation()")
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_confirmation_ownership()")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_events_prevent_mutation ON training_evidence_events")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_events_validate_ownership ON training_evidence_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_training_evidence_event_mutation()")
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_ownership()")
    op.drop_index("ix_training_evidence_holds_tenant_event", table_name="training_evidence_legal_holds")
    op.drop_table("training_evidence_legal_holds")
    op.drop_index("ix_training_evidence_confirmations_tenant_event", table_name="training_evidence_step_up_confirmations")
    op.drop_table("training_evidence_step_up_confirmations")
    for name in (
        "ix_training_evidence_events_occurred_at",
        "ix_training_evidence_events_related_id",
        "ix_training_evidence_events_release_id",
        "ix_training_evidence_events_enrollment_id",
        "ix_training_evidence_events_user_id",
        "ix_training_evidence_events_tenant_id",
    ):
        op.drop_index(name, table_name="training_evidence_events")
    op.drop_table("training_evidence_events")
