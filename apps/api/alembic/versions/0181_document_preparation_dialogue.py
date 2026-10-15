"""Private durable document preparation, additive application-compatible archive.

Revision ID: 0181
Revises: 0180
"""
import re

from sqlalchemy import text

from alembic import op

revision = "0181"
down_revision = "0180"
branch_labels = None
depends_on = None


def _schema():
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe dialogue schema")
    return f'"{schema}"'


def upgrade():
    s = _schema()
    task = f"{s}.workbench_document_dialogues"
    exchange = f"{s}.workbench_document_dialogue_exchanges"
    op.execute(f"""CREATE TABLE {task} (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
        language varchar(2) NOT NULL CHECK(language IN ('ru','kk','en')),
        sources jsonb NOT NULL CHECK(jsonb_typeof(sources)='array' AND jsonb_array_length(sources) BETWEEN 1 AND 5),
        creation_fingerprint varchar(64) NOT NULL CHECK(creation_fingerprint ~ '^[a-f0-9]{{64}}$'),
        draft jsonb NOT NULL CHECK(jsonb_typeof(draft)='object'),
        revision integer NOT NULL DEFAULT 1 CHECK(revision>=1),
        plan_id uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(f"""CREATE TABLE {exchange} (
        id uuid PRIMARY KEY,
        task_id uuid NOT NULL REFERENCES {task}(id) ON DELETE CASCADE,
        tenant_id uuid NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
        actor_id uuid NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
        base_revision integer NOT NULL CHECK(base_revision>=1),
        fingerprint varchar(64) NOT NULL CHECK(fingerprint ~ '^[a-f0-9]{{64}}$'),
        instruction text NOT NULL CHECK(char_length(btrim(instruction)) BETWEEN 1 AND 4000),
        state varchar(12) NOT NULL CHECK(state IN ('pending','completed','failed')),
        response jsonb, error_code varchar(48),
        created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
        CHECK((state='pending' AND response IS NULL AND error_code IS NULL AND finished_at IS NULL)
            OR(state='completed' AND response IS NOT NULL AND jsonb_typeof(response)='object' AND error_code IS NULL AND finished_at IS NOT NULL)
            OR(state='failed' AND response IS NULL AND error_code IS NOT NULL AND error_code IN
                ('interrupted','provider_unavailable','source_stale','budget_denied','persistence_unavailable','invalid_response') AND finished_at IS NOT NULL))
    )""")
    op.execute(f"CREATE INDEX ix_document_dialogue_owner ON {task}(tenant_id,actor_id,updated_at DESC,id DESC)")
    op.execute(f"CREATE INDEX ix_document_dialogue_exchange ON {exchange}(tenant_id,actor_id,task_id,created_at,id)")
    op.execute(f"CREATE UNIQUE INDEX uq_document_dialogue_pending ON {exchange}(task_id) WHERE state='pending'")
    for name in ("workbench_document_dialogues", "workbench_document_dialogue_exchanges"):
        table = f"{s}.{name}"
        tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
        actor = "actor_id=nullif(current_setting('app.user_id',true),'')::uuid"
        eligible = f"""EXISTS(SELECT 1 FROM {s}.users u WHERE u.id=actor_id AND u.tenant_id={name}.tenant_id
            AND u.is_active IS TRUE AND u.status='active' AND (u.role='methodologist' OR EXISTS(
                SELECT 1 FROM {s}.user_roles r WHERE r.user_id=u.id AND r.tenant_id=u.tenant_id AND r.role='methodologist')))"""
        scope = f"{tenant} AND {actor} AND {eligible}"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        for operation, policy in (("SELECT", "read"), ("INSERT", "insert"), ("UPDATE", "update")):
            using = f"USING({scope})" if operation != "INSERT" else ""
            check = f"WITH CHECK({scope})" if operation != "SELECT" else ""
            op.execute(f"CREATE POLICY {name}_{policy} ON {table} FOR {operation} TO lms_app {using} {check}")
        op.execute(f"CREATE POLICY {name}_purge ON {table} FOR DELETE TO lms_app USING({tenant} AND COALESCE(current_setting('app.is_superadmin',true),'false')='true')")
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app")
        for role in ("anon", "authenticated", "service_role", "lms_recovery"):
            op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
                EXECUTE 'REVOKE ALL ON {table} FROM {role}'; END IF; END $$""")
        op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO lms_app")
    op.execute(f"""CREATE FUNCTION {s}.guard_document_dialogue_task() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF NEW.tenant_id IS DISTINCT FROM nullif(current_setting('app.tenant_id',true),'')::uuid
            OR NEW.actor_id IS DISTINCT FROM nullif(current_setting('app.user_id',true),'')::uuid THEN
            RAISE EXCEPTION 'dialogue_context_required' USING ERRCODE='42501'; END IF;
        IF TG_OP='INSERT' THEN
            IF NEW.revision<>1 OR NEW.plan_id IS NOT NULL THEN
                RAISE EXCEPTION 'dialogue_initial_state' USING ERRCODE='23514'; END IF;
            IF (SELECT count(DISTINCT item->>'document_id') FROM jsonb_array_elements(NEW.sources) item)
                <>jsonb_array_length(NEW.sources) OR EXISTS(
                SELECT 1 FROM jsonb_array_elements(NEW.sources) item WHERE NOT EXISTS(
                    SELECT 1 FROM {s}.documents d WHERE d.id::text=item->>'document_id'
                    AND d.tenant_id=NEW.tenant_id AND d.lifecycle_status='active'
                    AND d.index_status IN ('ready','partial') AND d.content_sha256 IS NOT NULL
                    AND d.content_sha256=item->>'content_sha256'
                    AND d.version::text=item->>'version' AND d.index_revision::text=item->>'index_revision'
                    AND d.title=item->>'title')) THEN
                RAISE EXCEPTION 'dialogue_source_scope' USING ERRCODE='23514'; END IF;
            NEW.created_at:=clock_timestamp();
        ELSE
            IF ROW(NEW.id,NEW.tenant_id,NEW.actor_id,NEW.language,NEW.sources,NEW.creation_fingerprint,NEW.created_at)
                IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.actor_id,OLD.language,OLD.sources,OLD.creation_fingerprint,OLD.created_at)
                OR NEW.revision NOT IN (OLD.revision,OLD.revision+1)
                OR (NEW.draft IS DISTINCT FROM OLD.draft AND NEW.revision<>OLD.revision+1) THEN
                RAISE EXCEPTION 'dialogue_scope_immutable' USING ERRCODE='23514'; END IF;
        END IF;
        IF NEW.draft->'candidate'->>'language' IS DISTINCT FROM NEW.language THEN
            RAISE EXCEPTION 'dialogue_language_mismatch' USING ERRCODE='23514'; END IF;
        IF NEW.plan_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM {s}.workbench_document_plans p WHERE p.id=NEW.plan_id AND p.tenant_id=NEW.tenant_id
                AND p.actor_id=NEW.actor_id AND p.status='ready' AND p.snapshot->>'dialogue_task_id'=NEW.id::text
                AND p.snapshot->>'dialogue_revision'=NEW.revision::text AND p.snapshot->'sources'=NEW.sources) THEN
            RAISE EXCEPTION 'dialogue_plan_scope' USING ERRCODE='23514'; END IF;
        NEW.updated_at:=clock_timestamp(); RETURN NEW; END $$""")
    op.execute(f"""CREATE FUNCTION {s}.guard_document_dialogue_exchange() RETURNS trigger LANGUAGE plpgsql
        SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF TG_OP='INSERT' THEN
            IF NEW.state<>'pending' OR NOT EXISTS(SELECT 1 FROM {task} t WHERE t.id=NEW.task_id
                AND t.actor_id=NEW.actor_id AND t.tenant_id=NEW.tenant_id AND t.revision=NEW.base_revision+1) THEN
                RAISE EXCEPTION 'dialogue_exchange_scope' USING ERRCODE='23514'; END IF;
            NEW.created_at:=clock_timestamp();
        ELSE
            IF OLD.state<>'pending' OR NEW.state NOT IN ('completed','failed')
                OR ROW(NEW.id,NEW.task_id,NEW.tenant_id,NEW.actor_id,NEW.base_revision,NEW.fingerprint,NEW.instruction,NEW.created_at)
                    IS DISTINCT FROM ROW(OLD.id,OLD.task_id,OLD.tenant_id,OLD.actor_id,OLD.base_revision,OLD.fingerprint,OLD.instruction,OLD.created_at) THEN
                RAISE EXCEPTION 'dialogue_exchange_terminal' USING ERRCODE='23514'; END IF;
            NEW.finished_at:=clock_timestamp();
        END IF; RETURN NEW; END $$""")
    for table, function in ((task, "guard_document_dialogue_task"), (exchange, "guard_document_dialogue_exchange")):
        op.execute(f"CREATE TRIGGER {function} BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {s}.{function}()")
        op.execute(f"REVOKE ALL ON FUNCTION {s}.{function}() FROM PUBLIC,lms_app")
        for role in ("anon", "authenticated", "service_role", "lms_recovery"):
            op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
                EXECUTE 'REVOKE ALL ON FUNCTION {s}.{function}() FROM {role}'; END IF; END $$""")


def downgrade():
    s = _schema()
    for name in ("workbench_document_dialogue_exchanges", "workbench_document_dialogues"):
        if op.get_bind().execute(text(f"SELECT EXISTS(SELECT 1 FROM {s}.{name})")).scalar():
            raise RuntimeError("Document dialogue downgrade requires empty archive; retain user content")
    op.execute(f"DROP TABLE {s}.workbench_document_dialogue_exchanges")
    op.execute(f"DROP TABLE {s}.workbench_document_dialogues")
    op.execute(f"DROP FUNCTION {s}.guard_document_dialogue_exchange()")
    op.execute(f"DROP FUNCTION {s}.guard_document_dialogue_task()")
