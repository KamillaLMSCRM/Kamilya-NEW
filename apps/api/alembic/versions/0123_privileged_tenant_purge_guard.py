"""Add an owner-only guard for privileged whole-tenant deletion.

Revision ID: 0123
Revises: 0122
Create Date: 2026-08-22

Published learning programs remain immutable for every ordinary application
operation.  A direct database-owner session may authorize DELETE statements
for one exact tenant inside the current transaction.  This migration does not
expose a callable purge function or grant a destructive capability to lms_app.
"""

from alembic import op

revision = "0123"
down_revision = "0122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.privileged_tenant_purge_authorized(
            p_tenant_id uuid
        )
        RETURNS boolean AS $$
        DECLARE
            database_owner name;
        BEGIN
            SELECT pg_catalog.pg_get_userbyid(d.datdba)
            INTO database_owner
            FROM pg_catalog.pg_database AS d
            WHERE d.datname = pg_catalog.current_database();

            RETURN NULLIF(
                       pg_catalog.current_setting(
                           'app.privileged_tenant_purge_id',
                           true
                       ),
                       ''
                   ) = p_tenant_id::text
               AND session_user = database_owner
               AND current_user = database_owner;
        END;
        $$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_published_learning_path_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'published' THEN
                IF TG_OP = 'DELETE'
                   AND public.privileged_tenant_purge_authorized(OLD.tenant_id) THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'Published learning-program versions are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_published_learning_path_step_mutation()
        RETURNS trigger AS $$
        DECLARE
            path_status text;
            path_tenant_id uuid;
        BEGIN
            SELECT p.status, p.tenant_id
            INTO path_status, path_tenant_id
            FROM public.learning_paths AS p
            WHERE p.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.path_id ELSE NEW.path_id END;

            IF path_status = 'published' THEN
                IF TG_OP = 'DELETE'
                   AND public.privileged_tenant_purge_authorized(path_tenant_id) THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'Published learning-program curriculum is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_published_learning_path_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'published' THEN
                RAISE EXCEPTION 'Published learning-program versions are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_published_learning_path_step_mutation()
        RETURNS trigger AS $$
        DECLARE
            path_status text;
        BEGIN
            SELECT p.status
            INTO path_status
            FROM public.learning_paths AS p
            WHERE p.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.path_id ELSE NEW.path_id END;

            IF path_status = 'published' THEN
                RAISE EXCEPTION 'Published learning-program curriculum is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )

    op.execute(
        "DROP FUNCTION IF EXISTS public.privileged_tenant_purge_authorized(uuid)"
    )
