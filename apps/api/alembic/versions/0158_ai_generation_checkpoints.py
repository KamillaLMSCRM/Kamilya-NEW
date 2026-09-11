"""Add durable tenant-isolated AI generation checkpoints.

Revision ID: 0158
Revises: 0157
"""

import re

from alembic import op

revision = "0158"
down_revision = "0157"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe ai-generation-checkpoints schema")
    return f'"{schema}"'


def _tenant_policy(policy_name: str, table: str) -> str:
    return (
        f"CREATE POLICY {policy_name} ON {table} FOR ALL TO lms_app "
        "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _restrict_table(table: str, policy_name: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(_tenant_policy(policy_name, table))
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            REVOKE ALL ON {table} FROM {role};
          END IF;
        END $$""")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app")


def upgrade() -> None:
    schema = _schema()
    runs = f"{schema}.ai_generation_runs"
    checkpoints = f"{schema}.ai_generation_lesson_checkpoints"
    ai_jobs = f"{schema}.ai_jobs"
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_jobs_tenant_id_id ON {ai_jobs} (tenant_id, id)"
    )
    op.execute(f"""
        CREATE TABLE {runs} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            generation_key varchar(160) NOT NULL,
            plan_revision varchar(160) NOT NULL,
            source_job_id varchar(255) NOT NULL,
            plan_payload jsonb NOT NULL,
            lease_owner varchar(160),
            lease_expires_at timestamptz,
            lease_duration_seconds smallint NOT NULL DEFAULT 300,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ai_generation_runs_tenant_generation UNIQUE (tenant_id, generation_key),
            CONSTRAINT uq_ai_generation_runs_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT fk_ai_generation_runs_tenant_job FOREIGN KEY (tenant_id, source_job_id)
                REFERENCES {schema}.ai_jobs(tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT ck_ai_generation_runs_generation_key CHECK (length(btrim(generation_key)) BETWEEN 1 AND 160),
            CONSTRAINT ck_ai_generation_runs_plan_revision CHECK (length(btrim(plan_revision)) BETWEEN 1 AND 160),
            CONSTRAINT ck_ai_generation_runs_payload_object CHECK (jsonb_typeof(plan_payload) = 'object'),
            CONSTRAINT ck_ai_generation_runs_lease_pair CHECK (
                (lease_owner IS NULL AND lease_expires_at IS NULL)
                OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
            ),
            CONSTRAINT ck_ai_generation_runs_lease_owner CHECK (
                lease_owner IS NULL OR length(btrim(lease_owner)) BETWEEN 1 AND 160
            ),
            CONSTRAINT ck_ai_generation_runs_lease_duration CHECK (lease_duration_seconds BETWEEN 1 AND 900)
        )
    """)
    op.execute(
        f"CREATE INDEX ix_ai_generation_runs_tenant_source_job ON {runs} (tenant_id, source_job_id)"
    )
    op.execute(
        f"CREATE INDEX ix_ai_generation_runs_lease_expiry ON {runs} (lease_expires_at) WHERE lease_expires_at IS NOT NULL"
    )
    _restrict_table(runs, "ai_generation_runs_tenant")

    op.execute(f"""
        CREATE TABLE {checkpoints} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            generation_run_id uuid NOT NULL,
            module_key varchar(160) NOT NULL,
            lesson_key varchar(160) NOT NULL,
            module_order integer NOT NULL,
            lesson_order integer NOT NULL,
            content_status varchar(16) NOT NULL DEFAULT 'pending',
            review_status varchar(16) NOT NULL DEFAULT 'pending',
            assessment_status varchar(16) NOT NULL DEFAULT 'pending',
            content_payload jsonb,
            review_payload jsonb,
            assessment_payload jsonb,
            lease_owner varchar(160),
            lease_expires_at timestamptz,
            lease_duration_seconds smallint NOT NULL DEFAULT 300,
            attempt_count integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ai_generation_lesson_identity UNIQUE (tenant_id, generation_run_id, module_key, lesson_key),
            CONSTRAINT fk_ai_generation_checkpoint_tenant_run FOREIGN KEY (tenant_id, generation_run_id)
                REFERENCES {runs}(tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_ai_generation_checkpoint_module_key CHECK (length(btrim(module_key)) BETWEEN 1 AND 160),
            CONSTRAINT ck_ai_generation_checkpoint_lesson_key CHECK (length(btrim(lesson_key)) BETWEEN 1 AND 160),
            CONSTRAINT ck_ai_generation_checkpoint_orders CHECK (module_order >= 0 AND lesson_order >= 0),
            CONSTRAINT ck_ai_generation_checkpoint_content_status CHECK (content_status IN ('pending', 'completed', 'failed')),
            CONSTRAINT ck_ai_generation_checkpoint_review_status CHECK (review_status IN ('pending', 'completed', 'failed')),
            CONSTRAINT ck_ai_generation_checkpoint_assessment_status CHECK (assessment_status IN ('pending', 'completed', 'failed')),
            CONSTRAINT ck_ai_generation_checkpoint_content_payload CHECK (
                content_status <> 'completed' OR content_payload IS NOT NULL
            ),
            CONSTRAINT ck_ai_generation_checkpoint_review_payload CHECK (
                review_status <> 'completed' OR review_payload IS NOT NULL
            ),
            CONSTRAINT ck_ai_generation_checkpoint_assessment_payload CHECK (
                assessment_status <> 'completed' OR assessment_payload IS NOT NULL
            ),
            CONSTRAINT ck_ai_generation_checkpoint_lease_pair CHECK (
                (lease_owner IS NULL AND lease_expires_at IS NULL)
                OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
            ),
            CONSTRAINT ck_ai_generation_checkpoint_lease_owner CHECK (
                lease_owner IS NULL OR length(btrim(lease_owner)) BETWEEN 1 AND 160
            ),
            CONSTRAINT ck_ai_generation_checkpoint_lease_duration CHECK (
                lease_duration_seconds BETWEEN 1 AND 900
            ),
            CONSTRAINT ck_ai_generation_checkpoint_attempt_count CHECK (
                attempt_count >= 0
            )
        )
    """)
    op.execute(
        f"CREATE INDEX ix_ai_generation_checkpoint_pending ON {checkpoints} "
        "(tenant_id, generation_run_id, module_order, lesson_order) "
        "WHERE content_status <> 'completed' OR review_status <> 'completed' "
        "OR assessment_status <> 'completed'"
    )
    _restrict_table(checkpoints, "ai_generation_lesson_checkpoints_tenant")

    op.execute(f"""
        CREATE FUNCTION {schema}.prevent_ai_generation_identity_change()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.generation_key IS DISTINCT FROM OLD.generation_key
               OR NEW.plan_revision IS DISTINCT FROM OLD.plan_revision
               OR NEW.source_job_id IS DISTINCT FROM OLD.source_job_id THEN
                RAISE EXCEPTION 'ai_generation_run_identity_immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(f"""
        CREATE TRIGGER ai_generation_runs_identity_immutable
        BEFORE UPDATE ON {runs}
        FOR EACH ROW EXECUTE FUNCTION {schema}.prevent_ai_generation_identity_change()
    """)
    op.execute(f"""
        CREATE FUNCTION {schema}.prevent_ai_generation_checkpoint_identity_change()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.generation_run_id IS DISTINCT FROM OLD.generation_run_id
               OR NEW.module_key IS DISTINCT FROM OLD.module_key
               OR NEW.lesson_key IS DISTINCT FROM OLD.lesson_key
               OR NEW.module_order IS DISTINCT FROM OLD.module_order
               OR NEW.lesson_order IS DISTINCT FROM OLD.lesson_order THEN
                RAISE EXCEPTION 'ai_generation_checkpoint_identity_immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(f"""
        CREATE TRIGGER ai_generation_lesson_checkpoints_identity_immutable
        BEFORE UPDATE ON {checkpoints}
        FOR EACH ROW EXECUTE FUNCTION {schema}.prevent_ai_generation_checkpoint_identity_change()
    """)


def downgrade() -> None:
    schema = _schema()
    op.execute(f"DROP TABLE {schema}.ai_generation_lesson_checkpoints")
    op.execute(f"DROP TABLE {schema}.ai_generation_runs")
    op.execute(f"DROP FUNCTION {schema}.prevent_ai_generation_checkpoint_identity_change()")
    op.execute(f"DROP FUNCTION {schema}.prevent_ai_generation_identity_change()")
    op.execute(f"DROP INDEX IF EXISTS {schema}.uq_ai_jobs_tenant_id_id")
