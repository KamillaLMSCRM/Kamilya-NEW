"""Canonical service owning AI editor request creation and lifecycle events.

Every request and lifecycle transition for the contextual editor assistant
flows through this service. Controllers, model clients and UI must not create
rows or record events independently.

Contract:

- ``tenant_id`` and ``actor_id`` are supplied from the trusted server context
  (authenticated principal). They are never accepted from client payloads.
- The idempotency key ``event_key`` is globally unique within one request.
  Exact replay requires the same actor, same event type, and same validated
  metadata. Reusing a key with a different actor, event type, or payload
  raises :class:`EditorIdempotencyCollisionError` before any insert.
- History is append-only: events are never updated or deleted (runtime-role
  privileges deny UPDATE/DELETE on the event table). Invalid transitions
  raise :class:`EditorLifecycleTransitionError` instead of rewriting history.
- Lifecycle transitions lock the request row (``SELECT ... FOR UPDATE``) so
  two concurrent transitions cannot both commit from the same prior state.
- Raw instruction text stays on the request row as tenant content. It is
  rejected from event metadata and never appears in the analytics projection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from .analytics import (
    EditorMetadataValidationError,
    project_event,
    project_request,
    validate_event_metadata,
)
from .models import AIEditorRequest, AIEditorRequestEvent
from .repository import EditorRequestRepository
from .taxonomy import (
    EditorIntentCategory,
    EditorLifecycleEventType,
    can_record_outcome,
)

logger = logging.getLogger(__name__)

_MAX_INSTRUCTION_LENGTH = 8_000
_MAX_SELECTED_SCOPE_LENGTH = 120
_MAX_OPERATION_CONSTRAINTS_BYTES = 8_192
_EVENT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FINGERPRINT_SCHEMA = "editor_assistant.request.v1"
_REQUEST_ID_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://kml.kz/editor-assistant/request",
)


class EditorRequestServiceError(Exception):
    """Base class for editor assistant service errors."""


class EditorLifecycleTransitionError(EditorRequestServiceError):
    """A lifecycle event violates the append-only transition contract."""


class EditorIdempotencyCollisionError(EditorRequestServiceError):
    """An event key was reused with a different event type or payload."""


def _validate_event_key(event_key: str) -> str:
    """Accept only an opaque normalized idempotency key."""

    if not isinstance(event_key, str) or not _EVENT_KEY_PATTERN.fullmatch(event_key):
        raise EditorRequestServiceError("Invalid editor event key")
    return event_key


def _validate_instruction_text(value: str) -> str:
    """Bound raw instruction text before persistence."""

    if not isinstance(value, str):
        raise EditorRequestServiceError("Invalid editor instruction text")
    text_value = unicodedata.normalize("NFC", value.strip())
    if not text_value:
        raise EditorRequestServiceError("Invalid editor instruction text")
    if len(text_value) > _MAX_INSTRUCTION_LENGTH:
        raise EditorRequestServiceError("Editor instruction text exceeds the size limit")
    return text_value


def _validate_selected_scope(value: str | None) -> str | None:
    """Bound the selected scope before persistence."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise EditorRequestServiceError("Invalid editor selected scope")
    text_value = value.strip()
    if not text_value:
        raise EditorRequestServiceError("Invalid editor selected scope")
    if len(text_value) > _MAX_SELECTED_SCOPE_LENGTH:
        raise EditorRequestServiceError("Editor selected scope exceeds the size limit")
    return text_value


def _validate_operation_constraints(value: dict[str, Any]) -> dict[str, Any]:
    """Bound tenant-owned constraints before persistence."""

    if not isinstance(value, dict):
        raise EditorRequestServiceError("Invalid editor operation constraints")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_OPERATION_CONSTRAINTS_BYTES:
            raise EditorRequestServiceError("Editor operation constraints exceed the size limit")
        return cast(dict[str, Any], json.loads(encoded))
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise EditorRequestServiceError("Invalid editor operation constraints") from None


@dataclass
class EditorActorContext:
    """Trusted server-derived context for one editor assistant operation.

    Built by callers from the authenticated principal only. A client-supplied
    tenant or actor value must never populate this object.
    """

    tenant_id: Any
    actor_id: Any


