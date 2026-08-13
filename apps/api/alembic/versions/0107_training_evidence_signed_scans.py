"""Append returned hand-signed copies to training evidence.

Revision ID: 0107
Revises: 0106
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "training_evidence_signed_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_evidence_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="received"),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("storage_key", name="uq_training_evidence_signed_scans_storage_key"),
        sa.CheckConstraint("status = 'received'", name="ck_training_evidence_signed_scans_received"),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png')",
            name="ck_training_evidence_signed_scans_content_type",
        ),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="ck_training_evidence_signed_scans_size"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_training_evidence_signed_scans_sha256"),
        sa.CheckConstraint(
            "length(original_filename) BETWEEN 1 AND 255", name="ck_training_evidence_signed_scans_filename"
        ),
        sa.CheckConstraint("length(storage_key) > 0", name="ck_training_evidence_signed_scans_storage_key"),
    )
    op.create_index(
        "ix_training_evidence_signed_scans_tenant_event_uploaded",
        "training_evidence_signed_scans",
        ["tenant_id", "event_id", "uploaded_at"],
    )

    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_signed_scan_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE event_tenant uuid;
        DECLARE event_user uuid;
        DECLARE event_enrollment uuid;
        DECLARE enrollment_tenant uuid;
        DECLARE enrollment_user uuid;
        DECLARE uploader_tenant uuid;
        BEGIN
            SELECT tenant_id, user_id, enrollment_id
              INTO event_tenant, event_user, event_enrollment
              FROM training_evidence_events WHERE id=NEW.event_id;
            IF event_tenant IS NULL OR event_tenant <> NEW.tenant_id
               OR event_user <> NEW.user_id OR event_enrollment <> NEW.enrollment_id THEN
                RAISE EXCEPTION 'signed scan event tenant ownership mismatch'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            SELECT tenant_id, user_id INTO enrollment_tenant, enrollment_user
              FROM enrollments WHERE id=NEW.enrollment_id;
            IF enrollment_tenant IS NULL OR enrollment_tenant <> NEW.tenant_id
               OR enrollment_user <> NEW.user_id THEN
                RAISE EXCEPTION 'signed scan enrollment tenant ownership mismatch'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            SELECT tenant_id INTO uploader_tenant FROM users WHERE id=NEW.uploaded_by_user_id;
            IF uploader_tenant IS NULL OR uploader_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'signed scan uploader must belong to the event tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_training_evidence_signed_scan_ownership
        BEFORE INSERT OR UPDATE ON training_evidence_signed_scans
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_signed_scan_ownership()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_training_evidence_signed_scan_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND training_evidence_retention_purge_authorized() THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Returned signed scans are append-only'
                USING ERRCODE = 'check_violation';
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prevent_training_evidence_signed_scan_mutation
        BEFORE UPDATE OR DELETE ON training_evidence_signed_scans
        FOR EACH ROW EXECUTE FUNCTION prevent_training_evidence_signed_scan_mutation()
        """
    )

    op.execute("ALTER TABLE training_evidence_signed_scans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE training_evidence_signed_scans FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_training_evidence_signed_scans_isolation "
        "ON training_evidence_signed_scans FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("REVOKE ALL ON TABLE training_evidence_signed_scans FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT ON training_evidence_signed_scans TO lms_app")


def downgrade() -> None:
    # A returned copy is append-only evidence. Refuse a destructive downgrade
    # while any row exists, rather than silently deleting customer records.
    op.execute("ALTER TABLE training_evidence_signed_scans NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM training_evidence_signed_scans LIMIT 1) THEN
            RAISE EXCEPTION
              '0107 downgrade refused: returned signed scans exist; archive them under the approved retention procedure before downgrade';
          END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE training_evidence_signed_scans FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_prevent_training_evidence_signed_scan_mutation ON training_evidence_signed_scans"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_training_evidence_signed_scan_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_validate_training_evidence_signed_scan_ownership ON training_evidence_signed_scans"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_signed_scan_ownership()")
    op.execute(
        "DROP POLICY IF EXISTS tenant_training_evidence_signed_scans_isolation ON training_evidence_signed_scans"
    )
    op.drop_index(
        "ix_training_evidence_signed_scans_tenant_event_uploaded", table_name="training_evidence_signed_scans"
    )
    op.drop_table("training_evidence_signed_scans")
