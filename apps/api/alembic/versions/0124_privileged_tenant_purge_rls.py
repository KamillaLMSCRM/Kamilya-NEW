"""Allow the database owner to delete one authorized tenant through FORCE RLS.

Revision ID: 0124
Revises: 0123
Create Date: 2026-08-22

The policies added here are DELETE-only.  They do not expose tenant rows for
SELECT, permit INSERT or UPDATE, grant a callable purge entry point, or weaken
FORCE ROW LEVEL SECURITY.  The 0123 helper remains the authorization boundary:
the transaction tenant must match and both current_user and session_user must
be the current database owner.
"""

from alembic import op

revision = "0124"
down_revision = "0123"
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

POLICY_NAME = "privileged_tenant_purge_delete"


def upgrade() -> None:
    for table_name in PRIVILEGED_PURGE_TABLES:
        op.execute(
            f"""
            CREATE POLICY {POLICY_NAME}
            ON public.{table_name}
            FOR DELETE TO PUBLIC
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
