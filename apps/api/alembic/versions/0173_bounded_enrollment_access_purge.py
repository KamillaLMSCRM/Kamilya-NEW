"""Exact-superadmin purge of enrollment access children, without DELETE grants.

Revision ID: 0173
Revises: 0172
"""
import re

from alembic import op

revision = "0173"
down_revision = "0172"
branch_labels = None
depends_on = None

FUNCTION = "superadmin_purge_tenant_enrollment_access"


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe enrollment purge schema")
    return schema


def purge_sql(schema: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe enrollment purge schema")
    return f'''
        CREATE FUNCTION "{schema}".{FUNCTION}(p_tenant_id uuid,p_confirm_slug text)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE v_owner name; v_slug text; v_count integer := 0; v_rows integer;
        BEGIN
            SELECT pg_get_userbyid(d.datdba) INTO v_owner FROM pg_database d
                WHERE d.datname=current_database();
            IF (session_user <> 'lms_app' AND session_user <> v_owner)
               OR current_user <> v_owner
               OR coalesce(current_setting('app.is_superadmin',true),'') <> 'true'
               OR p_tenant_id IS NULL
               OR nullif(current_setting('app.tenant_id',true),'') IS DISTINCT FROM p_tenant_id::text
               OR p_confirm_slug IS NULL THEN
                RAISE EXCEPTION 'enrollment_access_purge_forbidden' USING ERRCODE='42501';
            END IF;
            SELECT t.slug INTO v_slug FROM "{schema}".tenants t WHERE t.id=p_tenant_id FOR UPDATE;
            IF v_slug IS NULL OR v_slug='kamilya' OR v_slug IS DISTINCT FROM p_confirm_slug THEN
                RAISE EXCEPTION 'enrollment_access_purge_target_rejected' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM "{schema}".course_assignment_notification_outbox
                WHERE tenant_id=p_tenant_id FOR UPDATE;
            IF EXISTS (SELECT 1 FROM "{schema}".course_assignment_notification_outbox
                       WHERE tenant_id=p_tenant_id AND status='claimed') THEN
                RAISE EXCEPTION 'enrollment_access_purge_notification_claimed' USING ERRCODE='55000';
            END IF;
            DELETE FROM "{schema}".assignment_access_credentials WHERE tenant_id=p_tenant_id;
            GET DIAGNOSTICS v_rows=ROW_COUNT; v_count:=v_count+v_rows;
            DELETE FROM "{schema}".enrollment_access_policies WHERE tenant_id=p_tenant_id;
            GET DIAGNOSTICS v_rows=ROW_COUNT; v_count:=v_count+v_rows;
            DELETE FROM "{schema}".course_assignment_notification_outbox WHERE tenant_id=p_tenant_id;
            GET DIAGNOSTICS v_rows=ROW_COUNT; v_count:=v_count+v_rows;
            RETURN v_count;
        END $$
    '''


def upgrade() -> None:
    schema = _schema()
    function = f'"{schema}".{FUNCTION}(uuid,text)'
    op.execute(purge_sql(schema))
    op.execute(f'''DO $$ DECLARE v_owner name; BEGIN
        SELECT pg_get_userbyid(datdba) INTO v_owner FROM pg_database WHERE datname=current_database();
        EXECUTE format('ALTER FUNCTION {function} OWNER TO %I',v_owner);
    END $$''')
    op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f'''DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON FUNCTION {function} FROM {role}'; END IF; END $$''')
    op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO lms_app")


def downgrade() -> None:
    op.execute(f'DROP FUNCTION "{_schema()}".{FUNCTION}(uuid,text)')
