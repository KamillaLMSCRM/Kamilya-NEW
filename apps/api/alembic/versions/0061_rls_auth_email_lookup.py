"""Allow exact-email lookup during password authentication.

Revision ID: 0061
Revises: 0060
"""

from alembic import op


revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Login needs a narrowly-scoped lookup for legacy tenants whose slug does
    # not equal the user's email domain. The application enables this setting
    # only around the exact-email SELECT, then restores it immediately.
    op.execute("DROP POLICY IF EXISTS users_auth_email_lookup ON users")
    op.execute(
        """
        CREATE POLICY users_auth_email_lookup ON users
        FOR SELECT TO lms_app
        USING (current_setting('app.auth_lookup', true) = 'true')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_auth_email_lookup ON users")
