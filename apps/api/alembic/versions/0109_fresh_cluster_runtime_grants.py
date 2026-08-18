"""Grant the application role access to legacy runtime tables.

Revision ID: 0109
Revises: 0108
Create Date: 2026-08-17

Migration 0033 intentionally grants only its fixed tenant-table inventory.
Four application tables sit outside that inventory and older managed clusters
received their grants through provider provisioning. A freshly migrated
PostgreSQL cluster therefore reaches the Alembic head while ``lms_app`` cannot
read the tenant row or the nested course/quiz content used by normal requests.

The two durable outbox tables are deliberately absent: they remain accessible
only through their bounded SECURITY DEFINER functions.
"""

from alembic import op

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None


RUNTIME_TABLES = (
    "tenants",
    "content_blocks",
    "questions",
    "quiz_choices",
)


def _validate_runtime_role() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            app_role RECORD;
        BEGIN
            SELECT rolsuper, rolbypassrls
              INTO app_role
              FROM pg_roles
             WHERE rolname = 'lms_app';

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Required role lms_app is missing; provision it before migration 0109';
            END IF;

            IF app_role.rolsuper OR app_role.rolbypassrls THEN
                RAISE EXCEPTION
                    'Role lms_app must be NOSUPERUSER NOBYPASSRLS before migration 0109';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _validate_runtime_role()
    op.execute("GRANT USAGE ON SCHEMA public TO lms_app")
    for table in RUNTIME_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO lms_app")


def downgrade() -> None:
    for table in RUNTIME_TABLES:
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {table} FROM lms_app")
