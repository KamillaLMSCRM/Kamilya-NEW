"""Tenant-owned encrypted BYOK provider configuration.

Revision ID: 0157
Revises: 0156
"""
import re

from alembic import op

revision = "0157"
down_revision = "0156"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe tenant-ai-providers schema")
    return f'"{schema}"'


def upgrade() -> None:
    schema = _schema()
    table = f"{schema}.tenant_ai_providers"
    op.execute(f"""
        CREATE TABLE {table} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            purpose varchar(16) NOT NULL,
            provider varchar(32) NOT NULL,
            model varchar(128) NOT NULL,
            encrypted_key text NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            free_only boolean NOT NULL DEFAULT true,
            output_dimensions integer NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tenant_ai_providers_tenant_purpose UNIQUE (tenant_id, purpose),
            CONSTRAINT ck_tenant_ai_providers_purpose CHECK (purpose IN ('generation', 'embedding')),
            CONSTRAINT ck_tenant_ai_providers_provider CHECK (provider IN ('deepseek', 'openrouter', 'voyage', 'cohere')),
            CONSTRAINT ck_tenant_ai_providers_model CHECK (model !~ '[\\r\\n]' AND length(model) BETWEEN 1 AND 128),
            CONSTRAINT ck_tenant_ai_providers_purpose_provider CHECK (
                (purpose = 'generation' AND provider IN ('deepseek', 'openrouter') AND output_dimensions IS NULL)
                OR (purpose = 'embedding' AND provider IN ('voyage', 'cohere', 'openrouter'))
            ),
            CONSTRAINT ck_tenant_ai_providers_dimensions CHECK (output_dimensions IS NULL OR output_dimensions BETWEEN 1 AND 4096)
        )
    """)
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"
    op.execute(f"CREATE POLICY tenant_ai_providers_tenant ON {table} FOR ALL TO lms_app USING ({tenant}) WITH CHECK ({tenant})")
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            REVOKE ALL ON {table} FROM {role};
          END IF;
        END $$""")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")


def downgrade() -> None:
    op.execute(f"DROP TABLE {_schema()}.tenant_ai_providers")
