"""Add tenant-scoped immutable training-evidence share links.

Revision ID: 0087
Revises: 0086
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "training_evidence_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_sha256", sa.Text(), nullable=False),
        sa.Column("package_format", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("public_filename", sa.Text(), nullable=False),
        sa.Column("package_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("package_sha256", sa.Text(), nullable=False),
        sa.Column("source_event_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_downloads", sa.Integer(), nullable=False),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_sha256", name="uq_training_evidence_shares_token_sha256"),
        sa.CheckConstraint("package_format IN ('zip', 'pdf')", name="ck_training_evidence_shares_format"),
        sa.CheckConstraint("max_downloads BETWEEN 1 AND 100", name="ck_training_evidence_shares_max_downloads"),
        sa.CheckConstraint("download_count >= 0 AND download_count <= max_downloads", name="ck_training_evidence_shares_download_count"),
        sa.CheckConstraint("length(token_sha256) = 64", name="ck_training_evidence_shares_token_hash"),
        sa.CheckConstraint("length(package_sha256) = 64", name="ck_training_evidence_shares_package_hash"),
    )
    op.create_index(
        "ix_training_evidence_shares_tenant_created",
        "training_evidence_shares",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_training_evidence_shares_tenant_expires",
        "training_evidence_shares",
        ["tenant_id", "expires_at"],
    )

    op.create_table(
        "training_evidence_share_access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "share_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_evidence_shares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("download_count_after", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "outcome IN ('downloaded', 'rejected_revoked', 'rejected_expired', 'rejected_exhausted', 'rejected_integrity')",
            name="ck_training_evidence_share_access_outcome",
        ),
    )
    op.create_index(
        "ix_training_evidence_share_access_logs_tenant_share",
        "training_evidence_share_access_logs",
        ["tenant_id", "share_id", "occurred_at"],
    )

    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_share_ownership()
        RETURNS trigger AS $$
        DECLARE creator_tenant uuid;
        BEGIN
            SELECT tenant_id INTO creator_tenant FROM users WHERE id = NEW.created_by_user_id;
            IF creator_tenant IS NULL OR creator_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Evidence share creator must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_shares_validate_ownership
        BEFORE INSERT OR UPDATE ON training_evidence_shares
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_share_ownership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_share_access_tenant()
        RETURNS trigger AS $$
        DECLARE share_tenant uuid;
        BEGIN
            SELECT tenant_id INTO share_tenant FROM training_evidence_shares WHERE id = NEW.share_id;
            IF share_tenant IS NULL OR share_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Evidence share access must belong to the share tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_share_access_validate_tenant
        BEFORE INSERT OR UPDATE ON training_evidence_share_access_logs
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_share_access_tenant();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_training_evidence_share_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.token_sha256 IS DISTINCT FROM OLD.token_sha256
               OR NEW.package_format IS DISTINCT FROM OLD.package_format
               OR NEW.content_type IS DISTINCT FROM OLD.content_type
               OR NEW.public_filename IS DISTINCT FROM OLD.public_filename
               OR NEW.package_bytes IS DISTINCT FROM OLD.package_bytes
               OR NEW.package_sha256 IS DISTINCT FROM OLD.package_sha256
               OR NEW.source_event_ids IS DISTINCT FROM OLD.source_event_ids
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.max_downloads IS DISTINCT FROM OLD.max_downloads
               OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Immutable evidence share fields cannot be changed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_shares_immutable
        BEFORE UPDATE ON training_evidence_shares
        FOR EACH ROW EXECUTE FUNCTION prevent_training_evidence_share_mutation();
        """
    )

    for table in ("training_evidence_shares", "training_evidence_share_access_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_{table}_isolation ON {table} "
            f"FOR ALL TO lms_app USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
        )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON training_evidence_shares TO lms_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON training_evidence_share_access_logs TO lms_app"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS training_evidence_shares_immutable ON training_evidence_shares")
    op.execute("DROP FUNCTION IF EXISTS prevent_training_evidence_share_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS training_evidence_share_access_validate_tenant "
        "ON training_evidence_share_access_logs"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_share_access_tenant()")
    op.execute("DROP TRIGGER IF EXISTS training_evidence_shares_validate_ownership ON training_evidence_shares")
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_share_ownership()")
    for table in ("training_evidence_share_access_logs", "training_evidence_shares"):
        op.execute(f"DROP POLICY IF EXISTS tenant_{table}_isolation ON {table}")
    op.drop_index(
        "ix_training_evidence_share_access_logs_tenant_share",
        table_name="training_evidence_share_access_logs",
    )
    op.drop_table("training_evidence_share_access_logs")
    op.drop_index("ix_training_evidence_shares_tenant_expires", table_name="training_evidence_shares")
    op.drop_index("ix_training_evidence_shares_tenant_created", table_name="training_evidence_shares")
    op.drop_table("training_evidence_shares")
