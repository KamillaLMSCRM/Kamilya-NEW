"""Reconcile production schema drift (2026-06-30)

This migration was created after the 2026-06-30 smoke-test discovered
the production DB has drifted from the migration chain (e.g.
`certificates.cert_number` instead of `certificate_number`).

The drift was already manually reconciled via the asyncpg script in
`apps/api/.check_db.py` (rename `cert_number` -> `certificate_number`,
add `expires_at` / `pdf_path` / `metadata` columns, copy `pdf_url` into
`pdf_path`).

This migration makes the manual fix durable: when Render next runs
`alembic upgrade head`, this migration will run and the IF NOT EXISTS
guards ensure no-op if production is already up-to-date. Any future
environment (preview, staging) will get the right schema from scratch.

Bug 2 (`UserCreate has no attribute tenant_id`) and Bug 3 (telegram
webhook accepts unauthenticated traffic) are code-side, not schema,
and tracked separately in the smoke report doc.

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-30
"""
import sqlalchemy as sa

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename cert_number -> certificate_number if it exists.
    #    Postgres RENAME COLUMN is non-destructive; no data loss.
    #    The DO block makes the migration safe in environments
    #    where the rename has already happened (skip) or where the
    #    table was created via a different path (rename happens).
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'certificates'
                  AND column_name = 'cert_number'
              ) THEN
                ALTER TABLE certificates
                  RENAME COLUMN cert_number TO certificate_number;
              END IF;
            END$$;
            """
        )
    )

    # 2. Ensure the columns the model expects exist.
    op.execute(sa.text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS certificate_number VARCHAR(50)"))
    op.execute(sa.text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE"))
    op.execute(sa.text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS pdf_path TEXT"))
    op.execute(sa.text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS metadata JSONB"))

    # 3. Unique index on certificate_number.
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_certificates_certificate_number "
            "ON certificates (certificate_number)"
        )
    )

    # 4. Backfill pdf_path from pdf_url (legacy data had pdf_url).
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'certificates'
                  AND column_name = 'pdf_url'
              ) THEN
                UPDATE certificates SET pdf_path = pdf_url
                WHERE pdf_path IS NULL AND pdf_url IS NOT NULL;
              END IF;
            END$$;
            """
        )
    )

    # 5. Positions.created_at safety net (0037 had the FAILED-on-startup
    #    log; we cannot be sure it actually ran in production).
    op.execute(sa.text("ALTER TABLE positions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE"))
    op.execute(sa.text("ALTER TABLE positions ALTER COLUMN created_at SET DEFAULT now()"))
    op.execute(
        sa.text(
            "UPDATE positions SET created_at = now() WHERE created_at IS NULL"
        )
    )


def downgrade() -> None:
    # Downgrade intentionally does NOT drop certificate_number or
    # positions.created_at — those columns are part of the model and
    # dropping them would break the application. This is a one-way
    # safety net.
    pass
