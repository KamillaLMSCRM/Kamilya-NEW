"""Append-only editorial decisions, original text and approved snapshots.

Revision ID: 0185
Revises: 0184
"""

import re

from alembic import op

revision = "0185"
down_revision = "0184"
branch_labels = None
depends_on = None


def _schema():
    value = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("unsafe_schema")
    return f'"{value}"'


def upgrade():
    schema = _schema()
    table = f"{schema}.document_editorial_events"
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute(f"""CREATE TABLE {table} (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
      document_id uuid NOT NULL REFERENCES {schema}.documents(id) ON DELETE CASCADE,
      actor_id uuid NOT NULL,
      sequence integer NOT NULL CHECK(sequence>0),
      kind varchar(24) NOT NULL CHECK(kind IN (
        'queued','running','analysis_block','failed','analyzed','resolved','issue_reopened','auto_undone','approved','reopened')),
      original_blob_sha256 varchar(64) NOT NULL CHECK(original_blob_sha256 ~ '^[0-9a-f]{{64}}$'),
      request_id uuid,
      command_sha256 varchar(64),
      payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(tenant_id,document_id,sequence),
      UNIQUE(tenant_id,document_id,request_id),
      CHECK((request_id IS NULL)=(command_sha256 IS NULL)),
      CHECK(command_sha256 IS NULL OR command_sha256 ~ '^[0-9a-f]{{64}}$'))""")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
    owned = (f"EXISTS (SELECT 1 FROM {schema}.documents d WHERE d.id=document_id "
             "AND d.tenant_id=document_editorial_events.tenant_id "
             "AND d.content_sha256=original_blob_sha256 AND d.lifecycle_status='active')")
    op.execute(f"CREATE POLICY editorial_events_read ON {table} FOR SELECT TO lms_app USING({tenant})")
    op.execute(f"CREATE POLICY editorial_events_insert ON {table} FOR INSERT TO lms_app WITH CHECK({tenant} AND {owned})")
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app")
    op.execute(f"GRANT SELECT,INSERT ON {table} TO lms_app")


def downgrade():
    schema = _schema()
    op.execute(f"DROP TABLE {schema}.document_editorial_events")
