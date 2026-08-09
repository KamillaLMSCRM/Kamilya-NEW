"""Replace polymorphic candidate evidence trigger with table-safe guards.

Revision ID: 0101
Revises: 0100
"""

from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS candidate_campaign_snapshot_immutable ON candidate_assessment_campaigns")
    op.execute("DROP TRIGGER IF EXISTS candidate_attempt_evidence_immutable ON candidate_assessment_attempts")
    op.execute("DROP FUNCTION IF EXISTS protect_candidate_assessment_evidence()")
    op.execute(
        """
        CREATE FUNCTION protect_candidate_campaign_snapshot() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF (NEW.content_release_id, NEW.assessment_snapshot, NEW.snapshot_sha256)
                IS DISTINCT FROM
               (OLD.content_release_id, OLD.assessment_snapshot, OLD.snapshot_sha256)
            THEN
                RAISE EXCEPTION 'candidate campaign snapshot is immutable';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_candidate_attempt_evidence() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF OLD.status = 'submitted' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'submitted candidate attempt is immutable';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER candidate_campaign_snapshot_immutable BEFORE UPDATE ON "
        "candidate_assessment_campaigns FOR EACH ROW EXECUTE FUNCTION protect_candidate_campaign_snapshot()"
    )
    op.execute(
        "CREATE TRIGGER candidate_attempt_evidence_immutable BEFORE UPDATE ON "
        "candidate_assessment_attempts FOR EACH ROW EXECUTE FUNCTION protect_candidate_attempt_evidence()"
    )


def downgrade() -> None:
    # Amended 0099 creates the same table-specific guards.
    pass
