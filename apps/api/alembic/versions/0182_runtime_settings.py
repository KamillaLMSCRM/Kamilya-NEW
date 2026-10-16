"""Typed non-secret runtime overrides and append-only revision audit.

Revision ID:0182
Revises:0181
"""

import re

from alembic import op

revision = "0182"
down_revision = "0181"
branch_labels = depends_on = None

# Frozen migration policy, not imported from an evolving application catalog.
NUMBERS = {
    "assignment.total_seconds": (90, 45, 90, True),
    "assignment.deepseek_seconds": (30, 5, 60, True),
    "assignment.chatgpt_seconds": (40, 5, 40, True),
    "assignment.fallback_seconds": (8, 2, 10, True),
    "assignment.max_tokens": (1200, 256, 1200, True),
    "document_intent.total_seconds": (30, 10, 90, True),
    "document_intent.max_tokens": (1200, 256, 1200, True),
    "document_dialogue.provider_seconds": (8, 2, 30, True),
    "generation.temperature": (0.2, 0, 0.5, False),
    "reviewer.timeout_seconds": (45, 5, 60, True),
    "document_answer.total_seconds": (60, 15, 90, True),
    "document_answer.provider_seconds": (8, 2, 30, True),
    "document_answer.max_tokens": (2000, 512, 2000, True),
    "editor.temperature": (0.2, 0, 0.5, False),
    "editor.max_tokens": (4096, 512, 4096, True),
    "writer.retrieval_count": (15, 5, 15, True),
    "writer.result_count": (10, 3, 10, True),
    "writer.similarity_threshold": (0.45, 0.3, 0.8, False),
    "provider.deepseek.timeout_seconds": (120, 30, 180, True),
    "provider.qwen.timeout_seconds": (600, 30, 600, False),
    "provider.glm.timeout_seconds": (600, 30, 600, False),
    "provider.chatgpt.timeout_seconds": (60, 40, 120, False),
    "outbox.assignment.batch_size": (20, 1, 50, True),
    "outbox.reminders.batch_size": (20, 1, 50, True),
    "outbox.crm.batch_size": (20, 1, 50, True),
}
MODEL_KEYS = tuple(f"provider.{name}.model" for name in ("deepseek", "qwen", "glm", "chatgpt"))


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("unsafe_runtime_settings_schema")
    return f'"{schema}"'


