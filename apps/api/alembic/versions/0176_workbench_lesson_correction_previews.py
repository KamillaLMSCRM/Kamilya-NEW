"""Owned immutable draft-lesson correction previews, not application receipts.

Revision ID: 0176
Revises: 0175
"""

import re

from sqlalchemy import text

from alembic import op

revision = "0176"
down_revision = "0175"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe correction preview schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    table = f'"{schema}".workbench_lesson_correction_plans'
    guard = f'"{schema}".guard_lesson_correction_plan'
    op.execute(f"""CREATE TABLE {table} (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES "{schema}".tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL,
        request_key uuid NOT NULL,
        request_digest varchar(64) NOT NULL CHECK (request_digest ~ '^[a-f0-9]{{64}}$'),
        snapshot jsonb NOT NULL,
        status varchar(16) NOT NULL DEFAULT 'pending',
        proposal jsonb,
        fingerprint varchar(64) CHECK (fingerprint ~ '^[a-f0-9]{{64}}$'),
        error_code varchar(64) CHECK (error_code ~ '^[a-z_]+$'),
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        finished_at timestamptz,
        CONSTRAINT uq_lesson_correction_request UNIQUE (tenant_id,actor_id,request_key),
        CONSTRAINT ck_lesson_correction_owner CHECK (COALESCE(
            snapshot->'context'->>'tenant_id'=tenant_id::text AND snapshot->>'actor_id'=actor_id::text
            AND snapshot->>'plan_id'=id::text AND (snapshot->>'expires_at')::timestamptz=expires_at,
            false)),
        CONSTRAINT ck_lesson_correction_lifetime CHECK (expires_at>created_at AND expires_at<=created_at+interval '15 minutes'),
        CONSTRAINT ck_lesson_correction_state CHECK (
            (status='pending' AND proposal IS NULL AND fingerprint IS NULL AND error_code IS NULL AND finished_at IS NULL)
            OR (status='ready' AND proposal IS NOT NULL AND fingerprint IS NOT NULL AND error_code IS NULL AND finished_at IS NOT NULL)
            OR (status='failed' AND proposal IS NULL AND fingerprint IS NULL AND error_code IS NOT NULL AND finished_at IS NOT NULL))
    )""")
    op.execute(f"CREATE INDEX ix_lesson_correction_owner ON {table}(tenant_id,actor_id,created_at)")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    owner = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    superadmin = "COALESCE(current_setting('app.is_superadmin',true),'false')='true'"
    eligible = f"""EXISTS (SELECT 1 FROM "{schema}".users u
        WHERE u.id=workbench_lesson_correction_plans.actor_id AND u.tenant_id=workbench_lesson_correction_plans.tenant_id
        AND u.is_active IS TRUE AND u.status='active'
        AND (u.role='methodologist' OR EXISTS (SELECT 1 FROM "{schema}".user_roles r
            WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist')))"""
    op.execute(
        f"CREATE POLICY correction_read ON {table} FOR SELECT TO lms_app USING ({tenant} AND ({owner} OR {superadmin}))"
    )
    op.execute(
        f"CREATE POLICY correction_insert ON {table} FOR INSERT TO lms_app WITH CHECK ({tenant} AND {owner} AND {eligible})"
    )
    op.execute(
        f"CREATE POLICY correction_update ON {table} FOR UPDATE TO lms_app USING ({tenant} AND {owner}) WITH CHECK ({tenant} AND {owner} AND (status='failed' OR {eligible}))"
    )
    op.execute(f"CREATE POLICY correction_purge ON {table} FOR DELETE TO lms_app USING ({tenant} AND {superadmin})")
    op.execute(f"""CREATE FUNCTION {guard}() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF TG_OP='INSERT' THEN
            IF NEW.status <> 'pending' OR NEW.proposal IS NOT NULL OR NEW.fingerprint IS NOT NULL
                OR NEW.error_code IS NOT NULL OR NEW.finished_at IS NOT NULL THEN
                RAISE EXCEPTION 'Correction admission must start pending';
            END IF;
            NEW.created_at := clock_timestamp();
        ELSE
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.request_key IS DISTINCT FROM OLD.request_key
                OR NEW.request_digest IS DISTINCT FROM OLD.request_digest OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
                OR NEW.expires_at IS DISTINCT FROM OLD.expires_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Correction context is immutable';
            END IF;
            IF OLD.status <> 'pending' THEN
                IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'Correction result is immutable'; END IF;
            ELSE
                IF NEW.status NOT IN ('ready','failed') THEN RAISE EXCEPTION 'Correction must finish once'; END IF;
                IF NEW.status='ready' AND OLD.expires_at<=clock_timestamp() THEN
                    RAISE EXCEPTION 'Correction preview expired';
                END IF;
                NEW.finished_at := clock_timestamp();
            END IF;
        END IF;
        RETURN NEW;
        END $$""")
    op.execute(
        f"CREATE TRIGGER lesson_correction_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {guard}()"
    )
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app")
    op.execute(f"REVOKE ALL ON FUNCTION {guard}() FROM PUBLIC,lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {table} FROM {role}';
            EXECUTE 'REVOKE ALL ON FUNCTION {guard}() FROM {role}';
        END IF; END $$""")
    op.execute(f"GRANT SELECT,INSERT,DELETE ON {table} TO lms_app")
    op.execute(f"GRANT UPDATE (status,proposal,fingerprint,error_code) ON {table} TO lms_app")


def downgrade() -> None:
    schema = _schema()
    table = f'"{schema}".workbench_lesson_correction_plans'
    if op.get_bind().execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
        raise RuntimeError("Correction downgrade requires an empty table; preserve previews")
    op.execute(f"DROP TABLE {table}")
    op.execute(f'DROP FUNCTION "{schema}".guard_lesson_correction_plan()')
