"""Persist immutable public-registration legal acceptance evidence.

Revision ID: 0104
Revises: 0103
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_legal_acceptances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("privacy_consent_version", sa.Text(), nullable=False),
        sa.Column("privacy_consent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("privacy_consent_locale", sa.Text(), nullable=False),
        sa.Column("privacy_consent_surface", sa.Text(), nullable=False),
        sa.Column("terms_version", sa.Text(), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("privacy_consent_locale IN ('ru', 'kk', 'en')", name="ck_registration_legal_acceptance_locale"),
        sa.CheckConstraint(
            "privacy_consent_surface IN ('tenant_registration', 'telegram_registration')",
            name="ck_registration_legal_acceptance_surface",
        ),
    )
    op.execute("ALTER TABLE registration_legal_acceptances ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE registration_legal_acceptances FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON registration_legal_acceptances TO lms_app")
    op.execute(
        """
        CREATE POLICY registration_legal_acceptances_tenant_select
        ON registration_legal_acceptances FOR SELECT TO lms_app
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY registration_legal_acceptances_tenant_insert
        ON registration_legal_acceptances FOR INSERT TO lms_app
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_registration_legal_acceptance_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM users
            WHERE id=NEW.user_id AND tenant_id=NEW.tenant_id
          ) THEN
            RAISE EXCEPTION 'registration legal acceptance tenant ownership mismatch';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_registration_legal_acceptance_ownership
        BEFORE INSERT ON registration_legal_acceptances
        FOR EACH ROW EXECUTE FUNCTION validate_registration_legal_acceptance_ownership()
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE registration_legal_acceptances NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """DO $$ BEGIN IF EXISTS (
        SELECT 1 FROM registration_legal_acceptances
        ) THEN RAISE EXCEPTION
        '0104 downgrade refused: immutable registration legal acceptance evidence exists; archive it under the approved legal retention procedure before downgrade';
        END IF; END $$"""
    )
    op.execute("ALTER TABLE registration_legal_acceptances FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_validate_registration_legal_acceptance_ownership ON registration_legal_acceptances"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_registration_legal_acceptance_ownership()")
    op.drop_table("registration_legal_acceptances")
