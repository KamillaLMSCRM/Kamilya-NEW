"""Private durable lesson dialogue, additive and application rollback compatible.

Revision ID: 0179
Revises: 0178
"""
import re

from sqlalchemy import text

from alembic import op

revision = "0179"
down_revision = "0178"
branch_labels = None
depends_on = None


def _schema():
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe dialogue schema")
    return f'"{schema}"'


def upgrade():
    s = _schema()
    t = f"{s}.ai_lesson_dialogue_exchanges"
    op.execute(f"""CREATE TABLE {t} (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
        course_id uuid NOT NULL REFERENCES {s}.courses(id) ON DELETE CASCADE,
        lesson_id uuid NOT NULL REFERENCES {s}.lessons(id) ON DELETE CASCADE,
        language varchar(2) NOT NULL CHECK(language IN ('ru','kk','en')),
        fingerprint varchar(64) NOT NULL CHECK(fingerprint ~ '^[a-f0-9]{{64}}$'),
        message text NOT NULL CHECK(char_length(btrim(message)) BETWEEN 1 AND 2000),
        state varchar(12) NOT NULL CHECK(state IN ('pending','completed','failed')),
        response jsonb,
        error_code varchar(32),
        created_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        CHECK((state='pending' AND response IS NULL AND error_code IS NULL AND finished_at IS NULL)
            OR(state='completed' AND jsonb_typeof(response)='object' AND response IS NOT NULL AND error_code IS NULL AND finished_at IS NOT NULL)
            OR(state='failed' AND response IS NULL AND error_code IN ('provider_unavailable','interrupted') AND error_code IS NOT NULL AND finished_at IS NOT NULL))
    )""")
    op.execute(f"CREATE INDEX ix_lesson_dialogue_scope ON {t}(tenant_id,actor_id,course_id,lesson_id,language,created_at DESC,id DESC)")
    op.execute(f"CREATE UNIQUE INDEX uq_lesson_dialogue_pending ON {t}(tenant_id,actor_id,course_id,lesson_id,language) WHERE state='pending'")
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    actor = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
    eligible = f"""EXISTS(SELECT 1 FROM {s}.users u WHERE u.id=actor_id AND u.tenant_id=ai_lesson_dialogue_exchanges.tenant_id
        AND u.is_active IS TRUE AND u.status='active'
        AND (u.role='methodologist' OR EXISTS(SELECT 1 FROM {s}.user_roles r WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist')))"""
    scope = f"{tenant} AND {actor} AND {eligible}"
    op.execute(f"CREATE POLICY lesson_dialogue_read ON {t} FOR SELECT TO lms_app USING({scope})")
    op.execute(f"CREATE POLICY lesson_dialogue_insert ON {t} FOR INSERT TO lms_app WITH CHECK({scope})")
    op.execute(f"CREATE POLICY lesson_dialogue_update ON {t} FOR UPDATE TO lms_app USING({scope}) WITH CHECK({scope})")
    op.execute(f"CREATE POLICY lesson_dialogue_purge ON {t} FOR DELETE TO lms_app USING({tenant} AND COALESCE(current_setting('app.is_superadmin',true),'false')='true')")
    op.execute(f"""CREATE FUNCTION {s}.guard_lesson_dialogue() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF TG_OP='INSERT' THEN
            IF NEW.tenant_id IS DISTINCT FROM nullif(current_setting('app.tenant_id',true),'')::uuid
                OR NEW.actor_id IS DISTINCT FROM nullif(current_setting('app.user_id',true),'')::uuid THEN
                RAISE EXCEPTION 'dialogue_context_required' USING ERRCODE='42501';
            END IF;
            IF NEW.state<>'pending' OR NOT EXISTS(
                SELECT 1 FROM {s}.lessons l JOIN {s}.modules m ON m.id=l.module_id
                JOIN {s}.courses c ON c.id=m.course_id WHERE l.id=NEW.lesson_id
                AND c.id=NEW.course_id AND l.tenant_id=NEW.tenant_id
                AND m.tenant_id=NEW.tenant_id AND c.tenant_id=NEW.tenant_id
            ) THEN RAISE EXCEPTION 'dialogue_scope_rejected' USING ERRCODE='23514'; END IF;
            NEW.created_at:=clock_timestamp();
        ELSE
            IF OLD.state<>'pending' OR NEW.state NOT IN ('completed','failed')
                OR ROW(NEW.id,NEW.tenant_id,NEW.actor_id,NEW.course_id,NEW.lesson_id,NEW.language,NEW.fingerprint,NEW.message,NEW.created_at)
                    IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.actor_id,OLD.course_id,OLD.lesson_id,OLD.language,OLD.fingerprint,OLD.message,OLD.created_at)
            THEN RAISE EXCEPTION 'dialogue_transition_rejected' USING ERRCODE='23514'; END IF;
            NEW.finished_at:=clock_timestamp();
        END IF;
        RETURN NEW;
        END $$""")
    op.execute(f"CREATE TRIGGER lesson_dialogue_guard BEFORE INSERT OR UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION {s}.guard_lesson_dialogue()")
    op.execute(f"REVOKE ALL ON {t} FROM PUBLIC,lms_app")
    op.execute(f"REVOKE ALL ON FUNCTION {s}.guard_lesson_dialogue() FROM PUBLIC,lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {t} FROM {role}';
            EXECUTE 'REVOKE ALL ON FUNCTION {s}.guard_lesson_dialogue() FROM {role}';
        END IF; END $$""")
    op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {t} TO lms_app")


def downgrade():
    s = _schema()
    t = f"{s}.ai_lesson_dialogue_exchanges"
    if op.get_bind().execute(text(f"SELECT EXISTS(SELECT 1 FROM {t})")).scalar():
        raise RuntimeError("Dialogue downgrade requires empty archive; retain user content")
    op.execute(f"DROP TABLE {t}")
    op.execute(f"DROP FUNCTION {s}.guard_lesson_dialogue()")
