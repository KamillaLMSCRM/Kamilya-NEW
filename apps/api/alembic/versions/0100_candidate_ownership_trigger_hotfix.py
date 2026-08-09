"""Replace the polymorphic candidate ownership trigger with table-safe guards.

Revision ID: 0100
Revises: 0099
"""

from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "candidate_assessment_campaigns",
        "assessment_candidates",
        "candidate_access_credentials",
        "candidate_assessment_attempts",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_ownership ON {table}")
    op.execute("DROP FUNCTION IF EXISTS validate_candidate_assessment_ownership()")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_candidate_campaign_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM content_releases r
                WHERE r.id = NEW.content_release_id AND r.tenant_id = NEW.tenant_id
            ) OR NOT EXISTS (
                SELECT 1 FROM users u
                WHERE u.id = NEW.created_by AND u.tenant_id = NEW.tenant_id
                  AND (
                      u.role = 'methodologist'
                      OR EXISTS (
                          SELECT 1 FROM user_roles ur
                          WHERE ur.user_id = u.id
                            AND ur.tenant_id = NEW.tenant_id
                            AND ur.role = 'methodologist'
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'candidate campaign tenant/release/creator mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_assessment_candidate_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM candidate_assessment_campaigns c
                WHERE c.id = NEW.campaign_id AND c.tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'candidate tenant/campaign mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_candidate_credential_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM assessment_candidates c
                JOIN candidate_assessment_campaigns p ON p.id = c.campaign_id
                WHERE c.id = NEW.candidate_id
                  AND c.tenant_id = NEW.tenant_id
                  AND c.campaign_id = NEW.campaign_id
                  AND p.id = NEW.campaign_id
                  AND p.tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'candidate credential tenant/candidate/campaign mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_candidate_attempt_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM assessment_candidates c
                JOIN candidate_assessment_campaigns p ON p.id = c.campaign_id
                WHERE c.id = NEW.candidate_id
                  AND c.tenant_id = NEW.tenant_id
                  AND c.campaign_id = NEW.campaign_id
                  AND p.id = NEW.campaign_id
                  AND p.tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'candidate attempt tenant/candidate/campaign mismatch';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    for table, function in (
        ("candidate_assessment_campaigns", "validate_candidate_campaign_ownership"),
        ("assessment_candidates", "validate_assessment_candidate_ownership"),
        ("candidate_access_credentials", "validate_candidate_credential_ownership"),
        ("candidate_assessment_attempts", "validate_candidate_attempt_ownership"),
    ):
        op.execute(
            f"CREATE TRIGGER {table}_ownership BEFORE INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )


def downgrade() -> None:
    # 0099 in this source tree creates the same table-specific guards.  The
    # hotfix only repairs databases that had already applied the earlier
    # polymorphic implementation, so no schema reversal is required.
    pass
