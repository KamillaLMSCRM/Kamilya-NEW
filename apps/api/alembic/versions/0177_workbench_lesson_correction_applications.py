"""Immutable confirmed draft-correction application receipts.

Revision ID: 0177
Revises: 0176
"""

import re

from sqlalchemy import text

from alembic import op

revision = "0177"
down_revision = "0176"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe correction application schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    table = f'"{schema}".workbench_lesson_correction_applications'
    guard = f'"{schema}".guard_lesson_correction_application'
    op.execute(f"""CREATE TABLE {table} (
        plan_id uuid PRIMARY KEY REFERENCES "{schema}".workbench_lesson_correction_plans(id) ON DELETE CASCADE,
        tenant_id uuid NOT NULL REFERENCES "{schema}".tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL,
        course_id uuid NOT NULL,
        lesson_id uuid NOT NULL,
        revision integer NOT NULL CHECK (revision>0),
        fingerprint varchar(64) NOT NULL CHECK (fingerprint ~ '^[a-f0-9]{{64}}$'),
        before_sha256 varchar(64) NOT NULL CHECK (before_sha256 ~ '^[a-f0-9]{{64}}$'),
        after_sha256 varchar(64) NOT NULL CHECK (after_sha256 ~ '^[a-f0-9]{{64}}$'),
        applied_at timestamptz NOT NULL DEFAULT now(),
        CHECK (before_sha256<>after_sha256)
    )""")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    owner = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    superadmin = "COALESCE(current_setting('app.is_superadmin',true),'false')='true'"
    eligible = f"""EXISTS (SELECT 1 FROM "{schema}".users u
        WHERE u.id=workbench_lesson_correction_applications.actor_id
        AND u.tenant_id=workbench_lesson_correction_applications.tenant_id
        AND u.is_active IS TRUE AND u.status='active'
        AND (u.role='methodologist' OR EXISTS (SELECT 1 FROM "{schema}".user_roles r
            WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist')))"""
    op.execute(
        f"CREATE POLICY correction_application_read ON {table} FOR SELECT TO lms_app USING ({tenant} AND {owner})"
    )
    op.execute(
        f"CREATE POLICY correction_application_insert ON {table} FOR INSERT TO lms_app WITH CHECK ({tenant} AND {owner} AND {eligible})"
    )
    op.execute(
        f"CREATE POLICY correction_application_purge ON {table} FOR DELETE TO lms_app USING ({tenant} AND {superadmin})"
    )
    op.execute(f"""CREATE FUNCTION {guard}() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Correction application is immutable'; END IF;
        IF NOT EXISTS (
            SELECT 1 FROM "{schema}".workbench_lesson_correction_plans p
            JOIN "{schema}".lessons l ON l.id=NEW.lesson_id
            JOIN "{schema}".modules m ON m.id=l.module_id
            JOIN "{schema}".courses c ON c.id=m.course_id
            WHERE p.id=NEW.plan_id AND p.status='ready'
            AND p.tenant_id=NEW.tenant_id AND p.actor_id=NEW.actor_id
            AND l.tenant_id=NEW.tenant_id AND m.tenant_id=NEW.tenant_id AND c.tenant_id=NEW.tenant_id
            AND c.id=NEW.course_id AND c.status='draft' AND c.delivery_type='native'
            AND l.content_type='text' AND l.published_at IS NULL
            AND c.review_status='pending' AND c.reviewed_by IS NULL AND c.reviewed_at IS NULL AND c.review_comment IS NULL
            AND l.source_validation_status='needs_review'
            AND p.fingerprint=NEW.fingerprint
            AND (p.snapshot->>'revision')::integer=NEW.revision
            AND p.snapshot->'context'->>'course_id'=NEW.course_id::text
            AND p.snapshot->'context'->>'lesson_id'=NEW.lesson_id::text
            AND p.snapshot->'context'->>'module_id'=m.id::text
            AND p.expires_at>clock_timestamp()
            AND NEW.before_sha256=encode(sha256(convert_to(p.snapshot->'context'->>'content','UTF8')),'hex')
            AND NEW.after_sha256=encode(sha256(convert_to(p.proposal->>'content','UTF8')),'hex')
            AND l.content=p.proposal->>'content'
            AND NOT EXISTS (SELECT 1 FROM "{schema}".quizzes q
                WHERE q.lesson_id=l.id AND q.tenant_id=NEW.tenant_id AND q.review_status<>'needs_review')
        ) THEN RAISE EXCEPTION 'Correction application context rejected'; END IF;
        NEW.applied_at := clock_timestamp();
        RETURN NEW;
        END $$""")
    op.execute(
        f"CREATE TRIGGER lesson_correction_application_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {guard}()"
    )
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app")
    op.execute(f"REVOKE ALL ON FUNCTION {guard}() FROM PUBLIC,lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {table} FROM {role}';
            EXECUTE 'REVOKE ALL ON FUNCTION {guard}() FROM {role}';
        END IF; END $$""")
    op.execute(f"GRANT SELECT,INSERT,DELETE ON {table} TO lms_app")


def downgrade() -> None:
    schema = _schema()
    table = f'"{schema}".workbench_lesson_correction_applications'
    if op.get_bind().execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
        raise RuntimeError("Correction application downgrade requires an empty table; preserve receipts")
    op.execute(f"DROP TABLE {table}")
    op.execute(f'DROP FUNCTION "{schema}".guard_lesson_correction_application()')
