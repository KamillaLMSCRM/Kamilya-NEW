"""Repository boundary for AI editor request and lifecycle event persistence."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, literal, null, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User

from .models import AIEditorRequest, AIEditorRequestEvent, AIEditorRequestPreview
from .patch_contract import PatchContractError, PatchIdempotencyCollisionError

_PREVIEW_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CLAIM_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}")
_MAX_RESULT_BYTES = 65_536
_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "raw_instruction",
        "instruction_text",
        "raw_provider_response",
        "provider_response",
        "source_excerpt",
        "source_excerpts",
        "exception_text",
        "traceback",
    }
)
_SAFE_FAILURE_CODES = frozenset(
    {
        "provider_timeout",
        "provider_unavailable",
        "provider_output_unparseable",
        "contract_violation",
        "validation_blocked",
        "stale_base_version",
        "rejected_out_of_scope",
        "source_evidence_unavailable",
        "requires_new_draft_revision",
        "internal_error",
    }
)


@dataclass(frozen=True)
class EditorPreviewRecord:
    """Safe immutable projection of one durable preview row."""

    id: UUID
    tenant_id: UUID
    request_id: UUID
    preview_key: str
    payload_fingerprint: str
    state: str
    owns_claim: bool
    claim_token: str | None
    completed_result: Mapping[str, Any] | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    failed_at: datetime | None


def _preview_identity(
    tenant_id: Any,
    request_id: Any,
    preview_key: str,
    payload_fingerprint: str | None = None,
) -> tuple[UUID, UUID, str, str | None]:
    try:
        normalized_tenant = UUID(str(tenant_id))
        normalized_request = UUID(str(request_id))
    except (TypeError, ValueError, AttributeError):
        raise PatchContractError("Invalid editor preview identity") from None
    if not isinstance(preview_key, str) or _PREVIEW_KEY.fullmatch(preview_key) is None:
        raise PatchContractError("Invalid editor preview identity")
    if payload_fingerprint is not None and (
        not isinstance(payload_fingerprint, str)
        or _SHA256.fullmatch(payload_fingerprint) is None
    ):
        raise PatchContractError("Invalid editor preview identity")
    return normalized_tenant, normalized_request, preview_key, payload_fingerprint


def _normalize_result(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PatchContractError("Invalid editor preview result")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_RESULT_BYTES:
            raise ValueError
        normalized = json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        raise PatchContractError("Invalid editor preview result") from None
    if not isinstance(normalized, dict):
        raise PatchContractError("Invalid editor preview result")
    if _contains_forbidden_result_key(normalized):
        raise PatchContractError("Invalid editor preview result")
    return cast(dict[str, Any], normalized)


def _contains_forbidden_result_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in _FORBIDDEN_RESULT_KEYS
            or _contains_forbidden_result_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_result_key(item) for item in value)
    return False


def _valid_claim_token(value: Any) -> bool:
    return isinstance(value, str) and _CLAIM_TOKEN.fullmatch(value) is not None


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(value)
    return value


def _preview_record(
    preview: AIEditorRequestPreview,
    *,
    owns_claim: bool = False,
    claim_token: str | None = None,
) -> EditorPreviewRecord:
    result = None
    if preview.state == "completed":
        result = _freeze_json(dict(preview.completed_result_json))
    return EditorPreviewRecord(
        id=cast(UUID, preview.id),
        tenant_id=cast(UUID, preview.tenant_id),
        request_id=cast(UUID, preview.request_id),
        preview_key=cast(str, preview.preview_key),
        payload_fingerprint=cast(str, preview.payload_fingerprint),
        state=cast(str, preview.state),
        owns_claim=owns_claim,
        claim_token=claim_token if owns_claim else None,
        completed_result=result,
        failure_code=(
            cast(str | None, preview.failure_code)
            if preview.state == "failed"
            else None
        ),
        created_at=cast(datetime, preview.created_at),
        updated_at=cast(datetime, preview.updated_at),
        completed_at=cast(datetime | None, preview.completed_at),
        failed_at=cast(datetime | None, preview.failed_at),
    )


class EditorRequestRepository:
    """Owns all DB access for editor requests and lifecycle events."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def _create_request(self, request: AIEditorRequest) -> AIEditorRequest:
        """Insert one request row. Caller owns flush/commit semantics."""

        self._db.add(request)
        await self._db.flush()
        return request

    async def claim_request(
        self, request: AIEditorRequest
    ) -> tuple[AIEditorRequest | None, bool]:
        """Atomically insert one deterministic request or return its existing row.

        Authority remains the service caller's responsibility. The database
        primary key is the concurrency boundary: PostgreSQL waits for a
        competing transaction and resolves the insert through ``ON CONFLICT``
        rather than a check-then-insert race.
        """

        statement = (
            pg_insert(AIEditorRequest)
            .values(
                id=request.id,
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
                target_entity_type=request.target_entity_type,
                target_entity_id=request.target_entity_id,
                parent_generation_trace_id=request.parent_generation_trace_id,
                intent_category=request.intent_category,
                selected_scope=request.selected_scope,
                operation_constraints=request.operation_constraints,
                request_fingerprint_sha256=request.request_fingerprint_sha256,
                base_content_version=request.base_content_version,
                locale=request.locale,
                source_type_summary=request.source_type_summary,
                generator_version=request.generator_version,
                prompt_version=request.prompt_version,
                model_id=request.model_id,
                validator_version=request.validator_version,
                instruction_text=request.instruction_text,
                instruction_expires_at=request.instruction_expires_at,
                outcome_state=request.outcome_state,
                created_at=request.created_at,
                updated_at=request.updated_at,
            )
            .on_conflict_do_nothing(index_elements=[AIEditorRequest.id])
            .returning(AIEditorRequest)
        )
        inserted = (await self._db.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return inserted, True
        return await self.get_request(request.id, request.tenant_id), False

    async def actor_exists_for_tenant(self, actor_id: Any, tenant_id: Any) -> bool:
        """Check that the authenticated actor belongs to the request tenant."""

        result = await self._db.execute(
            select(User.id).where(
                User.id == actor_id,
                User.tenant_id == tenant_id,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_request(self, request_id: Any, tenant_id: Any) -> AIEditorRequest | None:
        """Load one request strictly scoped to ``tenant_id``."""

        result = await self._db.execute(
            select(AIEditorRequest).where(
                AIEditorRequest.id == request_id,
                AIEditorRequest.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_request_for_update(
        self, request_id: Any, tenant_id: Any
    ) -> AIEditorRequest | None:
        """Load one request with a row lock for lifecycle transitions.

        ``SELECT ... FOR UPDATE`` serializes concurrent transitions on the
        same request inside the caller-owned transaction, preventing two
        competing events from both committing as valid from the same prior
        outcome state.
        """

        result = await self._db.execute(
            select(AIEditorRequest).where(
                AIEditorRequest.id == request_id,
                AIEditorRequest.tenant_id == tenant_id,
            ).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_event(
        self,
        request_id: Any,
        tenant_id: Any,
        event_key: str,
    ) -> AIEditorRequestEvent | None:
        """Load one lifecycle event by idempotency key, tenant-scoped.

        Contract: ``event_key`` is globally unique within one request, so
        lookup uses (tenant, request, event_key) only.
        """

        result = await self._db.execute(
            select(AIEditorRequestEvent).where(
                AIEditorRequestEvent.request_id == request_id,
                AIEditorRequestEvent.tenant_id == tenant_id,
                AIEditorRequestEvent.event_key == event_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_events(self, request_id: Any, tenant_id: Any) -> list[AIEditorRequestEvent]:
        """All events for one request in append order."""

        result = await self._db.execute(
            select(AIEditorRequestEvent)
            .where(
                AIEditorRequestEvent.request_id == request_id,
                AIEditorRequestEvent.tenant_id == tenant_id,
            )
            .order_by(AIEditorRequestEvent.sequence_no)
        )
        return list(result.scalars().all())

    async def next_event_sequence(self, request_id: Any, tenant_id: Any) -> int:
        """Return the next monotonic sequence while the request row is locked."""

        result = await self._db.execute(
            select(func.coalesce(func.max(AIEditorRequestEvent.sequence_no), 0) + 1).where(
                AIEditorRequestEvent.request_id == request_id,
                AIEditorRequestEvent.tenant_id == tenant_id,
            )
        )
        return int(result.scalar_one())

    async def _append_event(self, event: AIEditorRequestEvent) -> AIEditorRequestEvent:
        """Insert one lifecycle event. Never updates existing rows."""

        self._db.add(event)
        await self._db.flush()
        return event

    async def refresh_outcome_state(
        self, request: AIEditorRequest, event_type: str
    ) -> AIEditorRequest:
        """Move the request outcome to ``event_type`` and persist it."""

        mutable_request = cast(Any, request)
        mutable_request.outcome_state = event_type
        mutable_request.updated_at = datetime.now(UTC)
        await self._db.flush()
        return request

    async def _request_exists(self, tenant_id: UUID, request_id: UUID) -> bool:
        result = await self._db.execute(
            select(AIEditorRequest.id)
            .where(
                AIEditorRequest.tenant_id == tenant_id,
                AIEditorRequest.id == request_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _preview_by_key(
        self, tenant_id: UUID, preview_key: str
    ) -> AIEditorRequestPreview | None:
        result = await self._db.execute(
            select(AIEditorRequestPreview).where(
                AIEditorRequestPreview.tenant_id == tenant_id,
                AIEditorRequestPreview.preview_key == preview_key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _require_same_payload(
        preview: AIEditorRequestPreview,
        request_id: UUID,
        payload_fingerprint: str,
    ) -> None:
        if (
            preview.request_id != request_id
            or preview.payload_fingerprint != payload_fingerprint
        ):
            raise PatchIdempotencyCollisionError(
                "Editor preview idempotency collision"
            )

    async def claim_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
    ) -> EditorPreviewRecord | None:
        """Atomically own a new preview or observe its canonical state."""

        tenant, request, key, fingerprint = _preview_identity(
            tenant_id, request_id, preview_key, payload_fingerprint
        )
        assert fingerprint is not None
        if not await self._request_exists(tenant, request):
            return None

        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        statement = (
            pg_insert(AIEditorRequestPreview)
            .from_select(
                [
                    "tenant_id",
                    "request_id",
                    "preview_key",
                    "payload_fingerprint",
                    "state",
                    "claim_token_sha256",
                ],
                select(
                    literal(tenant),
                    literal(request),
                    literal(key),
                    literal(fingerprint),
                    literal("pending"),
                    literal(digest),
                ),
                include_defaults=False,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AIEditorRequestPreview.tenant_id,
                    AIEditorRequestPreview.preview_key,
                ]
            )
            .returning(AIEditorRequestPreview)
        )
        inserted = (await self._db.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return _preview_record(inserted, owns_claim=True, claim_token=token)

        existing = await self._preview_by_key(tenant, key)
        if existing is None:
            return None
        self._require_same_payload(existing, request, fingerprint)
        return _preview_record(existing)

    async def read_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
    ) -> EditorPreviewRecord | None:
        """Read a preview only through its complete tenant/request identity."""

        tenant, request, key, _ = _preview_identity(
            tenant_id, request_id, preview_key
        )
        result = await self._db.execute(
            select(AIEditorRequestPreview).where(
                AIEditorRequestPreview.tenant_id == tenant,
                AIEditorRequestPreview.request_id == request,
                AIEditorRequestPreview.preview_key == key,
            )
        )
        preview = result.scalar_one_or_none()
        return None if preview is None else _preview_record(preview)

    async def complete_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
        completed_result: Mapping[str, Any],
    ) -> EditorPreviewRecord | None:
        """Complete a pending preview only for its current token owner."""

        tenant, request, key, fingerprint = _preview_identity(
            tenant_id, request_id, preview_key, payload_fingerprint
        )
        assert fingerprint is not None
        normalized_result = _normalize_result(completed_result)
        if not _valid_claim_token(claim_token):
            return None
        digest = hashlib.sha256(claim_token.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        statement = (
            update(AIEditorRequestPreview)
            .where(
                AIEditorRequestPreview.tenant_id == tenant,
                AIEditorRequestPreview.request_id == request,
                AIEditorRequestPreview.preview_key == key,
                AIEditorRequestPreview.payload_fingerprint == fingerprint,
                AIEditorRequestPreview.state == "pending",
                AIEditorRequestPreview.claim_token_sha256 == digest,
            )
            .values(
                state="completed",
                claim_token_sha256=None,
                completed_result_json=normalized_result,
                failure_code=None,
                completed_at=now,
                failed_at=None,
                updated_at=now,
            )
            .returning(AIEditorRequestPreview)
        )
        completed = (await self._db.execute(statement)).scalar_one_or_none()
        if completed is not None:
            return _preview_record(completed)
        existing = await self._preview_by_key(tenant, key)
        if existing is not None:
            self._require_same_payload(existing, request, fingerprint)
        return None

    async def fail_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
        failure_code: Any,
    ) -> EditorPreviewRecord | None:
        """Fail a pending preview without persisting reflected error text."""

        tenant, request, key, fingerprint = _preview_identity(
            tenant_id, request_id, preview_key, payload_fingerprint
        )
        assert fingerprint is not None
        if not _valid_claim_token(claim_token):
            return None
        safe_code = (
            failure_code
            if isinstance(failure_code, str) and failure_code in _SAFE_FAILURE_CODES
            else "internal_error"
        )
        digest = hashlib.sha256(claim_token.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        statement = (
            update(AIEditorRequestPreview)
            .where(
                AIEditorRequestPreview.tenant_id == tenant,
                AIEditorRequestPreview.request_id == request,
                AIEditorRequestPreview.preview_key == key,
                AIEditorRequestPreview.payload_fingerprint == fingerprint,
                AIEditorRequestPreview.state == "pending",
                AIEditorRequestPreview.claim_token_sha256 == digest,
            )
            .values(
                state="failed",
                claim_token_sha256=None,
                completed_result_json=null(),
                failure_code=safe_code,
                completed_at=None,
                failed_at=now,
                updated_at=now,
            )
            .returning(AIEditorRequestPreview)
        )
        failed = (await self._db.execute(statement)).scalar_one_or_none()
        if failed is not None:
            return _preview_record(failed)
        existing = await self._preview_by_key(tenant, key)
        if existing is not None:
            self._require_same_payload(existing, request, fingerprint)
        return None

    async def reclaim_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
    ) -> EditorPreviewRecord | None:
        """Atomically move one failed preview back to one pending owner."""

        tenant, request, key, fingerprint = _preview_identity(
            tenant_id, request_id, preview_key, payload_fingerprint
        )
        assert fingerprint is not None
        existing = await self._preview_by_key(tenant, key)
        if existing is None:
            return None
        self._require_same_payload(existing, request, fingerprint)
        if existing.state != "failed":
            return _preview_record(existing)

        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        statement = (
            update(AIEditorRequestPreview)
            .where(
                AIEditorRequestPreview.tenant_id == tenant,
                AIEditorRequestPreview.request_id == request,
                AIEditorRequestPreview.preview_key == key,
                AIEditorRequestPreview.payload_fingerprint == fingerprint,
                AIEditorRequestPreview.state == "failed",
            )
            .values(
                state="pending",
                claim_token_sha256=digest,
                completed_result_json=null(),
                failure_code=None,
                completed_at=None,
                failed_at=None,
                updated_at=now,
            )
            .returning(AIEditorRequestPreview)
        )
        reclaimed = (await self._db.execute(statement)).scalar_one_or_none()
        if reclaimed is not None:
            return _preview_record(reclaimed, owns_claim=True, claim_token=token)
        current = await self._preview_by_key(tenant, key)
        if current is None:
            return None
        self._require_same_payload(current, request, fingerprint)
        return _preview_record(current)
