"""Server-owned one-time assignment previews and atomic receipts.

Revision ID: 0169
Revises: 0168
"""

import re

from sqlalchemy import text

from alembic import op
from app.core.tenant_bootstrap_migration import install_bootstrap as _install_bootstrap

revision = "0169"
down_revision = "0168"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe workbench schema")
    return schema


def upgrade() -> None:
    _install_bootstrap(_schema(), op.execute)
    schema = _schema()
    table = f'"{schema}".workbench_assignment_plans'
    op.execute(f"""
        CREATE TABLE {table} (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            actor_id uuid NOT NULL,
            snapshot jsonb NOT NULL,
            preview jsonb NOT NULL,
            fingerprint varchar(64) NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{{64}}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'ready',
            receipt jsonb,
            CONSTRAINT ck_workbench_plan_status CHECK (status IN ('ready','succeeded')),
            CONSTRAINT ck_workbench_plan_receipt CHECK (
                (status='ready' AND receipt IS NULL) OR (status='succeeded' AND receipt IS NOT NULL)),
            CONSTRAINT ck_workbench_plan_owner_binding CHECK (COALESCE(
                snapshot->>'tenant_id'=tenant_id::text AND snapshot->>'actor_id'=actor_id::text
                AND snapshot->>'plan_id'=id::text AND preview->>'plan_id'=id::text
                AND preview->>'fingerprint'=fingerprint, false))
        )
    """)
    op.execute(f"CREATE INDEX ix_workbench_plan_owner_created ON {table}(tenant_id,actor_id,created_at)")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    owner = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    superadmin = "COALESCE(current_setting('app.is_superadmin',true),'false')='true'"
    eligible = f"""EXISTS (SELECT 1 FROM {schema}.users u
        WHERE u.id=workbench_assignment_plans.actor_id
          AND u.tenant_id=workbench_assignment_plans.tenant_id
          AND (u.role='methodologist' OR EXISTS (SELECT 1 FROM {schema}.user_roles r
              WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist'))
          AND u.is_active IS TRUE AND u.status='active')"""
    op.execute(
        f"CREATE POLICY workbench_plan_read ON {table} FOR SELECT TO lms_app USING ({tenant} AND ({owner} OR {superadmin}))"
    )
    op.execute(
        f"CREATE POLICY workbench_plan_insert ON {table} FOR INSERT TO lms_app WITH CHECK ({tenant} AND {owner} AND {eligible})"
    )
    op.execute(
        f"CREATE POLICY workbench_plan_update ON {table} FOR UPDATE TO lms_app USING ({tenant} AND {owner}) WITH CHECK ({tenant} AND {owner} AND {eligible})"
    )
    op.execute(f"CREATE POLICY workbench_plan_purge ON {table} FOR DELETE TO lms_app USING ({tenant} AND {superadmin})")
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {table} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {table} TO lms_app")
    op.execute(f"GRANT UPDATE (status,receipt) ON {table} TO lms_app")


def downgrade() -> None:
    table = f'"{_schema()}".workbench_assignment_plans'
    if op.get_bind().execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
        raise RuntimeError("Workbench downgrade requires empty table; preserve committed receipts")
    op.execute(f"DROP TABLE {table}")
