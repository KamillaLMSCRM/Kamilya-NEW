"""add role, is_active, position_id, last_login to users

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def column_exists(bind, table, column):
    result = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c)"),
        {"t": table, "c": column},
    )
    return result.scalar()


def upgrade() -> None:
    bind = op.get_bind()

    # Add role column
    if not column_exists(bind, "users", "role"):
        bind.execute(sa.text("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"))
        bind.execute(sa.text("ALTER TABLE users ADD CONSTRAINT ck_user_role CHECK (role IN ('superadmin', 'admin', 'org_admin', 'teacher', 'student'))"))

    # Add is_active column
    if not column_exists(bind, "users", "is_active"):
        bind.execute(sa.text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true"))

    # Add position_id column
    if not column_exists(bind, "users", "position_id"):
        bind.execute(sa.text("ALTER TABLE users ADD COLUMN position_id UUID REFERENCES positions(id) ON DELETE SET NULL"))

    # Add last_login column
    if not column_exists(bind, "users", "last_login"):
        bind.execute(sa.text("ALTER TABLE users ADD COLUMN last_login TIMESTAMPTZ"))

    # Sync role from user_roles table where user_roles has data
    bind.execute(sa.text("""
        UPDATE users SET role = ur.role
        FROM user_roles ur
        WHERE users.id = ur.user_id AND users.tenant_id = ur.tenant_id
    """))

    # Sync is_active from status
    bind.execute(sa.text("UPDATE users SET is_active = (status = 'active') WHERE status IS NOT NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    for col in ["last_login", "position_id", "is_active", "role"]:
        if column_exists(bind, "users", col):
            bind.execute(sa.text(f"ALTER TABLE users DROP COLUMN {col}"))
