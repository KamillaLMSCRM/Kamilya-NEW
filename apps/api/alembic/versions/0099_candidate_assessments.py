"""Isolated candidate assessment domain.

Revision ID: 0099
Revises: 0098
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None

TABLES = (
    "candidate_assessment_campaigns",
    "assessment_candidates",
    "candidate_access_credentials",
    "candidate_assessment_attempts",
)


def _tenant_table(name: str) -> None:
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {name} FROM PUBLIC, lms_app")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {name} TO lms_app")
    op.execute(
        f"CREATE POLICY {name}_tenant ON {name} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "candidate_assessment_campaigns",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "content_release_id", uuid, sa.ForeignKey("content_releases.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("assessment_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('draft','active','closed')", name="ck_candidate_campaign_status"),
        sa.CheckConstraint("attempt_limit BETWEEN 1 AND 10", name="ck_candidate_campaign_attempt_limit"),
        sa.CheckConstraint("retention_days BETWEEN 1 AND 3650", name="ck_candidate_campaign_retention"),
    )
    op.create_table(
        "assessment_candidates",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", uuid, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "campaign_id", uuid, sa.ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("email", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="invited"),
        sa.Column("consented_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('invited','active','completed','withdrawn','deleted')", name="ck_assessment_candidate_status"
        ),
    )
    op.create_table(
        "candidate_access_credentials",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column(
            "campaign_id", uuid, sa.ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("candidate_id", uuid, sa.ForeignKey("assessment_candidates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "uq_candidate_active_credential",
        "candidate_access_credentials",
        ["candidate_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "candidate_assessment_attempts",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column(
            "campaign_id", uuid, sa.ForeignKey("candidate_assessment_campaigns.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("candidate_id", uuid, sa.ForeignKey("assessment_candidates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="started"),
        sa.Column("assessment_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("answers_sha256", sa.String(64)),
        sa.Column("earned_points", sa.Integer()),
        sa.Column("total_points", sa.Integer()),
        sa.Column("score_percent", sa.Integer()),
        sa.Column("passed", sa.Boolean()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "candidate_id", "campaign_id", "attempt_number", name="uq_candidate_campaign_attempt_number"
        ),
        sa.CheckConstraint("status IN ('started','submitted')", name="ck_candidate_attempt_status"),
    )
    for table in TABLES:
        _tenant_table(table)
    op.execute(
        """
        CREATE FUNCTION validate_candidate_campaign_ownership() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            IF (
                NOT EXISTS (
                    SELECT 1 FROM content_releases r
                    WHERE r.id = NEW.content_release_id AND r.tenant_id = NEW.tenant_id
                )
                OR NOT EXISTS (
                    SELECT 1 FROM users u
                    WHERE u.id = NEW.created_by
                      AND u.tenant_id = NEW.tenant_id
                      AND (
                          u.role = 'methodologist'
                          OR EXISTS (
                              SELECT 1 FROM user_roles ur
                              WHERE ur.user_id = u.id
                                AND ur.tenant_id = NEW.tenant_id
                                AND ur.role = 'methodologist'
                          )
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
        CREATE FUNCTION validate_assessment_candidate_ownership() RETURNS trigger
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
        CREATE FUNCTION validate_candidate_credential_ownership() RETURNS trigger
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
        CREATE FUNCTION validate_candidate_attempt_ownership() RETURNS trigger
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
    op.execute(
        """CREATE FUNCTION protect_candidate_campaign_snapshot() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN IF (NEW.content_release_id,NEW.assessment_snapshot,NEW.snapshot_sha256) IS DISTINCT FROM (OLD.content_release_id,OLD.assessment_snapshot,OLD.snapshot_sha256) THEN RAISE EXCEPTION 'candidate campaign snapshot is immutable'; END IF; RETURN NEW; END $$"""
    )
    op.execute(
        """CREATE FUNCTION protect_candidate_attempt_evidence() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN IF OLD.status='submitted' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'submitted candidate attempt is immutable'; END IF; RETURN NEW; END $$"""
    )
    op.execute(
        "CREATE TRIGGER candidate_campaign_snapshot_immutable BEFORE UPDATE ON candidate_assessment_campaigns FOR EACH ROW EXECUTE FUNCTION protect_candidate_campaign_snapshot()"
    )
    op.execute(
        "CREATE TRIGGER candidate_attempt_evidence_immutable BEFORE UPDATE ON candidate_assessment_attempts FOR EACH ROW EXECUTE FUNCTION protect_candidate_attempt_evidence()"
    )
    op.execute(
        """CREATE FUNCTION lookup_candidate_assessment_tenant(access_token_hash text) RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$ SELECT tenant_id FROM candidate_access_credentials WHERE token_hash=access_token_hash AND revoked_at IS NULL AND expires_at>now() LIMIT 1 $$"""
    )
    op.execute("REVOKE ALL ON FUNCTION lookup_candidate_assessment_tenant(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lookup_candidate_assessment_tenant(text) TO lms_app")


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN IF EXISTS (SELECT 1 FROM candidate_assessment_campaigns) OR EXISTS (SELECT 1 FROM assessment_candidates) OR EXISTS (SELECT 1 FROM candidate_access_credentials) OR EXISTS (SELECT 1 FROM candidate_assessment_attempts) THEN RAISE EXCEPTION '0099 downgrade refused: candidate PII or attempt evidence exists; run and approve the candidate assessment archive/redaction procedure, then empty all four tables'; END IF; END $$"""
    )
    op.execute("DROP FUNCTION IF EXISTS lookup_candidate_assessment_tenant(text)")
    op.execute("DROP FUNCTION IF EXISTS protect_candidate_attempt_evidence() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS protect_candidate_campaign_snapshot() CASCADE")
    for function in (
        "validate_candidate_attempt_ownership",
        "validate_candidate_credential_ownership",
        "validate_assessment_candidate_ownership",
        "validate_candidate_campaign_ownership",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}() CASCADE")
    for table in reversed(TABLES):
        op.drop_table(table)
