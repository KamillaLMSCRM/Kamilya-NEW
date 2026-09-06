"""Tenant-owned follow-up decisions for immutable quiz question versions.

Revision ID: 0155
Revises: 0154
"""

import re

from alembic import op

revision = "0155"
down_revision = "0154"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe learning-insights schema")
    return f'"{schema}"'


def upgrade() -> None:
    schema = _schema()
    table = f"{schema}.learning_question_reviews"
    op.execute(f"""
        CREATE TABLE {table} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            course_id uuid NOT NULL REFERENCES {schema}.courses(id) ON DELETE CASCADE,
            question_key varchar(64) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'unreviewed',
            updated_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_learning_question_review UNIQUE (tenant_id,course_id,question_key),
            CONSTRAINT ck_learning_question_review_status CHECK
                (status IN ('unreviewed','train_staff','review_question','improve_material','resolved')),
            CONSTRAINT ck_learning_question_review_key CHECK (question_key ~ '^[0-9a-f]{{64}}$')
        )
    """)
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"
    ownership = f"""EXISTS (SELECT 1 FROM {schema}.courses c
        WHERE c.id=learning_question_reviews.course_id
          AND c.tenant_id=learning_question_reviews.tenant_id)
        AND (updated_by IS NULL OR EXISTS (SELECT 1 FROM {schema}.users u
        WHERE u.id=learning_question_reviews.updated_by
          AND u.tenant_id=learning_question_reviews.tenant_id))"""
    op.execute(
        f"CREATE POLICY learning_question_review_tenant ON {table} USING ({tenant}) WITH CHECK ({tenant} AND {ownership})"
    )
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app")
    # Supabase default privileges must not expose this internal employee report.
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            REVOKE ALL ON {table} FROM {role};
          END IF;
        END $$""")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app")


def downgrade() -> None:
    op.execute(f"DROP TABLE {_schema()}.learning_question_reviews")
