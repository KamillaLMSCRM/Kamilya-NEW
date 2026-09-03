"""Allow the database owner through bounded superadmin purge functions.

Revision ID: 0149
Revises: 0148
Create Date: 2026-09-03

Production connects as ``lms_app`` while ephemeral integration environments
run the API as the database owner.  Both identities are already privileged at
their respective database boundary.  Keep the application-level
``app.is_superadmin`` requirement and exact tenant slug confirmation, while
rejecting every other session role.
"""

from alembic import op

revision = "0149"
down_revision = "0148"
branch_labels = None
depends_on = None


def _audit_purge(*, allow_database_owner: bool) -> str:
    identity_guard = (
        "session_user <> 'lms_app' AND session_user <> database_owner"
        if allow_database_owner
        else "session_user <> 'lms_app'"
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.superadmin_purge_tenant_audit_logs(
            p_tenant_id uuid,
            p_confirm_slug text
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE persisted_slug text;
        DECLARE deleted_count integer;
        DECLARE database_owner name;
        BEGIN
            SELECT pg_catalog.pg_get_userbyid(d.datdba)
            INTO database_owner
            FROM pg_catalog.pg_database AS d
            WHERE d.datname = pg_catalog.current_database();

            IF COALESCE(current_setting('app.is_superadmin', true), '') <> 'true'
               OR ({identity_guard}) THEN
                RAISE EXCEPTION 'Active superadmin context is required'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            SELECT t.slug INTO persisted_slug FROM public.tenants AS t WHERE t.id = p_tenant_id;
            IF persisted_slug IS NULL THEN
                RAISE EXCEPTION 'Tenant not found' USING ERRCODE = 'no_data_found';
            END IF;
            IF persisted_slug = 'kamilya' OR persisted_slug IS DISTINCT FROM p_confirm_slug THEN
                RAISE EXCEPTION 'Tenant deletion confirmation rejected' USING ERRCODE = 'insufficient_privilege';
            END IF;
            DELETE FROM public.audit_logs WHERE tenant_id = p_tenant_id;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$;
    """


def _approval_purge(*, allow_database_owner: bool) -> str:
    identity_guard = (
        "session_user <> 'lms_app' AND session_user <> database_owner"
        if allow_database_owner
        else "session_user <> 'lms_app'"
    )
    return f"""
        CREATE OR REPLACE FUNCTION public.superadmin_purge_tenant_course_approval(
            p_tenant_id uuid,
            p_confirm_slug text
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE persisted_slug text;
        DECLARE deleted_count integer := 0;
        DECLARE database_owner name;
        BEGIN
            SELECT pg_catalog.pg_get_userbyid(d.datdba)
            INTO database_owner
            FROM pg_catalog.pg_database AS d
            WHERE d.datname = pg_catalog.current_database();

            IF COALESCE(current_setting('app.is_superadmin', true), '') <> 'true'
               OR ({identity_guard}) THEN
                RAISE EXCEPTION 'Active superadmin context is required'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            SELECT t.slug INTO persisted_slug FROM public.tenants AS t WHERE t.id = p_tenant_id;
            IF persisted_slug IS NULL OR persisted_slug = 'kamilya' OR persisted_slug IS DISTINCT FROM p_confirm_slug THEN
                RAISE EXCEPTION 'Tenant deletion confirmation rejected' USING ERRCODE = 'insufficient_privilege';
            END IF;
            DELETE FROM public.workflow_deliveries WHERE tenant_id = p_tenant_id;
            DELETE FROM public.workflow_reminders WHERE tenant_id = p_tenant_id;
            DELETE FROM public.workflow_escalations WHERE tenant_id = p_tenant_id;
            DELETE FROM public.workflow_access_credentials WHERE tenant_id = p_tenant_id;
            DELETE FROM public.course_review_attempt_events WHERE tenant_id = p_tenant_id;
            DELETE FROM public.course_review_attempts WHERE tenant_id = p_tenant_id;
            DELETE FROM public.workflow_work_items WHERE tenant_id = p_tenant_id;
            DELETE FROM public.course_approval_reviewers WHERE tenant_id = p_tenant_id;
            DELETE FROM public.course_approval_requests WHERE tenant_id = p_tenant_id;
            DELETE FROM public.workflow_idempotency_keys WHERE tenant_id = p_tenant_id;
            DELETE FROM public.course_approval_revisions WHERE tenant_id = p_tenant_id;
            DELETE FROM public.course_approval_policies WHERE tenant_id = p_tenant_id;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$;
    """


def _replace_purge_functions(*, allow_database_owner: bool) -> None:
    op.execute(_audit_purge(allow_database_owner=allow_database_owner))
    op.execute(_approval_purge(allow_database_owner=allow_database_owner))
    op.execute("REVOKE ALL ON FUNCTION public.superadmin_purge_tenant_audit_logs(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.superadmin_purge_tenant_audit_logs(uuid, text) TO lms_app")
    op.execute("REVOKE ALL ON FUNCTION public.superadmin_purge_tenant_course_approval(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.superadmin_purge_tenant_course_approval(uuid, text) TO lms_app")


def upgrade() -> None:
    _replace_purge_functions(allow_database_owner=True)


def downgrade() -> None:
    _replace_purge_functions(allow_database_owner=False)
