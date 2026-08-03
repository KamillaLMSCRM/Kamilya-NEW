"""Add tenant-configurable training procedure definitions.

Revision ID: 0086
Revises: 0085
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "training_procedures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("procedure_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("approval_reference", sa.Text(), nullable=True),
        sa.Column("approval_date", sa.Date(), nullable=True),
        sa.Column("approved_by_name", sa.Text(), nullable=True),
        sa.Column("legal_basis", sa.Text(), nullable=True),
        sa.Column("local_basis", sa.Text(), nullable=True),
        sa.Column("confirmation_method", sa.Text(), nullable=False),
        sa.Column("retention_class", sa.Text(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("commission_snapshot_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("authorized_decision_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "code", "version", name="uq_training_procedures_tenant_code_version"),
        sa.CheckConstraint("version > 0", name="ck_training_procedures_version_positive"),
        sa.CheckConstraint("length(btrim(code)) > 0", name="ck_training_procedures_code_nonblank"),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9][a-z0-9._-]{0,99}$'",
            name="ck_training_procedures_code_format",
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_training_procedures_title_nonblank"),
        sa.CheckConstraint(
            "procedure_type IN ('acknowledgement', 'internal_attestation', 'admission_decision')",
            name="ck_training_procedures_type",
        ),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_training_procedures_status"),
        sa.CheckConstraint(
            "confirmation_method IN ('manual_record', 'email_otp')",
            name="ck_training_procedures_confirmation_method",
        ),
        sa.CheckConstraint(
            "retention_days IS NULL OR retention_days > 0",
            name="ck_training_procedures_retention_days_positive",
        ),
        sa.CheckConstraint(
            "status <> 'active' OR ("
            "approval_reference IS NOT NULL AND length(btrim(approval_reference)) > 0 AND "
            "approval_date IS NOT NULL AND "
            "approved_by_name IS NOT NULL AND length(btrim(approved_by_name)) > 0 AND "
            "(COALESCE(length(btrim(legal_basis)), 0) > 0 OR COALESCE(length(btrim(local_basis)), 0) > 0) AND "
            "retention_class IS NOT NULL AND length(btrim(retention_class)) > 0 AND "
            "retention_days IS NOT NULL AND retention_days > 0 AND "
            "(procedure_type <> 'internal_attestation' OR ("
            "commission_snapshot_rules IS NOT NULL AND "
            "commission_snapshot_rules ? 'members' AND "
            "commission_snapshot_rules ? 'quorum' AND "
            "commission_snapshot_rules ? 'decision_record')) AND "
            "(procedure_type <> 'admission_decision' OR ("
            "authorized_decision_rules IS NOT NULL AND "
            "authorized_decision_rules ? 'authority' AND "
            "authorized_decision_rules ? 'decision_record' AND "
            "authorized_decision_rules ? 'effective_date')))",
            name="ck_training_procedures_active_complete",
        ),
    )
    op.create_index("ix_training_procedures_tenant_status", "training_procedures", ["tenant_id", "status"])
    op.create_index("ix_training_procedures_tenant_type", "training_procedures", ["tenant_id", "procedure_type"])
    op.create_index(
        "uq_training_procedures_one_active_code",
        "training_procedures",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.execute(
        """
        CREATE FUNCTION validate_training_procedure_ownership()
        RETURNS trigger AS $$
        DECLARE creator_tenant uuid;
        DECLARE updater_tenant uuid;
        BEGIN
            SELECT tenant_id INTO creator_tenant FROM users WHERE id = NEW.created_by_user_id;
            SELECT tenant_id INTO updater_tenant FROM users WHERE id = NEW.updated_by_user_id;
            IF creator_tenant IS NULL OR creator_tenant <> NEW.tenant_id
               OR updater_tenant IS NULL OR updater_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Training procedure actors must belong to the same tenant' USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_procedures_validate_ownership
        BEFORE INSERT OR UPDATE ON training_procedures
        FOR EACH ROW EXECUTE FUNCTION validate_training_procedure_ownership();
        """
    )

    op.execute("ALTER TABLE training_procedures ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE training_procedures FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_training_procedures_isolation ON training_procedures "
        f"FOR ALL TO lms_app USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON training_procedures TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_training_procedures_isolation ON training_procedures")
    op.execute("DROP TRIGGER IF EXISTS training_procedures_validate_ownership ON training_procedures")
    op.execute("DROP FUNCTION IF EXISTS validate_training_procedure_ownership()")
    op.drop_index("uq_training_procedures_one_active_code", table_name="training_procedures")
    op.drop_index("ix_training_procedures_tenant_type", table_name="training_procedures")
    op.drop_index("ix_training_procedures_tenant_status", table_name="training_procedures")
    op.drop_table("training_procedures")
