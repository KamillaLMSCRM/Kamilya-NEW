"""Migration-only installer for the bounded tenant bootstrap read helpers.

The installer deliberately has no Alembic dependency.  Both the compatibility
expand migration and the final tenant-isolation migration call this function so
their helper definitions and owner/ACL controls cannot drift.
"""

from collections.abc import Callable


def install_bootstrap(schema: str, execute: Callable[[str], object]) -> None:
    """Install the bounded bootstrap functions and their migration ACLs.

    ``schema`` is an already validated, unquoted PostgreSQL identifier supplied
    by the migration.  ``execute`` is intentionally injected to keep this
    migration-only seam independent from Alembic's global operation object.
    """
    table = f'"{schema}".tenants'
    empty = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"
    non_platform = "current_setting('app.is_superadmin', true) IS DISTINCT FROM 'true'"
    execute(f"""
        CREATE OR REPLACE FUNCTION "{schema}".lookup_tenant_id_by_slug(requested_slug text)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
        AS $$
            SELECT id FROM {table}
            WHERE slug = requested_slug AND {empty} AND {non_platform}
        $$
    """)
    execute(f"""
        CREATE OR REPLACE FUNCTION "{schema}".tenant_login_eligible(requested_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM {table} WHERE id = requested_id
                AND status NOT IN ('archived', 'suspended') AND {empty} AND {non_platform}
            )
        $$
    """)
    # Same bounded-definer owner-policy precedent as0111. No new role or bypass.
    execute(f"""
        DO $$
        DECLARE function_owner name; other_owner name;
        BEGIN
            SELECT r.rolname INTO function_owner FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
            WHERE p.oid='"{schema}".lookup_tenant_id_by_slug(text)'::regprocedure;
            SELECT r.rolname INTO other_owner FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
            WHERE p.oid='"{schema}".tenant_login_eligible(uuid)'::regprocedure;
            IF function_owner IS NULL OR function_owner IN ('lms_app', 'public')
                OR function_owner IS DISTINCT FROM other_owner THEN
                RAISE EXCEPTION 'Unsafe tenant bootstrap function owner';
            END IF;
            EXECUTE 'DROP POLICY IF EXISTS tenants_bootstrap_function_owner ON {table}';
            EXECUTE format('CREATE POLICY tenants_bootstrap_function_owner ON {table} '
                'FOR SELECT TO %I USING (true)', function_owner);
        END $$
    """)
    for function in ("lookup_tenant_id_by_slug(text)", "tenant_login_eligible(uuid)"):
        execute(f'REVOKE ALL ON FUNCTION "{schema}".{function} FROM PUBLIC')
        execute(f'GRANT EXECUTE ON FUNCTION "{schema}".{function} TO lms_app')
