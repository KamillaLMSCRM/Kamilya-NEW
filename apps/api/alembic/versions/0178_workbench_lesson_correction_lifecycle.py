"""Durable correction estimate boundary and bounded metadata maintenance.

Revision ID: 0178
Revises: 0177
"""

import re

from sqlalchemy import text

from alembic import op

revision = "0178"
down_revision = "0177"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe correction lifecycle schema")
    return f'"{schema}"'


def upgrade() -> None:
    s = _schema()
    plans = f"{s}.workbench_lesson_correction_plans"
    receipts = f"{s}.workbench_lesson_correction_applications"
    ledger = f"{s}.workbench_lesson_correction_accounting"
    guard = f"{s}.guard_lesson_correction_accounting"
    maintenance = f"{s}.maintain_workbench_lesson_corrections"
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    owner = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    superadmin = "COALESCE(current_setting('app.is_superadmin',true),'false')='true'"
    eligible = f"""EXISTS(SELECT 1 FROM {s}.users u
        WHERE u.id=workbench_lesson_correction_accounting.actor_id
        AND u.tenant_id=workbench_lesson_correction_accounting.tenant_id
        AND u.is_active IS TRUE AND u.status='active'
        AND(u.role='methodologist' OR EXISTS(SELECT 1 FROM {s}.user_roles r
            WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist')))"""
    op.execute(f"""CREATE TABLE {ledger}(
        plan_id uuid PRIMARY KEY REFERENCES {plans}(id) ON DELETE CASCADE,
        tenant_id uuid NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL,
        month_key varchar(7) NOT NULL CHECK(month_key ~ '^[0-9]{{4}}-(0[1-9]|1[0-2])$'),
        estimated_cost_cents integer NOT NULL CHECK(estimated_cost_cents=10),
        state varchar(16) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        provider_boundary_at timestamptz,
        settled_at timestamptz,
        CONSTRAINT ck_correction_accounting_state CHECK(
            (state='reserved' AND provider_boundary_at IS NULL AND settled_at IS NULL)
            OR(state='started' AND provider_boundary_at IS NOT NULL AND settled_at IS NULL)
            OR(state IN('charged','retained') AND provider_boundary_at IS NOT NULL AND settled_at IS NOT NULL)
            OR(state='refunded' AND settled_at IS NOT NULL))
    )""")
    op.execute(f"ALTER TABLE {ledger} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {ledger} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY correction_accounting_read ON {ledger} FOR SELECT TO lms_app USING({tenant} AND({owner} OR {superadmin}))")
    op.execute(f"CREATE POLICY correction_accounting_insert ON {ledger} FOR INSERT TO lms_app WITH CHECK({tenant} AND {owner} AND {eligible})")
    op.execute(f"CREATE POLICY correction_accounting_update ON {ledger} FOR UPDATE TO lms_app USING({tenant} AND({owner} OR {superadmin})) WITH CHECK({tenant} AND({superadmin} OR({owner} AND(state IN('refunded','retained') OR {eligible}))))")
    op.execute(f"CREATE POLICY correction_accounting_purge ON {ledger} FOR DELETE TO lms_app USING({tenant} AND {superadmin})")
    # Existing owner policy remains untouched. Maintenance can only close pending
    # to failed (0176 trigger), never finish a proposal as ready or alter a result.
    op.execute(f"CREATE POLICY correction_maintenance_close ON {plans} FOR UPDATE TO lms_app USING({tenant} AND {superadmin}) WITH CHECK({tenant} AND {superadmin} AND status='failed')")
    # Without this policy RLS hides successful receipts from the maintenance actor,
    # misclassifying an applied plan as an unexecuted 24-hour preview.
    op.execute(f"CREATE POLICY correction_application_maintenance_read ON {receipts} FOR SELECT TO lms_app USING({tenant} AND {superadmin})")
    op.execute(f"""CREATE FUNCTION {guard}() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$
        DECLARE p record; refunded_usage uuid; v_super boolean;
        BEGIN
            SELECT * INTO p FROM {plans} WHERE id=NEW.plan_id
                AND tenant_id=NEW.tenant_id AND actor_id=NEW.actor_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'correction_accounting_owner_invalid' USING ERRCODE='23514'; END IF;
            v_super := COALESCE(current_setting('app.is_superadmin',true),'false')='true';
            IF TG_OP='INSERT' THEN
                IF NEW.state<>'reserved' OR p.status<>'pending'
                    OR NEW.month_key<>to_char((p.snapshot->>'created_at')::timestamptz AT TIME ZONE 'UTC','YYYY-MM')
                    OR NEW.provider_boundary_at IS NOT NULL OR NEW.settled_at IS NOT NULL THEN
                    RAISE EXCEPTION 'correction_accounting_admission_invalid' USING ERRCODE='23514';
                END IF;
                NEW.created_at := clock_timestamp();
                RETURN NEW;
            END IF;
            IF NEW.plan_id IS DISTINCT FROM OLD.plan_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.month_key IS DISTINCT FROM OLD.month_key
                OR NEW.estimated_cost_cents IS DISTINCT FROM OLD.estimated_cost_cents
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.provider_boundary_at IS DISTINCT FROM OLD.provider_boundary_at
                OR NEW.settled_at IS DISTINCT FROM OLD.settled_at THEN
                RAISE EXCEPTION 'correction_accounting_identity_immutable' USING ERRCODE='23514';
            END IF;
            IF OLD.state IN('charged','refunded','retained') THEN
                IF NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'correction_accounting_terminal_immutable' USING ERRCODE='23514';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.state='started' AND OLD.state='reserved' AND p.status='pending'
                AND p.expires_at>clock_timestamp() AND NOT v_super THEN
                NEW.provider_boundary_at := clock_timestamp();
            ELSIF NEW.state='charged' AND OLD.state='started' AND p.status='ready' AND NOT v_super THEN
                NEW.settled_at := clock_timestamp();
            ELSIF NEW.state='refunded' AND OLD.state IN('reserved','started') AND p.status='failed'
                AND(NOT v_super OR OLD.state='reserved') THEN
                UPDATE {s}.tenant_llm_usage SET
                    cost_cents=cost_cents-OLD.estimated_cost_cents,
                    request_count=request_count-1,updated_at=clock_timestamp()
                    WHERE tenant_id=OLD.tenant_id AND month_key=OLD.month_key
                        AND cost_cents>=OLD.estimated_cost_cents AND request_count>=1
                    RETURNING id INTO refunded_usage;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'correction_accounting_pending' USING ERRCODE='23514';
                END IF;
                NEW.settled_at := clock_timestamp();
            ELSIF NEW.state='retained' AND OLD.state='started' AND p.status='failed' AND v_super THEN
                NEW.settled_at := clock_timestamp();
            ELSE
                RAISE EXCEPTION 'correction_accounting_transition_invalid' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute(f"CREATE TRIGGER lesson_correction_accounting_guard BEFORE INSERT OR UPDATE ON {ledger} FOR EACH ROW EXECUTE FUNCTION {guard}()")
    op.execute(f"CREATE INDEX ix_correction_expiry_maintenance ON {plans}(tenant_id,expires_at,id)")
    op.execute(f"CREATE INDEX ix_correction_application_retention ON {receipts}(tenant_id,applied_at,plan_id)")
    eligibility = """p.tenant_id=v_tenant AND(
        (p.status='pending' AND p.expires_at<=transaction_timestamp())
        OR(p.status IN('ready','failed') AND a.plan_id IS NULL
            AND p.expires_at<=transaction_timestamp()-interval '24 hours')
        OR(a.applied_at<=transaction_timestamp()-interval '90 days'))"""
    action = """CASE WHEN p.status='pending' THEN
        CASE WHEN l.state='reserved' THEN 'reconcile_refund' ELSE 'reconcile_retain' END
        WHEN a.plan_id IS NOT NULL THEN 'delete_application' ELSE 'delete_preview' END"""
    ordering = """CASE WHEN p.status='pending' THEN p.expires_at
        WHEN a.plan_id IS NOT NULL THEN a.applied_at+interval '90 days'
        ELSE p.expires_at+interval '24 hours' END,p.id"""
    query = f"""SELECT p.id AS selected_id,{action} AS selected_action FROM {plans} p
        LEFT JOIN {receipts} a ON a.plan_id=p.id AND a.tenant_id=p.tenant_id
        LEFT JOIN {ledger} l ON l.plan_id=p.id AND l.tenant_id=p.tenant_id
        WHERE {eligibility} ORDER BY {ordering} LIMIT p_limit"""
    op.execute(f"""CREATE FUNCTION {maintenance}(p_limit integer DEFAULT 100,p_apply boolean DEFAULT false)
        RETURNS TABLE(plan_id uuid,action text) LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$
        DECLARE v_tenant uuid; candidate record; accounting record;
        BEGIN
            IF current_user<>'lms_app'
                OR COALESCE(current_setting('app.is_superadmin',true),'false')<>'true'
                OR NULLIF(current_setting('app.tenant_id',true),'') IS NULL THEN
                RAISE EXCEPTION 'correction_maintenance_forbidden' USING ERRCODE='42501';
            END IF;
            IF p_limit IS NULL OR p_limit<1 OR p_limit>500 OR p_apply IS NULL THEN
                RAISE EXCEPTION 'correction_maintenance_invalid_batch' USING ERRCODE='22023';
            END IF;
            v_tenant := NULLIF(current_setting('app.tenant_id',true),'')::uuid;
            IF NOT p_apply THEN RETURN QUERY {query}; RETURN; END IF;
            FOR candidate IN {query} FOR UPDATE OF p SKIP LOCKED LOOP
                IF candidate.selected_action LIKE 'reconcile_%' THEN
                    SELECT * INTO accounting FROM {ledger} WHERE {ledger}.plan_id=candidate.selected_id
                        AND tenant_id=v_tenant FOR UPDATE;
                    IF FOUND AND accounting.state NOT IN('reserved','started') THEN
                        RAISE EXCEPTION 'correction_accounting_pending' USING ERRCODE='23514';
                    END IF;
                    candidate.selected_action := CASE WHEN FOUND AND accounting.state='reserved' THEN 'reconcile_refund' ELSE 'reconcile_retain' END;
                    UPDATE {plans} SET status='failed',error_code='proposal_interrupted'
                        WHERE id=candidate.selected_id AND tenant_id=v_tenant AND status='pending';
                    UPDATE {ledger} SET state=CASE WHEN state='reserved' THEN 'refunded' ELSE 'retained' END
                        WHERE {ledger}.plan_id=candidate.selected_id AND tenant_id=v_tenant;
                ELSE
                    DELETE FROM {plans} WHERE id=candidate.selected_id AND tenant_id=v_tenant;
                END IF;
                plan_id := candidate.selected_id; action := candidate.selected_action; RETURN NEXT;
            END LOOP;
        END $$""")
    op.execute(f"REVOKE ALL ON {ledger} FROM PUBLIC,lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {ledger} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT SELECT,INSERT,DELETE ON {ledger} TO lms_app")
    op.execute(f"GRANT UPDATE(state) ON {ledger} TO lms_app")
    for function in (f"{guard}()", f"{maintenance}(integer,boolean)"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,lms_app")
        for role in ("anon", "authenticated", "service_role", "lms_recovery"):
            op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
                EXECUTE 'REVOKE ALL ON FUNCTION {function} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT EXECUTE ON FUNCTION {maintenance}(integer,boolean) TO lms_app")


def downgrade() -> None:
    s = _schema()
    plans = f"{s}.workbench_lesson_correction_plans"
    ledger = f"{s}.workbench_lesson_correction_accounting"
    if op.get_bind().execute(text(f"SELECT EXISTS(SELECT 1 FROM {plans}) OR EXISTS(SELECT 1 FROM {ledger})")).scalar():
        raise RuntimeError("Correction lifecycle downgrade requires empty tables; preserve accounting")
    op.execute(f"DROP FUNCTION {s}.maintain_workbench_lesson_corrections(integer,boolean)")
    op.execute(f"DROP TABLE {ledger}")
    op.execute(f"DROP FUNCTION {s}.guard_lesson_correction_accounting()")
    op.execute(f"DROP POLICY correction_maintenance_close ON {plans}")
    op.execute(f"DROP POLICY correction_application_maintenance_read ON {s}.workbench_lesson_correction_applications")
    op.execute(f"DROP INDEX {s}.ix_correction_expiry_maintenance")
    op.execute(f"DROP INDEX {s}.ix_correction_application_retention")
