"""Bounded bootstrap reads and own-ID tenant isolation.

Expand bootstrap functions, deploy compatible callers, then restrict tenants.
Never roll back to broad service_access or an incompatible API.
"""

import re

from alembic import op
from app.core.tenant_bootstrap_migration import install_bootstrap as _install_bootstrap

revision = "0172"
down_revision = "0171"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe tenants schema")
    return schema


def install_bootstrap() -> None:
    """Expand-only phase; NOT a completed migration or isolation activation."""
    _install_bootstrap(_schema(), op.execute)


def upgrade() -> None:
    install_bootstrap()
    table = f'"{_schema()}".tenants'
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS service_access ON {table}")
    op.execute(f"DROP POLICY IF EXISTS tenants_own_context ON {table}")
    op.execute(f"""
        CREATE POLICY tenants_own_context ON {table} FOR ALL TO lms_app
        USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    raise RuntimeError("0172 isolation is roll-forward only; broad tenants policy must not be restored")
