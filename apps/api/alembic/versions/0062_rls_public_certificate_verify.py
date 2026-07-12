"""Allow exact-number public certificate verification under RLS.

Revision ID: 0062
Revises: 0061
"""

from alembic import op


revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS certificates_public_verify ON certificates")
    op.execute(
        """
        CREATE POLICY certificates_public_verify ON certificates
        FOR SELECT TO lms_app
        USING (current_setting('app.public_certificate_lookup', true) = 'true')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS certificates_public_verify ON certificates")
