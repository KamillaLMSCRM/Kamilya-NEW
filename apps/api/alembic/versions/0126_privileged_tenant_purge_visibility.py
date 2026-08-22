"""Let the database owner see one exact tenant during an authorized purge.

Revision ID: 0126
Revises: 0125
Create Date: 2026-08-22

PostgreSQL applies SELECT visibility while evaluating DELETE statements under
row-level security.  The DELETE-only policies introduced in 0124 therefore
need matching visibility policies.  These policies remain bounded by the 0123
database-owner and transaction-local exact-tenant authorization helper.  They
do not grant table privileges or expose rows to the application role.
"""

from alembic import op

revision = "0126"
down_revision = "0125"
branch_labels = None
depends_on = None


PRIVILEGED_PURGE_TABLES = (
    "content_releases",
    "departments",
    "learning_path_assignments",
    "staff_import_mappings",
    "staff_import_session_events",
    "staff_import_sessions",
    "support_requests",
    "tenant_usage",
    "training_evidence_events",
    "training_evidence_signed_scans",
)

POLICY_NAME = "privileged_tenant_purge_select"


def upgrade() -> None:
    for table_name in PRIVILEGED_PURGE_TABLES:
        op.execute(
            f"""
            CREATE POLICY {POLICY_NAME}
            ON public.{table_name}
            FOR SELECT TO PUBLIC
            USING (
                public.privileged_tenant_purge_authorized(tenant_id)
            )
            """
        )


def downgrade() -> None:
    for table_name in reversed(PRIVILEGED_PURGE_TABLES):
        op.execute(
            f"DROP POLICY IF EXISTS {POLICY_NAME} ON public.{table_name}"
        )
