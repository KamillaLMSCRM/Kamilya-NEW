"""Add a dedicated nullable editor-request idempotency fingerprint.

Revision ID: 0137
Revises: 0136
Create Date: 2026-08-30

Legacy and ordinary non-idempotent requests remain NULL. No fingerprint is
guessed or backfilled. New request-level create-or-reuse operations populate
the exact lowercase SHA-256 digest.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0137"
down_revision = "0136"
branch_labels = None
depends_on = None


REQUEST_TABLE = "ai_editor_requests"
FINGERPRINT_COLUMN = "request_fingerprint_sha256"
FINGERPRINT_CHECK = "ck_ai_editor_requests_fingerprint_sha256"


def upgrade() -> None:
    op.add_column(
        REQUEST_TABLE,
        sa.Column(FINGERPRINT_COLUMN, sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        FINGERPRINT_CHECK,
        REQUEST_TABLE,
        f"{FINGERPRINT_COLUMN} IS NULL OR "
        f"{FINGERPRINT_COLUMN} ~ '^[0-9a-f]{{64}}$'",
    )


def downgrade() -> None:
    op.drop_constraint(FINGERPRINT_CHECK, REQUEST_TABLE, type_="check")
    op.drop_column(REQUEST_TABLE, FINGERPRINT_COLUMN)
