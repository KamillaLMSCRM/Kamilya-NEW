"""Bind platform impersonation actors and provide narrow audit cleanup.

Revision ID: 0148
Revises: 0147
Create Date: 2026-09-03

Platform superadmin impersonation keeps the real actor UUID for audit.  The
0147 tenant-integrity trigger originally required every actor UUID to belong
to the target tenant, which incorrectly rejected that legitimate path.  This
revision adds a database-validated, transaction-local impersonation marker.

Tenant deletion still keeps ``audit_logs`` append-only for ordinary runtime
operations.  A SECURITY DEFINER function is the only application-role path
that may remove one explicitly confirmed tenant's audit rows while an active
platform-superadmin context is present.
"""

from alembic import op

revision = "0148"
down_revision = "0147"
branch_labels = None
depends_on = None


def _trigger_body(*, allow_impersonation: bool) -> str:
    actor_guard = " AND NOT public.course_approval_platform_actor_bound(NEW.updated_by, NEW.tenant_id)" if allow_impersonation else ""
    revision_guard = " AND NOT public.course_approval_platform_actor_bound(NEW.created_by, NEW.tenant_id)" if allow_impersonation else ""
    requester_guard = " AND NOT public.course_approval_platform_actor_bound(NEW.requested_by, NEW.tenant_id)" if allow_impersonation else ""
    return f"""
        CREATE OR REPLACE FUNCTION enforce_course_approval_tenant_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE owner_tenant uuid;
        BEGIN
            IF TG_TABLE_NAME = 'course_approval_policies' THEN
                SELECT tenant_id INTO owner_tenant FROM courses WHERE id = NEW.course_id;
                IF (TG_OP = 'INSERT' OR NEW.updated_by IS DISTINCT FROM OLD.updated_by) AND NEW.updated_by IS NOT NULL AND (SELECT tenant_id FROM users WHERE id = NEW.updated_by) IS DISTINCT FROM NEW.tenant_id{actor_guard} THEN
                    RAISE EXCEPTION 'course approval policy actor tenant mismatch' USING ERRCODE='check_violation';
                END IF;
            ELSIF TG_TABLE_NAME = 'course_approval_revisions' THEN
                SELECT tenant_id INTO owner_tenant FROM courses WHERE id = NEW.course_id;
                IF TG_OP = 'INSERT' AND NEW.created_by IS NOT NULL AND (SELECT tenant_id FROM users WHERE id = NEW.created_by) IS DISTINCT FROM NEW.tenant_id{revision_guard} THEN
                    RAISE EXCEPTION 'course approval revision actor tenant mismatch' USING ERRCODE='check_violation';
                END IF;
            ELSIF TG_TABLE_NAME = 'course_approval_requests' THEN
                SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.revision_id;
                IF (TG_OP = 'INSERT' OR NEW.requested_by IS DISTINCT FROM OLD.requested_by) AND NEW.requested_by IS NOT NULL AND (SELECT tenant_id FROM users WHERE id = NEW.requested_by) IS DISTINCT FROM NEW.tenant_id{requester_guard} THEN
                    RAISE EXCEPTION 'course approval requester tenant mismatch' USING ERRCODE='check_violation';
                END IF;
            ELSIF TG_TABLE_NAME = 'course_approval_reviewers' THEN
                SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.revision_id;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'course approval reviewer tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                IF NEW.reviewer_user_id IS NOT NULL AND NEW.reviewer_email IS NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.reviewer_user_id;
                ELSE
                    owner_tenant := NEW.tenant_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'course_review_attempts' THEN
                SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.revision_id;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'course review attempt tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                IF NEW.reviewer_user_id IS NOT NULL AND NEW.reviewer_email IS NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.reviewer_user_id;
                ELSE
                    owner_tenant := NEW.tenant_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'course_review_attempt_events' THEN
                SELECT tenant_id INTO owner_tenant FROM course_review_attempts WHERE id = NEW.attempt_id;
            ELSIF TG_TABLE_NAME = 'workflow_work_items' THEN
                IF NEW.review_revision_id IS NOT NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM course_approval_revisions WHERE id = NEW.review_revision_id;
                ELSIF NEW.enrollment_id IS NOT NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM enrollments WHERE id = NEW.enrollment_id;
                END IF;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'workflow work item tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                IF NEW.target_user_id IS NOT NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.target_user_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'workflow_access_credentials' THEN
                SELECT tenant_id INTO owner_tenant FROM workflow_work_items WHERE id = NEW.work_item_id;
                IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                    RAISE EXCEPTION 'workflow credential tenant mismatch' USING ERRCODE='check_violation';
                END IF;
                IF NEW.reviewer_user_id IS NOT NULL AND NEW.reviewer_email IS NULL THEN
                    SELECT tenant_id INTO owner_tenant FROM users WHERE id = NEW.reviewer_user_id;
                ELSE
                    owner_tenant := NEW.tenant_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'workflow_idempotency_keys' THEN
                owner_tenant := NEW.tenant_id;
            ELSE
                SELECT tenant_id INTO owner_tenant FROM workflow_work_items WHERE id = NEW.work_item_id;
                IF TG_TABLE_NAME = 'workflow_deliveries' AND NEW.recipient_user_id IS NOT NULL THEN
                    IF (SELECT tenant_id FROM users WHERE id = NEW.recipient_user_id) IS DISTINCT FROM NEW.tenant_id THEN
                        RAISE EXCEPTION 'course approval delivery recipient tenant mismatch' USING ERRCODE='check_violation';
                    END IF;
                ELSIF TG_TABLE_NAME IN ('workflow_reminders', 'workflow_escalations') AND NEW.recipient_user_id IS NOT NULL THEN
                    IF (SELECT tenant_id FROM users WHERE id = NEW.recipient_user_id) IS DISTINCT FROM NEW.tenant_id THEN
                        RAISE EXCEPTION 'course approval deadline recipient tenant mismatch' USING ERRCODE='check_violation';
                    END IF;
                END IF;
            END IF;
            IF owner_tenant IS DISTINCT FROM NEW.tenant_id THEN
                RAISE EXCEPTION 'course approval tenant ownership mismatch' USING ERRCODE='check_violation';
            END IF;
            RETURN NEW;
        END $$;
    """


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.course_approval_platform_actor_bound(
            p_actor_id uuid,
            p_tenant_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE actor_tenant uuid;
        DECLARE actor_role text;
        BEGIN
            IF COALESCE(current_setting('app.is_impersonating', true), '') <> 'true'
               OR NULLIF(current_setting('app.impersonating_actor_id', true), '') IS DISTINCT FROM p_actor_id::text
               OR NULLIF(current_setting('app.tenant_id', true), '')::uuid IS DISTINCT FROM p_tenant_id THEN
                RETURN false;
            END IF;
            SELECT u.tenant_id, u.role INTO actor_tenant, actor_role
            FROM public.users AS u WHERE u.id = p_actor_id;
            RETURN actor_tenant IS NULL AND actor_role = 'superadmin';
        END;
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.course_approval_platform_actor_bound(uuid, uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.course_approval_platform_actor_bound(uuid, uuid) TO lms_app")
    op.execute(_trigger_body(allow_impersonation=True))
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.superadmin_purge_tenant_audit_logs(
            p_tenant_id uuid,
            p_confirm_slug text
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE persisted_slug text;
        DECLARE deleted_count integer;
        BEGIN
            IF COALESCE(current_setting('app.is_superadmin', true), '') <> 'true'
               OR session_user <> 'lms_app' THEN
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
    )
    op.execute("REVOKE ALL ON FUNCTION public.superadmin_purge_tenant_audit_logs(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.superadmin_purge_tenant_audit_logs(uuid, text) TO lms_app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.superadmin_purge_tenant_course_approval(
            p_tenant_id uuid,
            p_confirm_slug text
        ) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE persisted_slug text;
        DECLARE deleted_count integer := 0;
        BEGIN
            IF COALESCE(current_setting('app.is_superadmin', true), '') <> 'true'
               OR session_user <> 'lms_app' THEN
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
    )
    op.execute("REVOKE ALL ON FUNCTION public.superadmin_purge_tenant_course_approval(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.superadmin_purge_tenant_course_approval(uuid, text) TO lms_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.superadmin_purge_tenant_course_approval(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS public.superadmin_purge_tenant_audit_logs(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS public.course_approval_platform_actor_bound(uuid, uuid)")
    op.execute(_trigger_body(allow_impersonation=False))