def upgrade() -> None:
    schema = _schema()
    op.execute(f"""CREATE TABLE {schema}.runtime_settings (
      id smallint PRIMARY KEY DEFAULT 1 CHECK(id=1),
      revision integer NOT NULL DEFAULT 1 CHECK(revision>=1),
      overrides jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK(jsonb_typeof(overrides)='object'),
      updated_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(f"""CREATE TABLE {schema}.runtime_settings_history (
      revision integer PRIMARY KEY CHECK(revision>=2),
      before jsonb NOT NULL CHECK(jsonb_typeof(before)='object'),
      after jsonb NOT NULL CHECK(jsonb_typeof(after)='object'),
      reason varchar(240) NOT NULL CHECK(length(trim(reason))>=3),
      actor_id uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(f"INSERT INTO {schema}.runtime_settings(id) VALUES(1)")
    keys = ",".join(f"'{key}'" for key in (*NUMBERS, *MODEL_KEYS))
    op.execute(f"ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_runtime_settings_keys CHECK(overrides - ARRAY[{keys}]::text[] = '{{}}'::jsonb)")
    for index, (key, (_, minimum, maximum, integer)) in enumerate(NUMBERS.items()):
        numeric = f"(overrides->>'{key}')::numeric"
        integral = f"AND {numeric}=trunc({numeric})" if integer else ""
        op.execute(f"""ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_runtime_settings_number_{index}
          CHECK(NOT overrides ? '{key}' OR (jsonb_typeof(overrides->'{key}')='number'
          AND {numeric} BETWEEN {minimum} AND {maximum} {integral}))""")
    for index, key in enumerate(MODEL_KEYS):
        op.execute(f"""ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_runtime_settings_model_{index}
          CHECK(NOT overrides ? '{key}' OR (jsonb_typeof(overrides->'{key}')='string'
          AND overrides->>'{key}' ~ '^[A-Za-z0-9][A-Za-z0-9_./-]{{0,159}}$'
          AND position('..' in overrides->>'{key}')=0))""")
    op.execute(f"""ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_runtime_settings_luna
      CHECK(NOT overrides ? 'provider.chatgpt.model' OR overrides->>'provider.chatgpt.model'='gpt-5.6-luna')""")
    def value(key):
        return f"COALESCE((overrides->>'{key}')::numeric,{NUMBERS[key][0]})"
    for name, expression in {
        "assignment_budget": " + ".join(value(f"assignment.{name}_seconds") for name in ("deepseek", "chatgpt", "fallback")) + f" + 5 <= {value('assignment.total_seconds')}",
        "document_budget": f"{value('document_dialogue.provider_seconds')} <= {value('document_intent.total_seconds')}",
        "answer_budget": f"{value('document_answer.provider_seconds')}+5 <= {value('document_answer.total_seconds')}",
        "retrieval_budget": f"{value('writer.result_count')} <= {value('writer.retrieval_count')}",
    }.items():
        op.execute(f"ALTER TABLE {schema}.runtime_settings ADD CONSTRAINT ck_runtime_settings_{name} CHECK({expression})")
    for table in ("runtime_settings", "runtime_settings_history"):
        qualified = f"{schema}.{table}"
        op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {qualified} FROM PUBLIC,lms_app")
        for role in ("anon", "authenticated", "service_role", "lms_recovery"):
            op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
              REVOKE ALL ON {qualified} FROM {role}; END IF; END $$""")
    op.execute(f"CREATE POLICY runtime_settings_read ON {schema}.runtime_settings FOR SELECT TO lms_app USING(true)")
    op.execute(f"""CREATE POLICY runtime_settings_update ON {schema}.runtime_settings FOR UPDATE TO lms_app
      USING(current_setting('app.is_superadmin',true)='true')
      WITH CHECK(current_setting('app.is_superadmin',true)='true')""")
    op.execute(f"""CREATE POLICY runtime_settings_history_read ON {schema}.runtime_settings_history FOR SELECT TO lms_app
      USING(current_setting('app.is_superadmin',true)='true')""")
    op.execute(f"""CREATE POLICY runtime_settings_history_insert ON {schema}.runtime_settings_history FOR INSERT TO lms_app
      WITH CHECK(current_setting('app.is_superadmin',true)='true')""")
    op.execute(f"GRANT SELECT,UPDATE ON {schema}.runtime_settings TO lms_app")
    op.execute(f"GRANT SELECT,INSERT ON {schema}.runtime_settings_history TO lms_app")
    op.execute(f"""CREATE FUNCTION {schema}.assert_runtime_settings_audit()
      RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
        IF NEW.revision <> OLD.revision+1 OR NOT EXISTS(
          SELECT 1 FROM {schema}.runtime_settings_history h WHERE h.revision=NEW.revision
          AND h.before=OLD.overrides AND h.after=NEW.overrides
          AND h.actor_id IS NOT DISTINCT FROM NEW.updated_by) THEN
          RAISE EXCEPTION 'runtime_settings_audit_required' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute(f"REVOKE ALL ON FUNCTION {schema}.assert_runtime_settings_audit() FROM PUBLIC")
    op.execute(f"""CREATE CONSTRAINT TRIGGER runtime_settings_audited
      AFTER UPDATE OF overrides,revision ON {schema}.runtime_settings
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {schema}.assert_runtime_settings_audit()""")


def downgrade() -> None:
    schema = _schema()
    if schema == '"public"':
        raise RuntimeError("runtime_settings_audit_retained_use_binary_rollback")
    op.execute(f"DROP TABLE {schema}.runtime_settings_history")
    op.execute(f"DROP TABLE {schema}.runtime_settings")
    op.execute(f"DROP FUNCTION {schema}.assert_runtime_settings_audit()")