@dataclass
class EditorRequestDraft:
    """Validated input for one new editor assistant request."""

    target_entity_type: str
    target_entity_id: Any
    instruction_text: str
    intent_category: str
    base_content_version: str
    locale: str
    selected_scope: str | None = None
    operation_constraints: dict[str, Any] = field(default_factory=dict)
    parent_generation_trace_id: str | None = None
    source_type_summary: str | None = None
    generator_version: str | None = None
    prompt_version: str | None = None
    model_id: str | None = None
    validator_version: str | None = None
    instruction_expires_at: datetime | None = None


@dataclass
class EditorEventDraft:
    """Validated input for one lifecycle event on an existing request."""

    event_type: EditorLifecycleEventType
    event_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


class EditorRequestService:
    """Single canonical owner of request creation and lifecycle recording."""

    def __init__(self, db: AsyncSession):
        self._repo = EditorRequestRepository(db)

    async def create_request(
        self, actor: EditorActorContext, draft: EditorRequestDraft
    ) -> AIEditorRequest:
        """Create one request plus its initial ``requested`` event."""

        instruction_text = _validate_instruction_text(draft.instruction_text)
        instruction_expires_at = _validate_instruction_expiry(
            draft.instruction_expires_at
        )
        intent = _validated_intent(draft.intent_category)
        selected_scope = _validate_selected_scope(draft.selected_scope)

        now = datetime.now(UTC)
        request = AIEditorRequest(
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            target_entity_type=draft.target_entity_type,
            target_entity_id=draft.target_entity_id,
            parent_generation_trace_id=draft.parent_generation_trace_id,
            intent_category=intent.value,
            selected_scope=selected_scope,
            operation_constraints=_validate_operation_constraints(draft.operation_constraints),
            base_content_version=draft.base_content_version,
            locale=draft.locale,
            source_type_summary=draft.source_type_summary,
            generator_version=draft.generator_version,
            prompt_version=draft.prompt_version,
            model_id=draft.model_id,
            validator_version=draft.validator_version,
            instruction_text=instruction_text,
            instruction_expires_at=instruction_expires_at,
            outcome_state=EditorLifecycleEventType.REQUESTED.value,
            created_at=now,
            updated_at=now,
        )
        await self._ensure_actor_belongs_to_tenant(actor)
        await self._repo._create_request(request)

        await self._insert_event(
            tenant_id=request.tenant_id,
            request_id=request.id,
            actor_id=actor.actor_id,
            draft=EditorEventDraft(
                event_type=EditorLifecycleEventType.REQUESTED,
                event_key="requested",
            ),
            current_outcome=None,
        )
        logger.info(
            "editor_assistant request created: request_id=%s tenant=%s intent=%s",
            request.id,
            request.tenant_id,
            intent.value,
        )
        return request

    async def create_or_reuse_request(
        self,
        actor: EditorActorContext,
        draft: EditorRequestDraft,
        *,
        request_key: str | UUID,
    ) -> AIEditorRequest:
        """Atomically create or reuse one canonical idempotent request.

        ``request_key`` is validated and reduced to a tenant-namespaced UUID;
        it is never stored or reflected. The durable row stores only one
        canonical instruction plus one SHA-256 fingerprint in the dedicated
        nullable ``request_fingerprint_sha256`` column; business
        ``operation_constraints`` remain unchanged.
        """

        normalized_key = _validate_request_key(request_key)
        await self._ensure_actor_belongs_to_tenant(actor)
        request = _build_idempotent_request(actor, draft, normalized_key)
        claimed, created = await self._repo.claim_request(request)
        if claimed is None:
            raise EditorIdempotencyCollisionError(
                "Editor request idempotency collision"
            )
        if not created:
            stored_fingerprint = claimed.request_fingerprint_sha256
            expected_fingerprint = request.request_fingerprint_sha256
            if (
                not isinstance(stored_fingerprint, str)
                or not _SHA256_PATTERN.fullmatch(stored_fingerprint)
                or not isinstance(expected_fingerprint, str)
                or stored_fingerprint != expected_fingerprint
            ):
                raise EditorIdempotencyCollisionError(
                    "Editor request idempotency collision"
                )
            return claimed

        await self._insert_event(
            tenant_id=claimed.tenant_id,
            request_id=claimed.id,
            actor_id=actor.actor_id,
            draft=EditorEventDraft(
                event_type=EditorLifecycleEventType.REQUESTED,
                event_key="requested",
            ),
            current_outcome=None,
        )
        logger.info(
            "editor_assistant idempotent request created: request_id=%s tenant=%s intent=%s",
            claimed.id,
            claimed.tenant_id,
            claimed.intent_category,
        )
        return claimed

    async def record_event(
        self,
        actor: EditorActorContext,
        request_id: Any,
        draft: EditorEventDraft,
    ) -> tuple[AIEditorRequest, AIEditorRequestEvent | None]:
        """Record one lifecycle event idempotently and append-only.

        Returns ``(request, event)``. ``event`` is ``None`` when the exact
        event (same type and validated metadata) was already recorded — the
        replay is then a no-op and history is not rewritten. A reused key
        with different content raises ``EditorIdempotencyCollisionError``.
        """

        event_key = _validate_event_key(draft.event_key)
        validated_metadata = validate_event_metadata(draft.metadata)
        request = await self._repo.get_request_for_update(request_id, actor.tenant_id)
        if request is None:
            raise EditorRequestServiceError("Editor request not found in this tenant")
        await self._ensure_actor_belongs_to_tenant(actor)

        event_type_value = draft.event_type.value
        existing = await self._repo.get_event(
            request.id, actor.tenant_id, event_key
        )
        if existing is not None:
            if (
                existing.event_type != event_type_value
                or existing.metadata_json != validated_metadata
                or existing.actor_id != actor.actor_id
            ):
                raise EditorIdempotencyCollisionError("Editor event idempotency collision")
            # Idempotent exact replay: never rewrite, never re-apply outcome.
            return request, None

        current_outcome = cast(str | None, request.outcome_state)
        if not can_record_outcome(current_outcome, event_type_value):
            raise EditorLifecycleTransitionError(
                f"Cannot record {event_type_value} after {current_outcome}"
            )

        event = await self._insert_event(
            tenant_id=request.tenant_id,
            request_id=request.id,
            actor_id=actor.actor_id,
            draft=EditorEventDraft(
                event_type=draft.event_type,
                event_key=event_key,
                metadata=validated_metadata,
            ),
            current_outcome=current_outcome,
        )
        request = await self._repo.refresh_outcome_state(request, event_type_value)
        logger.info(
            "editor_assistant event recorded: request_id=%s event=%s",
            request.id,
            event_type_value,
        )
        return request, event

    async def build_analytics_projection(
        self, actor: EditorActorContext, request_id: Any
    ) -> dict[str, Any] | None:
        """Return the allowlisted analytics projection for one request."""

        request = await self._repo.get_request(request_id, actor.tenant_id)
        if request is None:
            return None
        events = await self._repo.list_events(request.id, actor.tenant_id)
        return {
            "request": project_request(request),
            "events": [project_event(event) for event in events],
        }

    async def _insert_event(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        actor_id: Any,
        draft: EditorEventDraft,
        current_outcome: str | None,
    ) -> AIEditorRequestEvent:
        if not can_record_outcome(current_outcome, draft.event_type.value):
            raise EditorLifecycleTransitionError(
                f"Cannot record {draft.event_type.value} after {current_outcome}"
            )
        event = AIEditorRequestEvent(
            tenant_id=tenant_id,
            request_id=request_id,
            event_type=draft.event_type.value,
            event_key=_validate_event_key(draft.event_key),
            sequence_no=await self._repo.next_event_sequence(request_id, tenant_id),
            actor_id=actor_id,
            metadata_json=draft.metadata,
        )
        return await self._repo._append_event(event)

    async def _ensure_actor_belongs_to_tenant(self, actor: EditorActorContext) -> None:
        if not await self._repo.actor_exists_for_tenant(actor.actor_id, actor.tenant_id):
            raise EditorRequestServiceError("Editor actor is not available in this tenant")


