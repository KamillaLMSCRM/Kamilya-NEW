"""Remove the duplicate org_admin tenant role.

Revision ID: 0074
Revises: 0073
"""

from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


CANONICAL_ROLES = "'superadmin', 'admin', 'methodologist', 'student'"
LEGACY_ROLES = "'superadmin', 'admin', 'org_admin', 'methodologist', 'student'"


def upgrade() -> None:
    # A multi-role account may already have both admin and org_admin. Remove
    # the duplicate first so the remaining org_admin rows can be renamed
    # without violating uq_user_role.
    op.execute(
        """
        DELETE FROM user_roles AS duplicate
        USING user_roles AS canonical
        WHERE duplicate.user_id = canonical.user_id
          AND duplicate.tenant_id = canonical.tenant_id
          AND duplicate.role = 'org_admin'
          AND canonical.role = 'admin'
        """
    )
    op.execute("UPDATE user_roles SET role = 'admin' WHERE role = 'org_admin'")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'org_admin'")
    op.execute("UPDATE user_invitations SET role = 'admin' WHERE role = 'org_admin'")

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
    # Downgrade restores schema compatibility only. There is no reliable
    # product distinction that would allow converted admins to be split back
    # into admin and org_admin.
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
