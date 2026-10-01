"""DB-owned execution time and bounded tenant-only workbench retention.

Revision ID: 0171
Revises: 0170
"""

import re

from alembic import op

revision = "0171"
down_revision = "0170"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe workbench schema")
    return f'"{schema}"'


def upgrade() -> None:
    schema = _schema()
    table = f"{schema}.workbench_assignment_plans"
    stamp = f"{schema}.stamp_workbench_execution_time"
    cleanup = f"{schema}.cleanup_workbench_assignment_plans"
    op.execute(f"ALTER TABLE {table} ADD COLUMN executed_at timestamptz")
    # Historic successful records have no reliable execution time: preserve NULL.
    op.execute(f"""
        ALTER TABLE {table} ADD CONSTRAINT ck_workbench_plan_execution_time
        CHECK (status='succeeded' OR executed_at IS NULL)
    """)
    op.execute(f"""
        CREATE FUNCTION {stamp}() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.status <> 'ready' OR NEW.executed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'workbench_initial_state_invalid' USING ERRCODE='23514';
                END IF;
            ELSIF OLD.status='succeeded' THEN
                IF NEW.status IS DISTINCT FROM OLD.status
                   OR NEW.receipt IS DISTINCT FROM OLD.receipt
                   OR NEW.executed_at IS DISTINCT FROM OLD.executed_at THEN
                    RAISE EXCEPTION 'workbench_receipt_immutable' USING ERRCODE='23514';
                END IF;
            ELSIF NEW.status='succeeded' THEN
                NEW.executed_at := clock_timestamp();
            ELSIF NEW.executed_at IS DISTINCT FROM OLD.executed_at THEN
                RAISE EXCEPTION 'workbench_execution_time_owned' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(f"""
        CREATE TRIGGER workbench_execution_time BEFORE INSERT OR UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {stamp}()
    """)
    op.execute(f"""
        CREATE INDEX ix_workbench_plan_ready_retention ON {table}(tenant_id,expires_at,id) WHERE status='ready'
    """)
    op.execute(f"""
        CREATE INDEX ix_workbench_plan_success_retention ON {table}(tenant_id,executed_at,id)
        WHERE status='succeeded' AND executed_at IS NOT NULL
    """)
    predicate = """
        p.tenant_id=v_tenant AND (
            (p.status='ready' AND p.expires_at <= transaction_timestamp()-interval '24 hours')
            OR (p.status='succeeded' AND p.executed_at IS NOT NULL
                AND p.executed_at <= transaction_timestamp()-interval '90 days'))
    """
    ordering = "CASE WHEN p.status='ready' THEN p.expires_at+interval '24 hours' ELSE p.executed_at+interval '90 days' END,p.id"
    op.execute(f"""
        CREATE FUNCTION {cleanup}(p_limit integer DEFAULT 100,p_apply boolean DEFAULT false)
        RETURNS TABLE(plan_id uuid,plan_status varchar) LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$
        DECLARE v_tenant uuid;
        BEGIN
            IF current_user <> 'lms_app'
               OR COALESCE(current_setting('app.is_superadmin',true),'false') <> 'true'
               OR NULLIF(current_setting('app.tenant_id',true),'') IS NULL THEN
                RAISE EXCEPTION 'workbench_cleanup_forbidden' USING ERRCODE='42501';
            END IF;
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 500 OR p_apply IS NULL THEN
                RAISE EXCEPTION 'workbench_cleanup_invalid_batch' USING ERRCODE='22023';
            END IF;
            v_tenant := NULLIF(current_setting('app.tenant_id',true),'')::uuid;
            IF NOT p_apply THEN
                RETURN QUERY SELECT p.id,p.status FROM {table} p
                    WHERE {predicate} ORDER BY {ordering} LIMIT p_limit;
            ELSE
                RETURN QUERY WITH candidates AS MATERIALIZED (
                    SELECT p.id FROM {table} p WHERE {predicate}
                    ORDER BY {ordering} LIMIT p_limit FOR UPDATE OF p SKIP LOCKED
                )
                DELETE FROM {table} p USING candidates c
                WHERE p.id=c.id AND p.tenant_id=v_tenant
                RETURNING p.id,p.status;
            END IF;
        END $$
    """)
    for function in (f"{stamp}()", f"{cleanup}(integer,boolean)"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,lms_app")
        for role in ("anon", "authenticated", "service_role", "lms_recovery"):
            op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
                EXECUTE 'REVOKE ALL ON FUNCTION {function} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT EXECUTE ON FUNCTION {cleanup}(integer,boolean) TO lms_app")


def downgrade() -> None:
    raise RuntimeError("Workbench retention is roll-forward only; preserve execution timestamps")
