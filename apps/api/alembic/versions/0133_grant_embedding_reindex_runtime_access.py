"""Grant the runtime role access to embedding reindex lifecycle tables.

Revision ID: 0133
Revises: 0132
Create Date: 2026-08-27
"""

from alembic import op


revision = "0133"
down_revision = "0132"
branch_labels = None
depends_on = None


TABLES = (
    "embedding_active_revisions",
    "embedding_reindex_runs",
    "embedding_reindex_events",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC, lms_app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"REVOKE ALL ON TABLE {table} FROM lms_app")
