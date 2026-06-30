"""Reconcile production schema drift (2026-06-30)

On 2026-06-30 the public cert verify endpoint
`GET /api/v1/certificates/verify/{number}` returned 500 with
"column certificates.certificate_number does not exist" in
production. The model in `app/modules/certificates/models.py`
defines the column, and the migration 0005_add_quiz_attempts_certificates.py
also creates it, but the column is missing in the production DB.

Hypothesis: the 0005 migration either never ran on prod (alembic
state out of sync) or it ran with a partial failure (table created
without the column). We do not have direct DB access from this
session to confirm — Render log only shows "alembic FAILED" on
every restart but the underlying root cause is hidden.

Rather than diagnose the migration chain, this patch migration
idempotently adds the missing column. IF NOT EXISTS on ADD COLUMN
is Postgres-native (9.6+) and safe to re-run.

Apply the same safety net to:
  - certificates.certificate_number  (Bug 1, smoke 2026-06-30)
  - positions.created_at             (re-confirms 0037; the alembic
                                       FAILED on every restart so we
                                       cannot be sure 0037 actually ran)

Bug 2 (`UserCreate has no attribute tenant_id`) and Bug 3 (telegram
webhook accepts unauthenticated traffic) are code-side, not schema,
and tracked separately in the smoke report doc.

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent column adds. Postgres ADD COLUMN IF NOT EXISTS exists
    # since 9.6; the prod Supabase Postgres is 15+. Safe to re-run.
    op.execute(
        sa.text(
            "ALTER TABLE certificates "
            "ADD COLUMN IF NOT EXISTS certificate_number VARCHAR(50)"
        )
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_certificates_certificate_number "
            "ON certificates (certificate_number)"
        )
    )

    op.execute(
        sa.text(
            "ALTER TABLE positions "
            "ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE positions "
            "ALTER COLUMN created_at SET DEFAULT now()"
        )
    )

    # The smoke also surfaced 0 certificates in production, so we
    # cannot backfill any data. But we DO want to backfill positions
    # in case 0037 never ran (its FAILED-on-startup status means it
    # might be a no-op in prod). Mirroring 0037's logic but as a
    # pure safety net — won't overwrite non-NULL values.
    op.execute(
        sa.text(
            """
            UPDATE positions AS p
            SET created_at = COALESCE(p.created_at, now())
            WHERE p.created_at IS NULL
            """
        )
    )


def downgrade() -> None:
    # Downgrade intentionally does NOT drop certificate_number or
    # positions.created_at — those columns are part of the model and
    # dropping them would break the application. This is a one-way
    # safety net.
    pass
