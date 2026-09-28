"""Source actuality policy and immutable revision change reviews.

Revision ID: 0165
Revises: 0164
"""

import re

from alembic import op

revision = "0165"
down_revision = "0164"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe source-actuality schema")
    return f'"{schema}"'


def _revoke_other_roles(table: str) -> None:
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {table} FROM {role}'; END IF; END $$""")


def upgrade() -> None:
    schema = _schema()
    policies = f"{schema}.document_source_policies"
    reviews = f"{schema}.document_change_reviews"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"

    op.execute(f"""
        CREATE TABLE {policies} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            source_family_id uuid NOT NULL,
            owner_id uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            reviewed_at timestamptz,
            next_review_at timestamptz,
            created_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            updated_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_document_source_policy_family UNIQUE (tenant_id,source_family_id),
            CONSTRAINT ck_document_source_policy_review_window CHECK
                (reviewed_at IS NULL OR next_review_at IS NULL OR next_review_at >= reviewed_at)
        )
    """)
    op.execute(f"CREATE INDEX ix_document_source_policy_tenant_next_review ON {policies}(tenant_id,next_review_at)")
    op.execute(f"ALTER TABLE {policies} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {policies} FORCE ROW LEVEL SECURITY")
    policy_ownership = f"""EXISTS (SELECT 1 FROM {schema}.documents d
            WHERE d.tenant_id=document_source_policies.tenant_id
              AND d.source_family_id=document_source_policies.source_family_id)
        AND (document_source_policies.owner_id IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_source_policies.owner_id
              AND u.tenant_id=document_source_policies.tenant_id
              AND u.role='methodologist' AND u.is_active IS TRUE AND u.status='active'))
        AND (document_source_policies.created_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_source_policies.created_by
              AND u.tenant_id=document_source_policies.tenant_id))
        AND (document_source_policies.updated_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_source_policies.updated_by
              AND u.tenant_id=document_source_policies.tenant_id))"""
    op.execute(f"CREATE POLICY document_source_policies_tenant ON {policies} USING ({tenant}) WITH CHECK ({tenant} AND {policy_ownership})")
    _revoke_other_roles(policies)
    op.execute(f"GRANT SELECT, INSERT ON {policies} TO lms_app")
    op.execute(f"GRANT UPDATE (owner_id,reviewed_at,next_review_at,updated_by,updated_at) ON {policies} TO lms_app")

    op.execute(f"""
        CREATE TABLE {reviews} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            source_family_id uuid NOT NULL,
            previous_document_id uuid NOT NULL REFERENCES {schema}.documents(id) ON DELETE RESTRICT,
            new_document_id uuid NOT NULL REFERENCES {schema}.documents(id) ON DELETE RESTRICT,
            status varchar(16) NOT NULL DEFAULT 'pending' CHECK
                (status IN ('pending','processing','ready','resolved','failed')),
            added_fact_count integer NOT NULL DEFAULT 0,
            removed_fact_count integer NOT NULL DEFAULT 0,
            changed_fact_count integer NOT NULL DEFAULT 0,
            unchanged_fact_count integer NOT NULL DEFAULT 0,
            impacted_course_count integer NOT NULL DEFAULT 0,
            impacted_lesson_count integer NOT NULL DEFAULT 0,
            assessment_questions_requiring_review integer NOT NULL DEFAULT 0,
            impact_snapshot jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            analysis_error_code varchar(80),
            analysis_error_message text,
            decision varchar(32) CHECK (decision IS NULL OR decision IN
                ('no_learning_impact','update_future','update_and_retrain','suspend_old_assignments')),
            decision_reason text CHECK
                (decision_reason IS NULL OR length(decision_reason) BETWEEN 20 AND 4000),
            decision_snapshot jsonb,
            decided_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            decided_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_document_change_review_revision_pair UNIQUE
                (tenant_id,previous_document_id,new_document_id),
            CONSTRAINT ck_document_change_review_distinct_revisions CHECK
                (previous_document_id <> new_document_id),
            CONSTRAINT ck_document_change_review_nonnegative_counts CHECK
                (added_fact_count >= 0 AND removed_fact_count >= 0 AND changed_fact_count >= 0
                 AND unchanged_fact_count >= 0
                 AND impacted_course_count >= 0 AND impacted_lesson_count >= 0
                 AND assessment_questions_requiring_review >= 0),
            CONSTRAINT ck_document_change_review_resolution_state CHECK (
                (status='resolved' AND decision IS NOT NULL AND decision_reason IS NOT NULL
                 AND decided_at IS NOT NULL AND decision_snapshot IS NOT NULL)
                OR (status<>'resolved' AND decision IS NULL AND decision_reason IS NULL
                    AND decided_at IS NULL AND decision_snapshot IS NULL))
        )
    """)
    op.execute(f"CREATE INDEX ix_document_change_review_tenant_status_created ON {reviews}(tenant_id,status,created_at DESC)")
    op.execute(f"CREATE INDEX ix_document_change_review_tenant_family ON {reviews}(tenant_id,source_family_id)")
    op.execute(f"ALTER TABLE {reviews} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {reviews} FORCE ROW LEVEL SECURITY")
    review_ownership = f"""EXISTS (SELECT 1 FROM {schema}.documents old_d
            WHERE old_d.id=document_change_reviews.previous_document_id
              AND old_d.tenant_id=document_change_reviews.tenant_id
              AND old_d.source_family_id=document_change_reviews.source_family_id)
        AND EXISTS (SELECT 1 FROM {schema}.documents new_d
            WHERE new_d.id=document_change_reviews.new_document_id
              AND new_d.tenant_id=document_change_reviews.tenant_id
              AND new_d.source_family_id=document_change_reviews.source_family_id)
        AND (document_change_reviews.decided_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_change_reviews.decided_by
              AND u.tenant_id=document_change_reviews.tenant_id
              AND u.role='methodologist' AND u.is_active IS TRUE AND u.status='active'))"""
    op.execute(f"CREATE POLICY document_change_reviews_tenant ON {reviews} USING ({tenant}) WITH CHECK ({tenant} AND {review_ownership})")
    _revoke_other_roles(reviews)
    op.execute(f"GRANT SELECT, INSERT ON {reviews} TO lms_app")
    op.execute(f"GRANT UPDATE (status,added_fact_count,removed_fact_count,changed_fact_count,unchanged_fact_count,impacted_course_count,impacted_lesson_count,assessment_questions_requiring_review,impact_snapshot,analysis_error_code,analysis_error_message,decision,decision_reason,decision_snapshot,decided_by,decided_at,updated_at) ON {reviews} TO lms_app")
    op.execute(f"""
        CREATE FUNCTION {schema}.freeze_document_change_review_resolution()
        RETURNS trigger LANGUAGE plpgsql SET search_path={schema},pg_temp AS $$
        BEGIN
          IF OLD.status='resolved' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'resolved document change review is immutable'
              USING ERRCODE='check_violation';
          END IF;
          IF NEW.status='resolved' AND OLD.status<>'ready' THEN
            RAISE EXCEPTION 'document change review must be ready before resolution'
              USING ERRCODE='check_violation';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(f"""
        CREATE TRIGGER trg_freeze_document_change_review_resolution
        BEFORE UPDATE ON {reviews}
        FOR EACH ROW EXECUTE FUNCTION {schema}.freeze_document_change_review_resolution()
    """)


def downgrade() -> None:
    schema = _schema()
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_freeze_document_change_review_resolution "
        f"ON {schema}.document_change_reviews"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {schema}.freeze_document_change_review_resolution()")
    op.execute(f"DROP TABLE {schema}.document_change_reviews")
    op.execute(f"DROP TABLE {schema}.document_source_policies")