def _validated_intent(intent_category: str) -> EditorIntentCategory:
    try:
        return EditorIntentCategory(intent_category)
    except ValueError:
        raise EditorRequestServiceError("Invalid editor intent category") from None


def _validate_request_key(request_key: str | UUID) -> str:
    if isinstance(request_key, UUID):
        return f"uuid:{request_key}"
    if not isinstance(request_key, str):
        raise EditorRequestServiceError("Invalid editor request key")
    value = request_key
    if _REQUEST_KEY_PATTERN.fullmatch(value) is None:
        raise EditorRequestServiceError("Invalid editor request key")
    try:
        parsed_uuid = UUID(value)
    except ValueError:
        return f"opaque:{value}"
    return f"uuid:{parsed_uuid}"


def _canonical_text(value: Any) -> str | None:
    if value is None:
        return None
    return unicodedata.normalize("NFC", str(value).strip())


def _canonical_uuid(value: Any) -> tuple[UUID, str]:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise EditorRequestServiceError("Invalid editor request identity") from None
    return parsed, str(parsed)


def _validate_instruction_expiry(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise EditorRequestServiceError("Invalid editor instruction expiry")
    return value


def _build_idempotent_request(
    actor: EditorActorContext,
    draft: EditorRequestDraft,
    request_key: str,
) -> AIEditorRequest:
    instruction = _validate_instruction_text(draft.instruction_text)
    instruction_expires_at = _validate_instruction_expiry(
        draft.instruction_expires_at
    )
    intent = _validated_intent(draft.intent_category)
    selected_scope = _validate_selected_scope(draft.selected_scope)
    constraints = _validate_operation_constraints(draft.operation_constraints)
    tenant_id, canonical_tenant_id = _canonical_uuid(actor.tenant_id)
    actor_id, canonical_actor_id = _canonical_uuid(actor.actor_id)
    target_entity_id, canonical_target_entity_id = _canonical_uuid(
        draft.target_entity_id
    )

    instruction_digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    fingerprint_payload = {
        "schema": _REQUEST_FINGERPRINT_SCHEMA,
        "tenant_id": canonical_tenant_id,
        "actor_id": canonical_actor_id,
        "target_entity_type": _canonical_text(draft.target_entity_type),
        "target_entity_id": canonical_target_entity_id,
        "parent_generation_trace_id": _canonical_text(
            draft.parent_generation_trace_id
        ),
        "intent_category": intent.value,
        "selected_scope": selected_scope,
        "operation_constraints": constraints,
        "base_content_version": _canonical_text(draft.base_content_version),
        "locale": _canonical_text(draft.locale),
        "source_type_summary": _canonical_text(draft.source_type_summary),
        "generator_version": _canonical_text(draft.generator_version),
        "prompt_version": _canonical_text(draft.prompt_version),
        "model_id": _canonical_text(draft.model_id),
        "validator_version": _canonical_text(draft.validator_version),
        "instruction_sha256": instruction_digest,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    key_digest = hashlib.sha256(request_key.encode("ascii")).hexdigest()
    request_id = uuid5(
        _REQUEST_ID_NAMESPACE,
        f"{canonical_tenant_id}:{key_digest}",
    )
    now = datetime.now(UTC)
    return AIEditorRequest(
        id=request_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        target_entity_type=fingerprint_payload["target_entity_type"],
        target_entity_id=target_entity_id,
        parent_generation_trace_id=fingerprint_payload[
            "parent_generation_trace_id"
        ],
        intent_category=intent.value,
        selected_scope=selected_scope,
        operation_constraints=constraints,
        request_fingerprint_sha256=fingerprint,
        base_content_version=fingerprint_payload["base_content_version"],
        locale=fingerprint_payload["locale"],
        source_type_summary=fingerprint_payload["source_type_summary"],
        generator_version=fingerprint_payload["generator_version"],
        prompt_version=fingerprint_payload["prompt_version"],
        model_id=fingerprint_payload["model_id"],
        validator_version=fingerprint_payload["validator_version"],
        instruction_text=instruction,
        instruction_expires_at=instruction_expires_at,
        outcome_state=EditorLifecycleEventType.REQUESTED.value,
        created_at=now,
        updated_at=now,
    )


__all__ = [
    "EditorActorContext",
    "EditorEventDraft",
    "EditorIdempotencyCollisionError",
    "EditorLifecycleTransitionError",
    "EditorMetadataValidationError",
    "EditorRequestDraft",
    "EditorRequestService",
    "EditorRequestServiceError",
    "project_event",
    "project_request",
]
