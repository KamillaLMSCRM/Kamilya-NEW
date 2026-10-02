"""Permit exact superadmin tenant row locks, not updates, by the definer owner.

Revision ID: 0174
Revises: 0173

PostgreSQL applies UPDATE USING policies to SELECT FOR UPDATE as well. The
non-bypass function owner has SELECT bootstrap visibility but no UPDATE policy,
so the existing guarded purge helper incorrectly sees a missing tenant row.
WITH CHECK(false) still rejects any real UPDATE through this owner-only policy.
"""
from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision = "0174"
down_revision = "0173"
branch_labels = None
depends_on = None

POLICY = "tenants_purge_function_owner_lock"


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("Unsafe tenant purge lock identifier")
    return value


def _schema() -> str:
    return _identifier(op.get_context().opts.get("version_table_schema") or "public")


def lock_policy_sql(schema: str, owner_role: str) -> str:
    schema, owner_role = _identifier(schema), _identifier(owner_role)
    return f'''CREATE POLICY {POLICY} ON "{schema}".tenants
        FOR UPDATE TO "{owner_role}"
        USING (
            current_user = '{owner_role}'
            AND (session_user = 'lms_app' OR session_user = pg_catalog.pg_get_userbyid(
                (SELECT datdba FROM pg_catalog.pg_database
                 WHERE datname = pg_catalog.current_database())))
            AND current_setting('app.is_superadmin', true) = 'true'
            AND id::text = NULLIF(current_setting('app.tenant_id', true), '')
            AND slug <> 'kamilya'
        ) WITH CHECK (false)'''


def upgrade() -> None:
    schema = _schema()
    owner_role = op.get_bind().scalar(sa.text(
        "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database "
        "WHERE datname = pg_catalog.current_database()"
    ))
    op.execute(lock_policy_sql(schema, owner_role))


def downgrade() -> None:
    op.execute(f'DROP POLICY {POLICY} ON "{_schema()}".tenants')
