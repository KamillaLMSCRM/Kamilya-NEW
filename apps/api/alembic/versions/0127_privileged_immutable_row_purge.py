"""Allow exact-owner tenant purge through two remaining immutable guards.

Revision ID: 0127
Revises: 0126
Create Date: 2026-08-22

Staff-import events and published content releases remain immutable for every
ordinary operation.  A DELETE is accepted only inside the database-owner,
transaction-local exact-tenant purge context introduced in 0123.
"""

from alembic import op

revision = "0127"
down_revision = "0126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_staff_import_session_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND public.privileged_tenant_purge_authorized(OLD.tenant_id) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'staff import session events are append-only'
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_content_release_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND public.privileged_tenant_purge_authorized(OLD.tenant_id) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Published course releases are immutable'
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_content_release_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Published course releases are immutable'
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_staff_import_session_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'staff import session events are append-only'
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
