"""Make the runtime audit and privacy-processing ledger append-only.

Revision ID: 0168
Revises: 0167
Create Date: 2026-09-29

Tenant deletion remains owned by the bounded SECURITY DEFINER purge function
introduced in migrations 0148/0149.  Ordinary ``lms_app`` sessions may append
and read audit records but may neither rewrite nor delete them.
"""

from alembic import op

revision = "0168"
down_revision = "0167"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM lms_app")


def downgrade() -> None:
    # Migration 0147 already made DELETE unavailable to lms_app.  Restore only
    # the pre-0168 UPDATE privilege so a downgrade does not weaken that guard.
    op.execute("GRANT UPDATE ON audit_logs TO lms_app")
