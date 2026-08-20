"""Persist immutable, tenant-scoped adaptive staff import sessions.

Revision ID: 0113
Revises: 0112
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "staff_import_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="uploaded", nullable=False),
        sa.Column("mode", sa.Text(), server_default="ADD_OR_UPDATE", nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("source_file_name", sa.Text(), nullable=False),
        sa.Column("source_file_sha256", sa.Text(), nullable=False),
        sa.Column("source_format", sa.Text(), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_object_key", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("workbook_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mapping_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("proposal_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("proposal_revision", sa.Text(), nullable=True),
        sa.Column("proposal_hash", sa.Text(), nullable=True),
        sa.Column("reviewed_revision", sa.Text(), nullable=True),
        sa.Column("approved_revision", sa.Text(), nullable=True),
        sa.Column("approval_token_hash", sa.Text(), nullable=True),
        sa.Column("full_reconciliation_confirmation", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN ('uploaded','inspecting','needs_mapping','needs_review','needs_correction','ready_for_approval','approved','committing','committed','rejected','expired','failed')", name="ck_staff_import_sessions_state"),
        sa.CheckConstraint("mode IN ('ADD_OR_UPDATE','FULL_RECONCILIATION')", name="ck_staff_import_sessions_mode"),
        sa.CheckConstraint("source_format IN ('xlsx','xls','csv')", name="ck_staff_import_sessions_source_format"),
        sa.CheckConstraint("source_size_bytes > 0", name="ck_staff_import_sessions_source_size"),
        sa.CheckConstraint("source_file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_staff_import_sessions_source_sha256"),
        sa.CheckConstraint("proposal_hash IS NULL OR proposal_hash ~ '^[0-9a-f]{64}$'", name="ck_staff_import_sessions_proposal_hash"),
        sa.CheckConstraint("(proposal_json IS NULL AND proposal_revision IS NULL AND proposal_hash IS NULL) OR (proposal_json IS NOT NULL AND proposal_revision IS NOT NULL AND proposal_hash IS NOT NULL)", name="ck_staff_import_sessions_proposal_snapshot"),
        sa.CheckConstraint("state NOT IN ('approved','committing','committed') OR (approved_revision IS NOT NULL AND approved_at IS NOT NULL)", name="ck_staff_import_sessions_approval_state"),
        sa.CheckConstraint("state <> 'committed' OR committed_at IS NOT NULL", name="ck_staff_import_sessions_commit_state"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mapping_id"], ["staff_import_mappings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_staff_import_sessions_tenant_idempotency"),
    )
    op.create_index("ix_staff_import_sessions_tenant_created", "staff_import_sessions", ["tenant_id", "created_at"])
    op.create_index("ix_staff_import_sessions_tenant_state", "staff_import_sessions", ["tenant_id", "state"])

    op.create_table(
        "staff_import_session_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(event_metadata) = 'object'", name="ck_staff_import_session_events_metadata"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["staff_import_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_staff_import_session_events_session_created", "staff_import_session_events", ["session_id", "created_at"])
    op.create_index("ix_staff_import_session_events_tenant_created", "staff_import_session_events", ["tenant_id", "created_at"])

    op.execute(
        r"""
        CREATE FUNCTION validate_staff_import_session_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE actor_tenant uuid;
        DECLARE mapping_tenant uuid;
        BEGIN
          SELECT tenant_id INTO actor_tenant FROM users WHERE id = NEW.actor_id;
          IF actor_tenant IS NULL OR actor_tenant <> NEW.tenant_id THEN
            RAISE EXCEPTION 'staff import actor tenant mismatch' USING ERRCODE='foreign_key_violation';
          END IF;
          IF NEW.mapping_id IS NOT NULL THEN
            SELECT tenant_id INTO mapping_tenant FROM staff_import_mappings WHERE id = NEW.mapping_id;
            IF mapping_tenant IS NULL OR mapping_tenant <> NEW.tenant_id THEN
              RAISE EXCEPTION 'staff import mapping tenant mismatch' USING ERRCODE='foreign_key_violation';
            END IF;
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.state IN ('approved','committing','committed') AND
             (NEW.proposal_json IS DISTINCT FROM OLD.proposal_json OR
              NEW.proposal_revision IS DISTINCT FROM OLD.proposal_revision OR
              NEW.proposal_hash IS DISTINCT FROM OLD.proposal_hash) THEN
            RAISE EXCEPTION 'approved staff import proposal is immutable' USING ERRCODE='check_violation';
          END IF;
          IF TG_OP = 'UPDATE' AND NEW.state IS DISTINCT FROM OLD.state AND NOT (
            (OLD.state = 'uploaded' AND NEW.state IN ('inspecting','failed','expired')) OR
            (OLD.state = 'inspecting' AND NEW.state IN ('needs_mapping','needs_review','needs_correction','ready_for_approval','failed','rejected','expired')) OR
            (OLD.state = 'needs_mapping' AND NEW.state IN ('needs_review','needs_correction','ready_for_approval','failed','rejected','expired')) OR
            (OLD.state = 'needs_review' AND NEW.state IN ('ready_for_approval','needs_correction','rejected','expired')) OR
            (OLD.state = 'needs_correction' AND NEW.state IN ('needs_review','ready_for_approval','rejected','expired')) OR
            (OLD.state = 'ready_for_approval' AND NEW.state IN ('approved','needs_correction','rejected','expired')) OR
            (OLD.state = 'approved' AND NEW.state IN ('committing','rejected','expired')) OR
            (OLD.state = 'committing' AND NEW.state IN ('committed','failed'))
          ) THEN
            RAISE EXCEPTION 'invalid staff import session state transition'
              USING ERRCODE='check_violation';
          END IF;
          NEW.updated_at := now();
          NEW.version := CASE WHEN TG_OP = 'UPDATE' THEN OLD.version + 1 ELSE NEW.version END;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_staff_import_session_ownership
        BEFORE INSERT OR UPDATE ON staff_import_sessions
        FOR EACH ROW EXECUTE FUNCTION validate_staff_import_session_ownership()
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION validate_staff_import_session_event_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE session_tenant uuid;
        DECLARE actor_tenant uuid;
        BEGIN
          SELECT tenant_id INTO session_tenant FROM staff_import_sessions WHERE id = NEW.session_id;
          SELECT tenant_id INTO actor_tenant FROM users WHERE id = NEW.actor_id;
          IF session_tenant IS NULL OR session_tenant <> NEW.tenant_id OR
             actor_tenant IS NULL OR actor_tenant <> NEW.tenant_id THEN
            RAISE EXCEPTION 'staff import event tenant mismatch' USING ERRCODE='foreign_key_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_staff_import_session_event_ownership
        BEFORE INSERT ON staff_import_session_events
        FOR EACH ROW EXECUTE FUNCTION validate_staff_import_session_event_ownership()
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION prevent_staff_import_session_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'staff import session events are append-only' USING ERRCODE='check_violation';
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prevent_staff_import_session_event_mutation
        BEFORE UPDATE OR DELETE ON staff_import_session_events
        FOR EACH ROW EXECUTE FUNCTION prevent_staff_import_session_event_mutation()
        """
    )

    for table in ("staff_import_sessions", "staff_import_session_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_{table}_isolation ON {table} FOR ALL TO lms_app "
            f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
        )
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON staff_import_sessions TO lms_app")
    op.execute("GRANT SELECT, INSERT ON staff_import_session_events TO lms_app")


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM staff_import_sessions LIMIT 1) THEN
            RAISE EXCEPTION '0113 downgrade refused: staff import audit records exist';
          END IF;
        END $$
        """
    )
    op.drop_table("staff_import_session_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_staff_import_session_event_mutation()")
    op.execute("DROP FUNCTION IF EXISTS validate_staff_import_session_event_ownership()")
    op.drop_table("staff_import_sessions")
    op.execute("DROP FUNCTION IF EXISTS validate_staff_import_session_ownership()")
