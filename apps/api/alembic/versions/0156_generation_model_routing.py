"""Global approved generation-model routing.

Revision ID: 0156
Revises: 0155
"""

import re

from alembic import op

revision = "0156"
down_revision = "0155"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe generation-model-routing schema")
    return f'"{schema}"'


def upgrade() -> None:
    schema = _schema()
    table = f"{schema}.generation_model_routing"
    op.execute(f"""
        CREATE TABLE {table} (
            id smallint PRIMARY KEY DEFAULT 1,
            ordered_model_ids jsonb NOT NULL,
            revision integer NOT NULL DEFAULT 1,
            updated_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_generation_model_routing_singleton CHECK (id = 1),
            CONSTRAINT ck_generation_model_routing_revision CHECK (revision >= 1),
            CONSTRAINT ck_generation_model_routing_array CHECK (
                jsonb_typeof(ordered_model_ids) = 'array'
                AND jsonb_array_length(ordered_model_ids) BETWEEN 1 AND 3
                AND ordered_model_ids ->> 0 = 'deepseek'
                AND ordered_model_ids <@ '["deepseek","qwen38_flash_next","glm53_flash"]'::jsonb
                AND (
                    jsonb_array_length(ordered_model_ids) = 1
                    OR (
                        jsonb_array_length(ordered_model_ids) = 2
                        AND ordered_model_ids ->> 0 <> ordered_model_ids ->> 1
                    )
                    OR (
                        jsonb_array_length(ordered_model_ids) = 3
                        AND ordered_model_ids ->> 0 <> ordered_model_ids ->> 1
                        AND ordered_model_ids ->> 0 <> ordered_model_ids ->> 2
                        AND ordered_model_ids ->> 1 <> ordered_model_ids ->> 2
                    )
                )
            )
        )
    """)
    op.execute(f"""
        INSERT INTO {table} (id, ordered_model_ids)
        VALUES (1, '["deepseek","qwen38_flash_next","glm53_flash"]'::jsonb)
    """)
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            REVOKE ALL ON {table} FROM {role};
          END IF;
        END $$""")
    # Runtime workers need the non-secret route; only authenticated platform
    # superadmins may mutate it.
    op.execute(f"""
        CREATE POLICY generation_model_routing_read ON {table}
        FOR SELECT TO lms_app USING (true)
    """)
    op.execute(f"""
        CREATE POLICY generation_model_routing_superadmin_write ON {table}
        FOR ALL TO lms_app
        USING (current_setting('app.is_superadmin', true) = 'true')
        WITH CHECK (current_setting('app.is_superadmin', true) = 'true')
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app")


def downgrade() -> None:
    op.execute(f"DROP TABLE {_schema()}.generation_model_routing")
