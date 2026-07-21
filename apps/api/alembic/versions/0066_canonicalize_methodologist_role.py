"""Use methodologist as the only learning-content role.

Revision ID: 0066
Revises: 0065
"""

from alembic import op


revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


CANONICAL_ROLES = "'superadmin', 'admin', 'org_admin', 'methodologist', 'student'"
LEGACY_ROLES = "'superadmin', 'admin', 'org_admin', 'methodologist', 'teacher', 'student'"


def upgrade() -> None:
    # Avoid the user-role unique constraint if a test account somehow has
    # both the old and canonical role records.
    op.execute(
        """
        DELETE FROM user_roles AS legacy
        USING user_roles AS canonical
        WHERE legacy.user_id = canonical.user_id
          AND legacy.tenant_id = canonical.tenant_id
          AND legacy.role = 'teacher'
          AND canonical.role = 'methodologist'
        """
    )
    op.execute("UPDATE user_roles SET role = 'methodologist' WHERE role = 'teacher'")
    op.execute("UPDATE users SET role = 'methodologist' WHERE role = 'teacher'")
    op.execute("UPDATE user_invitations SET role = 'methodologist' WHERE role = 'teacher'")

    op.drop_constraint("ck_user_role_role", "user_roles", type_="check")
    op.create_check_constraint(
        "ck_user_role_role",
        "user_roles",
        f"role IN ({CANONICAL_ROLES})",
    )
    op.drop_constraint("ck_user_role", "users", type_="check")
    op.create_check_constraint(
        "ck_user_role",
        "users",
        f"role IN ({CANONICAL_ROLES})",
    )


def downgrade() -> None:
    # Downgrade restores schema compatibility only. Converted users remain
    # methodologists because there is no reliable way to identify which ones
    # previously used the legacy name.
    op.drop_constraint("ck_user_role_role", "user_roles", type_="check")
    op.create_check_constraint(
        "ck_user_role_role",
        "user_roles",
        f"role IN ({LEGACY_ROLES})",
    )
    op.drop_constraint("ck_user_role", "users", type_="check")
    op.create_check_constraint(
        "ck_user_role",
        "users",
        f"role IN ({LEGACY_ROLES})",
    )
