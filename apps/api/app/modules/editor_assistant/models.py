"""Tenant-scoped persistence for AI editor assistant requests and events.

Three tables:

- ``ai_editor_requests``: one row per user request. Stores the raw instruction
  text as tenant content (never logged, never projected into analytics) plus
  normalized taxonomy, provenance versions and retention fields.
- ``ai_editor_request_events``: append-only lifecycle events. Idempotency key
  is ``event_key``, unique within one request; updates are denied at the
  runtime-role privilege boundary so history is never rewritten.
- ``ai_editor_request_previews``: durable ownership and terminal result state
  for one idempotent preview. It stores only a token digest and a bounded
  structured result; prompts, provider output, evidence and exceptions are not
  part of this table.

Same-tenancy invariant: events reference requests through a composite
``(tenant_id, request_id)`` foreign key, so a privileged connection also
cannot attach an event to a request owned by another tenant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base
from app.modules.editor_assistant.taxonomy import (
    EditorIntentCategory,
    EditorLifecycleEventType,
)

_REQUEST_TABLE = "ai_editor_requests"
_EVENT_TABLE = "ai_editor_request_events"
_PREVIEW_TABLE = "ai_editor_request_previews"

_INTENT_VALUES = ", ".join(f"'{item.value}'" for item in EditorIntentCategory)
_EVENT_TYPE_VALUES = ", ".join(f"'{item.value}'" for item in EditorLifecycleEventType)
_OUTCOME_VALUES = _EVENT_TYPE_VALUES
_PREVIEW_STATE_VALUES = "'pending', 'completed', 'failed'"
_PREVIEW_FAILURE_VALUES = (
    "'provider_timeout', 'provider_unavailable', 'provider_output_unparseable', "
    "'contract_violation', 'validation_blocked', 'stale_base_version', "
    "'rejected_out_of_scope', 'source_evidence_unavailable', "
    "'requires_new_draft_revision', 'internal_error'"
)


class AIEditorRequest(Base):
    """One contextual AI editor request. Tenant-scoped like course content."""

    __tablename__ = _REQUEST_TABLE

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    target_entity_type = Column(String(40), nullable=False)
    target_entity_id = Column(UUID(as_uuid=True), nullable=False)
    parent_generation_trace_id = Column(String(120), nullable=True)

    intent_category = Column(String(64), nullable=False)
    selected_scope = Column(String(120), nullable=True)
    operation_constraints = Column(JSONB, nullable=False, default=dict, server_default="{}")
    request_fingerprint_sha256 = Column(String(64), nullable=True)
    base_content_version = Column(String(64), nullable=False)
    locale = Column(String(16), nullable=False)
    source_type_summary = Column(String(64), nullable=True)
    generator_version = Column(String(64), nullable=True)
    prompt_version = Column(String(64), nullable=True)
    model_id = Column(String(120), nullable=True)
    validator_version = Column(String(64), nullable=True)

    # Raw tenant content. Must never enter logs, metrics labels, event
    # metadata or the analytics projection.
    instruction_text = Column(Text, nullable=False)

    # Retention/expiry of the raw tenant content. NULL means the tenant has
    # not configured a policy yet; the purge path treats NULL as retain.
    instruction_expires_at = Column(DateTime(timezone=True), nullable=True)

    outcome_state = Column(String(32), nullable=False, default="requested", server_default="requested")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Composite candidate key: makes the event table's same-tenant
        # composite FK possible and is unique by definition (id is PK).
        UniqueConstraint("tenant_id", "id", name="uq_ai_editor_requests_tenant_id"),
        Index("ix_ai_editor_requests_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_ai_editor_requests_tenant_target",
            "tenant_id",
            "target_entity_type",
            "target_entity_id",
        ),
        Index(
            "ix_ai_editor_requests_tenant_intent",
            "tenant_id",
            "intent_category",
        ),
        CheckConstraint(
            f"intent_category IN ({_INTENT_VALUES})",
            name="ck_ai_editor_requests_intent_category",
        ),
        CheckConstraint(
            f"outcome_state IN ({_OUTCOME_VALUES})",
            name="ck_ai_editor_requests_outcome_state",
        ),
        CheckConstraint(
            "char_length(btrim(instruction_text)) BETWEEN 1 AND 8000",
            name="ck_ai_editor_requests_instruction_length",
        ),
        CheckConstraint(
            "length(btrim(target_entity_type)) > 0",
            name="ck_ai_editor_requests_target_type",
        ),
        CheckConstraint(
            "length(btrim(base_content_version)) > 0",
            name="ck_ai_editor_requests_base_version",
        ),
        CheckConstraint(
            "request_fingerprint_sha256 IS NULL OR "
            "request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ai_editor_requests_fingerprint_sha256",
        ),
        {"extend_existing": True},
    )


class AIEditorRequestEvent(Base):
    """Append-only lifecycle event. Idempotent on (tenant, request, event_key)."""

    __tablename__ = _EVENT_TABLE
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["ai_editor_requests.tenant_id", "ai_editor_requests.id"],
            name="fk_ai_editor_events_same_tenant_request",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "request_id",
            "event_key",
            name="uq_ai_editor_event_tenant_request_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "request_id",
            "sequence_no",
            name="uq_ai_editor_event_tenant_request_sequence",
        ),
        Index("ix_ai_editor_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_editor_events_request", "tenant_id", "request_id"),
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPE_VALUES})",
            name="ck_ai_editor_events_event_type",
        ),
        CheckConstraint(
            "length(btrim(event_key)) > 0",
            name="ck_ai_editor_events_key",
        ),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(
        UUID(as_uuid=True),
        nullable=False,
    )
    event_type = Column(String(32), nullable=False)
    event_key = Column(String(120), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    # Persisted metadata is allowlist-only (see analytics.EVENT_METADATA_ALLOWLIST):
    # normalized labels, bounded numerics and version strings. Tenant content
    # is rejected at the service boundary and can never be stored here.
    metadata_json = Column(JSONB, nullable=False, default=dict, server_default="{}")
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AIEditorRequestPreview(Base):
    """Durable tenant-scoped claim and bounded result for one preview."""

    __tablename__ = _PREVIEW_TABLE
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["ai_editor_requests.tenant_id", "ai_editor_requests.id"],
            name="fk_ai_editor_previews_same_tenant_request",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "preview_key",
            name="uq_ai_editor_preview_tenant_key",
        ),
        Index(
            "ix_ai_editor_previews_tenant_request",
            "tenant_id",
            "request_id",
        ),
        Index(
            "ix_ai_editor_previews_tenant_state_updated",
            "tenant_id",
            "state",
            "updated_at",
        ),
        CheckConstraint(
            "char_length(btrim(preview_key)) BETWEEN 1 AND 120",
            name="ck_ai_editor_previews_key_length",
        ),
        CheckConstraint(
            "payload_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_ai_editor_previews_payload_fingerprint",
        ),
        CheckConstraint(
            f"state IN ({_PREVIEW_STATE_VALUES})",
            name="ck_ai_editor_previews_state",
        ),
        CheckConstraint(
            "claim_token_sha256 IS NULL "
            "OR claim_token_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ai_editor_previews_claim_digest",
        ),
        # One structured question patch is deliberately capped at 64 KiB.
        # Source excerpts and provider payloads are not permitted in this row.
        CheckConstraint(
            "completed_result_json IS NULL "
            "OR octet_length(completed_result_json::text) <= 65536",
            name="ck_ai_editor_previews_result_size",
        ),
        CheckConstraint(
            "completed_result_json IS NULL "
            "OR jsonb_typeof(completed_result_json) = 'object'",
            name="ck_ai_editor_previews_result_object",
        ),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({_PREVIEW_FAILURE_VALUES})",
            name="ck_ai_editor_previews_failure_code",
        ),
        CheckConstraint(
            "(state = 'pending' "
            "AND claim_token_sha256 IS NOT NULL "
            "AND completed_result_json IS NULL "
            "AND failure_code IS NULL "
            "AND completed_at IS NULL "
            "AND failed_at IS NULL) "
            "OR (state = 'completed' "
            "AND claim_token_sha256 IS NULL "
            "AND completed_result_json IS NOT NULL "
            "AND failure_code IS NULL "
            "AND completed_at IS NOT NULL "
            "AND failed_at IS NULL) "
            "OR (state = 'failed' "
            "AND claim_token_sha256 IS NULL "
            "AND completed_result_json IS NULL "
            "AND failure_code IS NOT NULL "
            "AND completed_at IS NULL "
            "AND failed_at IS NOT NULL)",
            name="ck_ai_editor_previews_state_shape",
        ),
        {"extend_existing": True},
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id = Column(UUID(as_uuid=True), nullable=False)
    preview_key = Column(String(120), nullable=False)
    payload_fingerprint = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False)
    claim_token_sha256 = Column(String(64), nullable=True)
    completed_result_json = Column(JSONB, nullable=True)
    failure_code = Column(String(64), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
