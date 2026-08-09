"""Bounded candidate retention enforcement with de-identified aggregates.

Revision ID: 0102
Revises: 0101
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """DO $$ DECLARE retention_role record; BEGIN SELECT rolsuper,rolbypassrls INTO retention_role FROM pg_roles WHERE rolname='lms_candidate_retention'; IF NOT FOUND THEN RAISE EXCEPTION 'Required role lms_candidate_retention is missing; provision LOGIN NOSUPERUSER NOBYPASSRLS before 0102'; END IF; IF retention_role.rolsuper OR retention_role.rolbypassrls THEN RAISE EXCEPTION 'Role lms_candidate_retention must be NOSUPERUSER NOBYPASSRLS'; END IF; END $$"""
    )
    op.create_table(
        "candidate_assessment_retention_aggregates",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("candidates_redacted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_percent_sum", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_enforced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "candidates_redacted >= 0 AND submitted_attempts >= 0 AND passed_attempts >= 0 AND score_percent_sum >= 0",
            name="ck_candidate_retention_aggregate_nonnegative",
        ),
    )
    op.execute("ALTER TABLE candidate_assessment_retention_aggregates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE candidate_assessment_retention_aggregates FORCE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE ALL ON TABLE candidate_assessment_retention_aggregates FROM PUBLIC, lms_app, lms_candidate_retention"
    )
    op.execute("GRANT SELECT ON TABLE candidate_assessment_retention_aggregates TO lms_app")
    op.execute(
        """CREATE POLICY candidate_assessment_retention_aggregates_tenant ON candidate_assessment_retention_aggregates USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"""
    )
    op.execute(
        """
        CREATE FUNCTION enforce_expired_candidate_retention(p_limit integer DEFAULT 50)
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            candidate_row record;
            submitted_count integer;
            passed_count integer;
            score_sum bigint;
            processed integer := 0;
        BEGIN
            IF p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'candidate retention limit must be between 1 and 100';
            END IF;
            FOR candidate_row IN
                SELECT c.id, c.tenant_id, c.campaign_id
                FROM assessment_candidates c
                WHERE c.retention_until <= now() AND c.status <> 'deleted'
                ORDER BY c.retention_until, c.id
                FOR UPDATE SKIP LOCKED
                LIMIT p_limit
            LOOP
                SELECT count(*)::integer,
                       count(*) FILTER (WHERE a.passed IS TRUE)::integer,
                       COALESCE(sum(a.score_percent), 0)::bigint
                INTO submitted_count, passed_count, score_sum
                FROM candidate_assessment_attempts a
                WHERE a.tenant_id = candidate_row.tenant_id
                  AND a.campaign_id = candidate_row.campaign_id
                  AND a.candidate_id = candidate_row.id
                  AND a.status = 'submitted';

                INSERT INTO candidate_assessment_retention_aggregates(
                    tenant_id, campaign_id, candidates_redacted,
                    submitted_attempts, passed_attempts, score_percent_sum, last_enforced_at
                ) VALUES (
                    candidate_row.tenant_id, candidate_row.campaign_id, 1,
                    submitted_count, passed_count, score_sum, now()
                )
                ON CONFLICT (tenant_id, campaign_id) DO UPDATE SET
                    candidates_redacted = candidate_assessment_retention_aggregates.candidates_redacted + 1,
                    submitted_attempts = candidate_assessment_retention_aggregates.submitted_attempts + EXCLUDED.submitted_attempts,
                    passed_attempts = candidate_assessment_retention_aggregates.passed_attempts + EXCLUDED.passed_attempts,
                    score_percent_sum = candidate_assessment_retention_aggregates.score_percent_sum + EXCLUDED.score_percent_sum,
                    last_enforced_at = now();

                UPDATE candidate_access_credentials
                SET revoked_at = COALESCE(revoked_at, now()), locked_until = NULL
                WHERE tenant_id = candidate_row.tenant_id
                  AND campaign_id = candidate_row.campaign_id
                  AND candidate_id = candidate_row.id;

                DELETE FROM candidate_assessment_attempts
                WHERE tenant_id = candidate_row.tenant_id
                  AND campaign_id = candidate_row.campaign_id
                  AND candidate_id = candidate_row.id;

                UPDATE assessment_candidates
                SET first_name = 'Deleted', last_name = '', email = NULL, phone = NULL,
                    consented_at = NULL, status = 'deleted'
                WHERE id = candidate_row.id
                  AND tenant_id = candidate_row.tenant_id
                  AND campaign_id = candidate_row.campaign_id;
                processed := processed + 1;
            END LOOP;
            RETURN processed;
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION enforce_expired_candidate_retention(integer) FROM PUBLIC, lms_app")
    op.execute("GRANT USAGE ON SCHEMA public TO lms_candidate_retention")
    op.execute("GRANT EXECUTE ON FUNCTION enforce_expired_candidate_retention(integer) TO lms_candidate_retention")


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN IF EXISTS (SELECT 1 FROM candidate_assessment_retention_aggregates) THEN RAISE EXCEPTION '0102 downgrade refused: de-identified candidate retention aggregates exist and the PII redaction is irreversible'; END IF; END $$"""
    )
    op.execute("REVOKE EXECUTE ON FUNCTION enforce_expired_candidate_retention(integer) FROM lms_candidate_retention")
    op.execute("DROP FUNCTION IF EXISTS enforce_expired_candidate_retention(integer)")
    op.execute("REVOKE USAGE ON SCHEMA public FROM lms_candidate_retention")
    op.drop_table("candidate_assessment_retention_aggregates")
