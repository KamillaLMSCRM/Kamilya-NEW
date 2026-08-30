"""Add tenant-scoped AI editor request and lifecycle event tables.

Revision ID: 0135
Revises: 0134
Create Date: 2026-08-30

Additive foundation for the contextual AI editor assistant (plan Step 1).
Both tables are tenant-scoped with FORCE RLS. Lifecycle events are
append-only: the runtime role receives SELECT, INSERT only on the event
table, and a composite same-tenant foreign key prevents an event from
attaching to another tenant's request even from a privileged connection.
No existing tables or data are modified.
"""

from __future__ import annotations

from alembic import op

revision = "0135"
down_revision = "0134"
branch_labels = None
depends_on = None


REQUEST_TABLE = "ai_editor_requests"
EVENT_TABLE = "ai_editor_request_events"

INTENT_VALUES = (
    "'rewrite_wording', 'add_context', 'simplify_language', 'change_difficulty', "
    "'make_scenario_based', 'regenerate_distractors', 'balance_answer_length', "
    "'fix_multiple_correct_answers', 'fix_source_grounding', 'fix_grammar', "
    "'remove_duplication', 'add_or_rewrite_explanation', 'split_or_merge_content', 'other'"
)

EVENT_TYPE_VALUES = (
    "'requested', 'preview_started', 'preview_ready', 'preview_failed', "
    "'regenerated', 'applied', 'rejected', 'manually_edited_after_apply', "
    "'published', 'superseded', 'expired'"
)


def _tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {REQUEST_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            actor_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            target_entity_type VARCHAR(40) NOT NULL,
            target_entity_id UUID NOT NULL,
            parent_generation_trace_id VARCHAR(120),
            intent_category VARCHAR(64) NOT NULL,
            selected_scope VARCHAR(120),
            operation_constraints JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            base_content_version VARCHAR(64) NOT NULL,
            locale VARCHAR(16) NOT NULL,
            source_type_summary VARCHAR(64),
            generator_version VARCHAR(64),
            prompt_version VARCHAR(64),
            model_id VARCHAR(120),
            validator_version VARCHAR(64),
            instruction_text TEXT NOT NULL,
            instruction_expires_at TIMESTAMPTZ,
            outcome_state VARCHAR(32) NOT NULL DEFAULT 'requested',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_ai_editor_requests_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_ai_editor_requests_target_type
                CHECK (length(btrim(target_entity_type)) > 0),
            CONSTRAINT ck_ai_editor_requests_intent_category
                CHECK (intent_category IN ({INTENT_VALUES})),
            CONSTRAINT ck_ai_editor_requests_outcome_state
                CHECK (outcome_state IN ({EVENT_TYPE_VALUES})),
            CONSTRAINT ck_ai_editor_requests_instruction_length
                CHECK (char_length(btrim(instruction_text)) BETWEEN 1 AND 8000),
            CONSTRAINT ck_ai_editor_requests_base_version
                CHECK (length(btrim(base_content_version)) > 0)
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_requests_tenant_created ON {REQUEST_TABLE} (tenant_id, created_at)"
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_requests_tenant_target ON {REQUEST_TABLE} "
        "(tenant_id, target_entity_type, target_entity_id)"
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_requests_tenant_intent ON {REQUEST_TABLE} (tenant_id, intent_category)"
    )

    op.execute(
        f"""
        CREATE TABLE {EVENT_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            request_id UUID NOT NULL,
            event_type VARCHAR(32) NOT NULL,
            event_key VARCHAR(120) NOT NULL,
            sequence_no INTEGER NOT NULL,
            actor_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_ai_editor_events_same_tenant_request
                FOREIGN KEY (tenant_id, request_id)
                REFERENCES {REQUEST_TABLE} (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_ai_editor_event_tenant_request_key
                UNIQUE (tenant_id, request_id, event_key),
            CONSTRAINT uq_ai_editor_event_tenant_request_sequence
                UNIQUE (tenant_id, request_id, sequence_no),
            CONSTRAINT ck_ai_editor_events_event_type
                CHECK (event_type IN ({EVENT_TYPE_VALUES})),
            CONSTRAINT ck_ai_editor_events_key CHECK (length(btrim(event_key)) > 0)
        )
        """
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_events_tenant_created ON {EVENT_TABLE} (tenant_id, created_at)"
    )
    op.execute(
        f"CREATE INDEX ix_ai_editor_events_request ON {EVENT_TABLE} (tenant_id, request_id)"
    )

    for table in (REQUEST_TABLE, EVENT_TABLE):
        _tenant_rls(table)

    # Request provenance is immutable to the runtime role. Only the denormalized
    # lifecycle state and its timestamp may be updated. Events are append-only.
    op.execute(f"GRANT SELECT, INSERT ON {REQUEST_TABLE} TO lms_app")
    op.execute(
        f"GRANT UPDATE (outcome_state, updated_at) ON {REQUEST_TABLE} TO lms_app"
    )
    op.execute(f"GRANT SELECT, INSERT ON {EVENT_TABLE} TO lms_app")


def downgrade() -> None:
    for table in (EVENT_TABLE, REQUEST_TABLE):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table}")
