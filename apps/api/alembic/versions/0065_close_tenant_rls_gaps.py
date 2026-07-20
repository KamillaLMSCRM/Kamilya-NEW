"""Reconcile generated content and close tenant RLS gaps.

Revision ID: 0065
Revises: 0064
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

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


def _reconcile_generated_content() -> None:
    """Repair the legacy production table before applying tenant policies."""
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("generated_content")}

    if "course_id" not in columns:
        op.add_column(
            "generated_content",
            sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "tenant_id" not in columns:
        op.add_column(
            "generated_content",
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "title" not in columns:
        op.add_column(
            "generated_content",
            sa.Column("title", sa.String(), nullable=True),
        )

    op.execute(
        """
        UPDATE generated_content AS content
        SET tenant_id = COALESCE(content.tenant_id, job.tenant_id),
            course_id = COALESCE(content.course_id, job.course_id),
            title = COALESCE(
                NULLIF(content.title, ''),
                NULLIF(content.content ->> 'title', ''),
                NULLIF(content.content_type, ''),
                'Generated content'
            )
        FROM ai_jobs AS job
        WHERE job.id = content.job_id
          AND (content.tenant_id IS NULL OR content.course_id IS NULL OR content.title IS NULL)
        """
    )

    orphaned = bind.execute(
        sa.text("SELECT count(*) FROM generated_content WHERE tenant_id IS NULL")
    ).scalar_one()
    if orphaned:
        raise RuntimeError(
            "generated_content contains rows without a matching tenant in ai_jobs; "
            "repair those rows before applying migration 0065"
        )

    op.execute(
        """
        UPDATE generated_content
        SET title = COALESCE(
            NULLIF(title, ''),
            NULLIF(content ->> 'title', ''),
            NULLIF(content_type, ''),
            'Generated content'
        )
        WHERE title IS NULL OR title = ''
        """
    )
    op.alter_column("generated_content", "tenant_id", nullable=False)
    op.alter_column("generated_content", "title", nullable=False)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_generated_content_tenant_id "
        "ON generated_content (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_generated_content_course_id "
        "ON generated_content (course_id)"
    )


def upgrade() -> None:
    _reconcile_generated_content()

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
