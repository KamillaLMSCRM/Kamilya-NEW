"""Enable and force RLS on tenant-scoped tables added outside the RLS chain.

Revision ID: 0065
Revises: 0064
"""

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "generated_content",
    "kiosk_access_logs",
    "learner_assistant_messages",
    "scorm_attempts",
    "scorm_packages",
    "staff_import_mappings",
    "tenant_usage",
)


def _tenant_expression() -> str:
    return "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            FOR ALL TO lms_app
            USING ({_tenant_expression()})
            WITH CHECK ({_tenant_expression()})
            """
        )
        op.execute(f"DROP POLICY IF EXISTS {table}_superadmin_session ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_superadmin_session ON {table}
            FOR ALL TO lms_app
            USING (current_setting('app.is_superadmin', true) = 'true')
            WITH CHECK (current_setting('app.is_superadmin', true) = 'true')
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")

    # Global provider keys are intentionally readable by tenant requests so
    # the AI fallback chain can use them. Tenant-specific keys remain isolated,
    # and writes to global rows require a validated superadmin session.
    op.execute("ALTER TABLE provider_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE provider_keys FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS provider_keys_read ON provider_keys")
    op.execute(
        f"""
        CREATE POLICY provider_keys_read ON provider_keys
        FOR SELECT TO lms_app
        USING (tenant_id IS NULL OR {_tenant_expression()})
        """
    )
    op.execute("DROP POLICY IF EXISTS provider_keys_tenant_write ON provider_keys")
    op.execute(
        f"""
        CREATE POLICY provider_keys_tenant_write ON provider_keys
        FOR ALL TO lms_app
        USING ({_tenant_expression()})
        WITH CHECK ({_tenant_expression()})
        """
    )
    op.execute("DROP POLICY IF EXISTS provider_keys_superadmin_session ON provider_keys")
    op.execute(
        """
        CREATE POLICY provider_keys_superadmin_session ON provider_keys
        FOR ALL TO lms_app
        USING (current_setting('app.is_superadmin', true) = 'true')
        WITH CHECK (current_setting('app.is_superadmin', true) = 'true')
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON provider_keys TO lms_app")


def downgrade() -> None:
    # Keep FORCE RLS enabled: removing it would re-open a tenant-isolation gap.
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_superadmin_session ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute("DROP POLICY IF EXISTS provider_keys_superadmin_session ON provider_keys")
    op.execute("DROP POLICY IF EXISTS provider_keys_tenant_write ON provider_keys")
    op.execute("DROP POLICY IF EXISTS provider_keys_read ON provider_keys")
