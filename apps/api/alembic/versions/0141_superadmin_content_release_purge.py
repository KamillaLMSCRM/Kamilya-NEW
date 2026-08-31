"""Allow bounded superadmin purge of immutable course releases.

Revision ID: 0141
Revises: 0140
Create Date: 2026-08-31

Published releases remain immutable during every ordinary application
operation.  The application role may invoke one SECURITY DEFINER function
that validates the active superadmin context and exact tenant slug before it
removes releases for that tenant only.
"""

from alembic import op

revision = "0141"
down_revision = "0140"
branch_labels = None
depends_on = None

FUNCTION_NAME = "superadmin_purge_tenant_content_releases"


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
               AND current_user = database_owner;
        END;
        $$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.{FUNCTION_NAME}(
            p_tenant_id uuid,
            p_confirm_slug text
        )
        RETURNS integer AS $$
        DECLARE
            persisted_slug text;
            deleted_count integer;
        BEGIN
            IF COALESCE(
                pg_catalog.current_setting('app.is_superadmin', true),
                ''
            ) <> 'true' THEN
                RAISE EXCEPTION 'Active superadmin context is required'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            SELECT t.slug
            INTO persisted_slug
            FROM public.tenants AS t
            WHERE t.id = p_tenant_id;

            IF persisted_slug IS NULL THEN
                RAISE EXCEPTION 'Tenant not found'
                    USING ERRCODE = 'no_data_found';
            END IF;
            IF persisted_slug = 'kamilya' THEN
                RAISE EXCEPTION 'Production tenant is protected'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF persisted_slug IS DISTINCT FROM p_confirm_slug THEN
                RAISE EXCEPTION 'Tenant slug confirmation mismatch'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            PERFORM pg_catalog.set_config(
                'app.privileged_tenant_purge_id',
                p_tenant_id::text,
                true
            );
            UPDATE public.courses
            SET current_release_id = NULL
            WHERE tenant_id = p_tenant_id;
            DELETE FROM public.content_releases
            WHERE tenant_id = p_tenant_id;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp;
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION public.{FUNCTION_NAME}(uuid, text) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION public.{FUNCTION_NAME}(uuid, text) TO lms_app"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION IF EXISTS public.{FUNCTION_NAME}(uuid, text)"
    )
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
