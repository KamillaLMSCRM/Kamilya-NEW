"""Restore runtime access required to replace cohort membership.

Revision ID: 0134
Revises: 0133
Create Date: 2026-08-28
"""

from alembic import op

revision = "0134"
down_revision = "0133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cohort membership is replaced as a bounded delete-and-insert operation.
    # RLS/FORCE RLS remains authoritative for tenant isolation.
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON TABLE cohort_members TO lms_app"
    )


def downgrade() -> None:
    # Migration 0060 already defines these privileges as part of the cohort
    # contract. Do not make a rollback less functional than that predecessor.
    pass
