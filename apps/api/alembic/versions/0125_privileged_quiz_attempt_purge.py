"""Allow owner-authorized tenant purge of evidentiary quiz attempts.

Revision ID: 0125
Revises: 0124
Create Date: 2026-08-22

Evidence-bearing attempts remain immutable for ordinary UPDATE and DELETE
operations.  Only a DELETE in the database-owner, exact-tenant purge context
introduced by 0123 is accepted.
"""

from alembic import op

revision = "0125"
down_revision = "0124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_quiz_attempt_evidence_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.evidence_sha256 IS NOT NULL THEN
                IF TG_OP = 'DELETE'
                   AND public.privileged_tenant_purge_authorized(OLD.tenant_id) THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'Evidentiary quiz attempts are immutable'
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
        CREATE OR REPLACE FUNCTION public.prevent_quiz_attempt_evidence_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.evidence_sha256 IS NOT NULL THEN
                RAISE EXCEPTION 'Evidentiary quiz attempts are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp;
        """
    )
