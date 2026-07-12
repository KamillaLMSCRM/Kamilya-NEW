"""Allow the canonical methodologist learning-content role.

The application and ADRs have supported both `teacher` and `methodologist`,
but the original database check constraints only allowed `teacher`. This made
some valid demo and invitation flows fail at INSERT time and made route-level
role declarations inconsistent.
"""
from alembic import op


revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


_ROLES = "'superadmin', 'admin', 'org_admin', 'methodologist', 'teacher', 'student'"


def upgrade() -> None:
    for table, constraint in (("users", "ck_user_role"), ("user_roles", "ck_user_role_role")):
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = '{constraint}'
                      AND conrelid = '{table}'::regclass
                ) THEN
                    ALTER TABLE {table} DROP CONSTRAINT {constraint};
                END IF;
                ALTER TABLE {table} ADD CONSTRAINT {constraint}
                    CHECK (role IN ({_ROLES}));
            END $$;
        """)


def downgrade() -> None:
    op.drop_constraint("ck_user_role_role", "user_roles", type_="check")
    op.create_check_constraint(
        "ck_user_role_role",
        "user_roles",
        "role IN ('superadmin', 'admin', 'org_admin', 'teacher', 'student')",
    )
    op.drop_constraint("ck_user_role", "users", type_="check")
    op.create_check_constraint(
        "ck_user_role",
        "users",
        "role IN ('superadmin', 'admin', 'org_admin', 'teacher', 'student')",
    )
