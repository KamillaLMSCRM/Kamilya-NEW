"""Immutable document previews joined to one admitted generation job.

Revision ID: 0175
Revises: 0174
"""

import re

from sqlalchemy import text

from alembic import op

revision = "0175"
down_revision = "0174"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe document workbench schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    table = f'"{schema}".workbench_document_plans'
    op.execute(f"""CREATE TABLE {table} (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES "{schema}".tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL,
        snapshot jsonb NOT NULL,
        fingerprint varchar(64) NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{{64}}$'),
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        status varchar(16) NOT NULL DEFAULT 'ready',
        job_id varchar REFERENCES "{schema}".ai_jobs(id),
        admitted_at timestamptz,
        CONSTRAINT ck_workbench_document_state CHECK (
            (status='ready' AND job_id IS NULL AND admitted_at IS NULL) OR
            (status='submitted' AND job_id IS NOT NULL AND admitted_at IS NOT NULL)),
        CONSTRAINT ck_workbench_document_owner CHECK (COALESCE(
            snapshot->>'tenant_id'=tenant_id::text AND snapshot->>'actor_id'=actor_id::text
            AND snapshot->>'plan_id'=id::text
            AND (snapshot->>'expires_at')::timestamptz=expires_at, false))
    )""")
    op.execute(f"CREATE UNIQUE INDEX uq_workbench_document_job ON {table}(job_id)")
    op.execute(f"CREATE INDEX ix_workbench_document_owner ON {table}(tenant_id,actor_id,created_at)")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    owner = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    superadmin = "COALESCE(current_setting('app.is_superadmin',true),'false')='true'"
    eligible = f"""EXISTS (SELECT 1 FROM "{schema}".users u
        WHERE u.id=workbench_document_plans.actor_id AND u.tenant_id=workbench_document_plans.tenant_id
        AND u.is_active IS TRUE AND u.status='active'
        AND (u.role='methodologist' OR EXISTS (SELECT 1 FROM "{schema}".user_roles r
            WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist')))"""
    op.execute(f"CREATE POLICY document_plan_read ON {table} FOR SELECT TO lms_app USING ({tenant} AND ({owner} OR {superadmin}))")
    op.execute(f"CREATE POLICY document_plan_insert ON {table} FOR INSERT TO lms_app WITH CHECK ({tenant} AND {owner} AND {eligible})")
    op.execute(f"CREATE POLICY document_plan_update ON {table} FOR UPDATE TO lms_app USING ({tenant} AND {owner}) WITH CHECK ({tenant} AND {owner} AND {eligible})")
    op.execute(f"CREATE POLICY document_plan_purge ON {table} FOR DELETE TO lms_app USING ({tenant} AND {superadmin})")
    op.execute(f"""CREATE FUNCTION "{schema}".guard_document_plan() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF TG_OP='INSERT' THEN
            IF NEW.status <> 'ready' OR NEW.job_id IS NOT NULL OR NEW.admitted_at IS NOT NULL THEN
                RAISE EXCEPTION 'Document preview must start ready';
            END IF;
        ELSE
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
                OR NEW.fingerprint IS DISTINCT FROM OLD.fingerprint OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Document preview is immutable';
            END IF;
            IF OLD.status='submitted' THEN
                IF NEW.status IS DISTINCT FROM OLD.status OR NEW.job_id IS DISTINCT FROM OLD.job_id
                    OR NEW.admitted_at IS DISTINCT FROM OLD.admitted_at THEN
                    RAISE EXCEPTION 'Submitted document plan is immutable';
                END IF;
            ELSIF NEW.status='submitted' THEN
                IF OLD.expires_at <= clock_timestamp() THEN
                    RAISE EXCEPTION 'Document preview expired';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM "{schema}".ai_jobs j WHERE j.id=NEW.job_id
                    AND j.user_id=NEW.actor_id AND j.tenant_id=NEW.tenant_id
                    AND j.course_id IS NULL
                    AND j.params->'source_analysis'->>'generation_engine'='evidence_v2'
                    AND j.params::jsonb->'documents'=NEW.snapshot->'generation'->'documents') THEN
                    RAISE EXCEPTION 'Document job owner mismatch';
                END IF;
                NEW.admitted_at := clock_timestamp();
            ELSIF NEW.job_id IS DISTINCT FROM OLD.job_id OR NEW.admitted_at IS DISTINCT FROM OLD.admitted_at THEN
                RAISE EXCEPTION 'Document admission requires submitted state';
            END IF;
        END IF;
        RETURN NEW;
        END $$""")
    op.execute(f'CREATE TRIGGER document_plan_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION "{schema}".guard_document_plan()')
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app")
    op.execute(f'REVOKE ALL ON FUNCTION "{schema}".guard_document_plan() FROM PUBLIC,lms_app')
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {table} FROM {role}';
            EXECUTE 'REVOKE ALL ON FUNCTION "{schema}".guard_document_plan() FROM {role}';
        END IF; END $$""")
    op.execute(f"GRANT SELECT,INSERT,DELETE ON {table} TO lms_app")
    op.execute(f"GRANT UPDATE (status,job_id) ON {table} TO lms_app")


def downgrade() -> None:
    schema = _schema()
    table = f'"{schema}".workbench_document_plans'
    if op.get_bind().execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
        raise RuntimeError("Document plan downgrade requires an empty table; preserve admitted job links")
    op.execute(f"DROP TABLE {table}")
    op.execute(f'DROP FUNCTION "{schema}".guard_document_plan()')
