"""Actor-owned organization changes and durable learning preservation.

Revision ID: 0182
Revises: 0181
"""
import re

from alembic import op

revision = "0182"
down_revision = "0181"
branch_labels = None
depends_on = None


def _schema():
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("unsafe_schema")
    return f'"{schema}"'


def upgrade():
    s = _schema()
    op.execute(f"""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM {s}.users u LEFT JOIN {s}.positions p ON p.id=u.position_id
        WHERE u.position_id IS NOT NULL AND (p.id IS NULL OR u.tenant_id IS DISTINCT FROM p.tenant_id))
      OR EXISTS(SELECT 1 FROM {s}.positions p LEFT JOIN {s}.departments d ON d.id=p.department_id
        WHERE p.department_id IS NOT NULL AND (d.id IS NULL OR p.tenant_id IS DISTINCT FROM d.tenant_id)) THEN
        RAISE EXCEPTION 'existing_staff_tenant_reference_mismatch' USING ERRCODE='23514'; END IF;
      END $$""")
    p, r = f"{s}.organization_change_plans", f"{s}.organization_transfer_retained_enrollments"
    op.execute(f"""CREATE TABLE {p} (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
      actor_id uuid NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
      command jsonb NOT NULL, preview jsonb NOT NULL, fingerprint varchar(64) NOT NULL,
      status varchar(16) NOT NULL CHECK(status IN ('ready','succeeded')),
      receipt jsonb, expires_at timestamptz NOT NULL, executed_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK((status='ready' AND receipt IS NULL AND executed_at IS NULL) OR
            (status='succeeded' AND receipt IS NOT NULL AND executed_at IS NOT NULL)))""")
    op.execute(f"CREATE INDEX ix_org_change_owner ON {p}(tenant_id,actor_id,created_at)")
    op.execute(f"""CREATE TABLE {r} (
      enrollment_id uuid PRIMARY KEY REFERENCES {s}.enrollments(id) ON DELETE CASCADE,
      tenant_id uuid NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
      plan_id uuid REFERENCES {p}(id) ON DELETE SET NULL,
      original_source text NOT NULL CHECK(original_source IN ('position','department','organization')),
      created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute(f"CREATE INDEX ix_org_retained_tenant ON {r}(tenant_id)")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    actor = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    eligible = f"""EXISTS(SELECT 1 FROM {s}.users u WHERE u.id=actor_id AND u.tenant_id=organization_change_plans.tenant_id
      AND u.is_active IS TRUE AND u.status='active' AND (u.role='methodologist' OR EXISTS(
        SELECT 1 FROM {s}.user_roles x WHERE x.user_id=u.id AND x.tenant_id=u.tenant_id AND x.role='methodologist')))"""
    scope = f"{tenant} AND {actor} AND {eligible}"
    for table in (p, r):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE"):
        clause = f"WITH CHECK({scope})" if action == "INSERT" else f"USING({scope})" + (f" WITH CHECK({scope})" if action == "UPDATE" else "")
        op.execute(f"CREATE POLICY org_change_{action.lower()} ON {p} FOR {action} TO lms_app {clause}")
    op.execute(f"CREATE POLICY org_retained_read ON {r} FOR SELECT TO lms_app USING({tenant})")
    owned_plan = f"EXISTS(SELECT 1 FROM {p} p WHERE p.id=plan_id AND p.tenant_id=organization_transfer_retained_enrollments.tenant_id AND p.actor_id=nullif(current_setting('app.user_id',true),'')::uuid)"
    op.execute(f"CREATE POLICY org_retained_insert ON {r} FOR INSERT TO lms_app WITH CHECK({tenant} AND {owned_plan})")
    # Retention is an explicit owner-maintenance operation, never an application
    # DELETE capability or a forgeable session-setting maintenance flag.
    op.execute(f"REVOKE DELETE ON {p} FROM PUBLIC,lms_app")
    op.execute(f"GRANT SELECT,INSERT,UPDATE ON {p} TO lms_app")
    op.execute(f"GRANT SELECT,INSERT ON {r} TO lms_app")
    op.execute(f"""CREATE FUNCTION {s}.guard_organization_change_plan() RETURNS trigger LANGUAGE plpgsql
      SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
      IF TG_OP='INSERT' AND NEW.status<>'ready' THEN
        RAISE EXCEPTION 'organization_change_initial_state' USING ERRCODE='23514'; END IF;
      IF NOT EXISTS(SELECT 1 FROM {s}.users u WHERE u.id=NEW.actor_id AND u.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'organization_change_owner' USING ERRCODE='23514'; END IF;
      IF TG_OP='UPDATE' AND (OLD.status<>'ready' OR NEW.status<>'succeeded' OR
        ROW(NEW.id,NEW.tenant_id,NEW.actor_id,NEW.command,NEW.preview,NEW.fingerprint,NEW.expires_at,NEW.created_at)
        IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.actor_id,OLD.command,OLD.preview,OLD.fingerprint,OLD.expires_at,OLD.created_at)) THEN
        RAISE EXCEPTION 'organization_change_immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW; END $$""")
    op.execute(f"CREATE TRIGGER organization_change_guard BEFORE INSERT OR UPDATE ON {p} FOR EACH ROW EXECUTE FUNCTION {s}.guard_organization_change_plan()")
    op.execute(f"""CREATE FUNCTION {s}.guard_transfer_retained_enrollment() RETURNS trigger LANGUAGE plpgsql
      SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM {s}.enrollments e WHERE e.id=NEW.enrollment_id AND e.tenant_id=NEW.tenant_id
        AND e.source=NEW.original_source) OR NOT EXISTS(SELECT 1 FROM {p} p WHERE p.id=NEW.plan_id AND p.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'retained_enrollment_tenant' USING ERRCODE='23514'; END IF;
      RETURN NEW; END $$""")
    op.execute(f"CREATE TRIGGER retained_enrollment_guard BEFORE INSERT ON {r} FOR EACH ROW EXECUTE FUNCTION {s}.guard_transfer_retained_enrollment()")
    op.execute(f"""CREATE FUNCTION {s}.guard_staff_position_tenant() RETURNS trigger LANGUAGE plpgsql
      SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
      IF NEW.position_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {s}.positions p
        WHERE p.id=NEW.position_id AND p.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'staff_position_tenant_mismatch' USING ERRCODE='23514'; END IF;
      RETURN NEW; END $$""")
    op.execute(f"CREATE TRIGGER staff_position_tenant_guard BEFORE INSERT OR UPDATE OF position_id,tenant_id ON {s}.users FOR EACH ROW EXECUTE FUNCTION {s}.guard_staff_position_tenant()")
    op.execute(f"""CREATE FUNCTION {s}.guard_staff_position_department_tenant() RETURNS trigger LANGUAGE plpgsql
      SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
      IF (TG_OP='UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id) OR
        (NEW.department_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {s}.departments d
        WHERE d.id=NEW.department_id AND d.tenant_id=NEW.tenant_id)) THEN
        RAISE EXCEPTION 'staff_position_department_tenant_mismatch' USING ERRCODE='23514'; END IF;
      RETURN NEW; END $$""")
    op.execute(f"CREATE TRIGGER staff_position_department_tenant_guard BEFORE INSERT OR UPDATE OF department_id,tenant_id ON {s}.positions FOR EACH ROW EXECUTE FUNCTION {s}.guard_staff_position_department_tenant()")
    op.execute(f"""CREATE FUNCTION {s}.guard_staff_unit_tenant_immutable() RETURNS trigger LANGUAGE plpgsql
      SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
      IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'staff_unit_tenant_immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW; END $$""")
    op.execute(f"CREATE TRIGGER staff_unit_tenant_immutable BEFORE UPDATE OF tenant_id ON {s}.departments FOR EACH ROW EXECUTE FUNCTION {s}.guard_staff_unit_tenant_immutable()")


def downgrade():
    s = _schema()
    op.execute(f"DROP TRIGGER staff_unit_tenant_immutable ON {s}.departments")
    op.execute(f"DROP FUNCTION {s}.guard_staff_unit_tenant_immutable()")
    op.execute(f"DROP TRIGGER staff_position_department_tenant_guard ON {s}.positions")
    op.execute(f"DROP FUNCTION {s}.guard_staff_position_department_tenant()")
    op.execute(f"DROP TRIGGER staff_position_tenant_guard ON {s}.users")
    op.execute(f"DROP FUNCTION {s}.guard_staff_position_tenant()")
    op.execute(f"DROP TABLE {s}.organization_transfer_retained_enrollments")
    op.execute(f"DROP TABLE {s}.organization_change_plans")
    op.execute(f"DROP FUNCTION {s}.guard_transfer_retained_enrollment()")
    op.execute(f"DROP FUNCTION {s}.guard_organization_change_plan()")
