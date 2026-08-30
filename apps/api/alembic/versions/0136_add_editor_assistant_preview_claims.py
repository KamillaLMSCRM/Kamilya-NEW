"""Add tenant-scoped durable AI editor preview claims.

Revision ID: 0136
Revises: 0135
Create Date: 2026-08-30

The result JSON is capped at 64 KiB: sufficient for one structured question
patch and its safe validation/provenance fields. Source excerpts, prompts, raw
provider responses, instructions and exception text do not belong in this
table. The runtime role has table-level SELECT/INSERT and column-level UPDATE
only for lifecycle transition fields; DELETE and identity-field updates are
not granted.
"""

from __future__ import annotations

from alembic import op

revision = "0136"
down_revision = "0135"
branch_labels = None
depends_on = None


PREVIEW_TABLE = "ai_editor_request_previews"
FAILURE_VALUES = (
    "'provider_timeout', 'provider_unavailable', 'provider_output_unparseable', "
    "'contract_violation', 'validation_blocked', 'stale_base_version', "
    "'rejected_out_of_scope', 'source_evidence_unavailable', "
    "'requires_new_draft_revision', 'internal_error'"
)
TENANT_EXPRESSION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {PREVIEW_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            request_id UUID NOT NULL,
            preview_key VARCHAR(120) NOT NULL,
            payload_fingerprint VARCHAR(64) NOT NULL,
            state VARCHAR(16) NOT NULL,
            claim_token_sha256 VARCHAR(64),
            completed_result_json JSONB,
            failure_code VARCHAR(64),
            completed_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_ai_editor_previews_same_tenant_request
                FOREIGN KEY (tenant_id, request_id)
                REFERENCES ai_editor_requests (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_ai_editor_preview_tenant_key
                UNIQUE (tenant_id, preview_key),
            CONSTRAINT ck_ai_editor_previews_key_length
                CHECK (char_length(btrim(preview_key)) BETWEEN 1 AND 120),
            CONSTRAINT ck_ai_editor_previews_payload_fingerprint
                CHECK (payload_fingerprint ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_ai_editor_previews_state
                CHECK (state IN ('pending', 'completed', 'failed')),
            CONSTRAINT ck_ai_editor_previews_claim_digest
                CHECK (claim_token_sha256 IS NULL
                    OR claim_token_sha256 ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_ai_editor_previews_result_size
                CHECK (completed_result_json IS NULL
                    OR octet_length(completed_result_json::text) <= 65536),
            CONSTRAINT ck_ai_editor_previews_result_object
                CHECK (completed_result_json IS NULL
                    OR jsonb_typeof(completed_result_json) = 'object'),
            CONSTRAINT ck_ai_editor_previews_failure_code
                CHECK (failure_code IS NULL OR failure_code IN ({FAILURE_VALUES})),
            CONSTRAINT ck_ai_editor_previews_state_shape CHECK (
                (state = 'pending'
                    AND claim_token_sha256 IS NOT NULL
                    AND completed_result_json IS NULL
                    AND failure_code IS NULL
                    AND completed_at IS NULL
                    AND failed_at IS NULL)
                OR (state = 'completed'
                    AND claim_token_sha256 IS NULL
                    AND completed_result_json IS NOT NULL
                    AND failure_code IS NULL
                    AND completed_at IS NOT NULL
                    AND failed_at IS NULL)
                OR (state = 'failed'
                    AND claim_token_sha256 IS NULL
                    AND completed_result_json IS NULL
                    AND failure_code IS NOT NULL
                    AND completed_at IS NULL
                    AND failed_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_previews_tenant_request "
        f"ON {PREVIEW_TABLE} (tenant_id, request_id)"
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_previews_tenant_state_updated "
        f"ON {PREVIEW_TABLE} (tenant_id, state, updated_at)"
    )

    op.execute(f"ALTER TABLE {PREVIEW_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {PREVIEW_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {PREVIEW_TABLE}_tenant_select ON {PREVIEW_TABLE}
        FOR SELECT USING ({TENANT_EXPRESSION})
        """
    )
    op.execute(
        f"""
        CREATE POLICY {PREVIEW_TABLE}_tenant_insert ON {PREVIEW_TABLE}
        FOR INSERT WITH CHECK ({TENANT_EXPRESSION})
        """
    )
    op.execute(
        f"""
        CREATE POLICY {PREVIEW_TABLE}_tenant_update ON {PREVIEW_TABLE}
        FOR UPDATE USING ({TENANT_EXPRESSION}) WITH CHECK ({TENANT_EXPRESSION})
        """
    )

    op.execute(f"REVOKE ALL ON {PREVIEW_TABLE} FROM PUBLIC")
    op.execute(f"REVOKE DELETE ON {PREVIEW_TABLE} FROM lms_app")
    op.execute(f"GRANT SELECT ON {PREVIEW_TABLE} TO lms_app")
    op.execute(
        f"GRANT INSERT (tenant_id, request_id, preview_key, "
        f"payload_fingerprint, state, claim_token_sha256) "
        f"ON {PREVIEW_TABLE} TO lms_app"
    )
    op.execute(
        f"GRANT UPDATE (state, claim_token_sha256, completed_result_json, "
        f"failure_code, completed_at, failed_at, updated_at) "
        f"ON {PREVIEW_TABLE} TO lms_app"
    )


def downgrade() -> None:
    for operation in ("update", "insert", "select"):
        op.execute(
            f"DROP POLICY IF EXISTS {PREVIEW_TABLE}_tenant_{operation} "
            f"ON {PREVIEW_TABLE}"
        )
    op.execute(f"DROP TABLE IF EXISTS {PREVIEW_TABLE}")
