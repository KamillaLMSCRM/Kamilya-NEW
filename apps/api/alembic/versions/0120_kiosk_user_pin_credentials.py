"""Add tenant-scoped kiosk user PIN credentials.

Revision ID: 0120
Revises: 0119
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0120"
down_revision = "0119"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # Existing kiosk logs predate the masked-log contract. Scrub identifiers
    # in place before the new PIN flow can be released.
    op.execute(
        """
        UPDATE kiosk_access_logs
           SET personnel_number = CASE
               WHEN personnel_number IS NULL OR btrim(personnel_number) = '' THEN NULL
               WHEN length(btrim(personnel_number)) <= 2
                   THEN repeat('*', length(btrim(personnel_number)))
               ELSE repeat('*', length(btrim(personnel_number)) - 2)
                    || right(btrim(personnel_number), 2)
           END
        """
    )
    op.create_table(
        "kiosk_user_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "issued_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_kiosk_user_credential_tenant_user"),
        sa.CheckConstraint("failed_attempts BETWEEN 0 AND 5", name="ck_kiosk_user_credentials_attempts"),
    )
    op.create_index("ix_kiosk_user_credentials_tenant_id", "kiosk_user_credentials", ["tenant_id"])
    op.create_index("ix_kiosk_user_credentials_user_id", "kiosk_user_credentials", ["user_id"])

    op.execute(
        """
        CREATE FUNCTION validate_kiosk_user_credential_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        DECLARE learner_tenant uuid;
        DECLARE issuer_tenant uuid;
        DECLARE issuer_is_platform_superadmin boolean;
        BEGIN
            SELECT tenant_id INTO learner_tenant FROM users WHERE id = NEW.user_id;
            SELECT tenant_id, (role = 'superadmin' AND tenant_id IS NULL)
              INTO issuer_tenant, issuer_is_platform_superadmin
              FROM users WHERE id = NEW.issued_by;
            IF learner_tenant IS NULL OR learner_tenant <> NEW.tenant_id
               OR (
                   COALESCE(issuer_is_platform_superadmin, false) = false
                   AND (issuer_tenant IS NULL OR issuer_tenant <> NEW.tenant_id)
               ) THEN
                RAISE EXCEPTION 'kiosk credential tenant ownership mismatch'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_kiosk_user_credential_ownership
        BEFORE INSERT OR UPDATE ON kiosk_user_credentials
        FOR EACH ROW EXECUTE FUNCTION validate_kiosk_user_credential_ownership()
        """
    )
    op.execute("ALTER TABLE kiosk_user_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kiosk_user_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_kiosk_user_credentials_isolation "
        "ON kiosk_user_credentials FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute("REVOKE ALL ON TABLE kiosk_user_credentials FROM PUBLIC, lms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON kiosk_user_credentials TO lms_app")


def downgrade() -> None:
    op.execute("ALTER TABLE kiosk_user_credentials NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM kiosk_user_credentials LIMIT 1) THEN
            RAISE EXCEPTION
              '0120 downgrade refused: kiosk credentials exist; revoke and rotate access through an approved rollback procedure';
          END IF;
        END $$;
        """
    )
    op.execute("DROP POLICY IF EXISTS tenant_kiosk_user_credentials_isolation ON kiosk_user_credentials")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_validate_kiosk_user_credential_ownership ON kiosk_user_credentials"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_kiosk_user_credential_ownership()")
    op.drop_index("ix_kiosk_user_credentials_user_id", table_name="kiosk_user_credentials")
    op.drop_index("ix_kiosk_user_credentials_tenant_id", table_name="kiosk_user_credentials")
    op.drop_table("kiosk_user_credentials")
