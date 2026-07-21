"""Ensure every tenant user's primary role is an assigned role.

Revision ID: 0067
Revises: 0066
"""

from alembic import op


revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO user_roles (id, user_id, tenant_id, role)
        SELECT gen_random_uuid(), u.id, u.tenant_id, u.role
        FROM users AS u
        WHERE u.tenant_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM user_roles AS ur
            WHERE ur.user_id = u.id
              AND ur.tenant_id = u.tenant_id
              AND ur.role = u.role
          )
        """
    )


def downgrade() -> None:
    # These rows represent valid primary-role assignments and must not be
    # deleted on downgrade.
    pass
