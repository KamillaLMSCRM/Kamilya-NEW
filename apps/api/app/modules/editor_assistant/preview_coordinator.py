"""Durable idempotent coordination for one resolved question preview.

This module owns the claim/terminal-state boundary around the pure preview
application. It does not create requests, resolve context, call providers,
emit telemetry, or mutate course content.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Awaitable, Mapping
from typing import Any, Protocol, TypeGuard, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from .patch_contract import PatchIdempotencyCollisionError
from .preview_application import PreviewIdentityFactory
from .question_context import ResolvedQuestionContext
from .repository import EditorPreviewRecord
from .schemas import (
    EditorApplicability,
    EditorAssistantFailure,
    EditorAssistantFailureCode,
    EditorAssistantPreviewRequest,
    EditorAssistantPreviewResponse,
    EditorAssistantSourceProjection,
    EditorPreviewState,
    editor_assistant_failure_contract,
)

_SCHEMA_VERSION = "editor_assistant.preview_coordinator.v1"


class AIEditorRequestPreviewRepository(Protocol):
    """The exact persistence methods required by the coordinator."""

    async def claim_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
    ) -> EditorPreviewRecord | None: ...

    async def read_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
    ) -> EditorPreviewRecord | None: ...

    async def complete_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
        completed_result: Mapping[str, Any],
    ) -> EditorPreviewRecord | None: ...

    async def fail_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
        failure_code: Any,
    ) -> EditorPreviewRecord | None: ...


class PreviewApplicationRunner(Protocol):
    """Injected pure application boundary used only by the claim owner."""

    def __call__(
        self,
        context: ResolvedQuestionContext,
        request: EditorAssistantPreviewRequest,
        identity_factory: PreviewIdentityFactory,
    ) -> Awaitable[EditorAssistantPreviewResponse]: ...


def _payload_fingerprint(
    context: ResolvedQuestionContext,
    request: EditorAssistantPreviewRequest,
) -> str:
    normalized_instruction = " ".join(
        unicodedata.normalize("NFC", request.instruction).split()
    )
    metadata = {
        "schema_version": _SCHEMA_VERSION,
        "request_key": str(request.request_key),
        "preview_key": str(request.preview_key),
        "intent": request.intent.value,
        "tenant_id": str(context.tenant_id),
        "question_id": str(context.question_id),
        "context_snapshot_fingerprint": context.snapshot_fingerprint,
        "instruction_sha256": hashlib.sha256(
            normalized_instruction.encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_token(context: ResolvedQuestionContext) -> str:
    fingerprint = (
        context.snapshot_fingerprint
        if isinstance(context.snapshot_fingerprint, str)
        else "invalid"
    )
    return hashlib.sha256(
        f"kamilya-question-preview-v1:{fingerprint}".encode()
    ).hexdigest()


def _fallback_preview_id(tenant_id: UUID, preview_key: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"kamilya-editor-preview:{tenant_id}:{preview_key}",
    )


def _neutral_snapshot_token(
    editor_request_id: UUID,
    request: EditorAssistantPreviewRequest,
) -> str:
    return hashlib.sha256(
        (
            "kamilya-question-preview-neutral-v1:"
            f"{editor_request_id}:{request.request_key}:{request.preview_key}"
        ).encode()
    ).hexdigest()


def _failed_response(
    context: ResolvedQuestionContext,
    *,
    request_id: UUID,
    preview_id: UUID,
    code: EditorAssistantFailureCode,
    base_snapshot_token: str | None = None,
) -> EditorAssistantPreviewResponse:
    safe_code = (
        code
        if isinstance(code, EditorAssistantFailureCode)
        else EditorAssistantFailureCode.INTERNAL_ERROR
    )
    message, applicability = editor_assistant_failure_contract(safe_code)
    return EditorAssistantPreviewResponse(
        request_id=request_id,
        preview_id=preview_id,
        state=EditorPreviewState.FAILED,
        applicability=applicability,
        base_snapshot_token=base_snapshot_token or _snapshot_token(context),
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
        failure=EditorAssistantFailure(
            error_code=safe_code,
            message=message,
        ),
    )


def _pending_response(
    context: ResolvedQuestionContext,
    *,
    request_id: UUID,
    preview_id: UUID,
) -> EditorAssistantPreviewResponse:
    return EditorAssistantPreviewResponse(
        request_id=request_id,
        preview_id=preview_id,
        state=EditorPreviewState.PENDING,
        applicability=EditorApplicability.NOT_APPLICABLE,
        base_snapshot_token=_snapshot_token(context),
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
    )


def _record_is_bound(
    record: object,
    *,
    tenant_id: UUID,
    request_id: UUID,
    preview_key: str,
    fingerprint: str,
) -> TypeGuard[EditorPreviewRecord]:
    return (
        isinstance(record, EditorPreviewRecord)
        and record.tenant_id == tenant_id
        and record.request_id == request_id
        and record.preview_key == preview_key
        and record.payload_fingerprint == fingerprint
    )


def _stored_response(
    record: EditorPreviewRecord,
    context: ResolvedQuestionContext,
) -> EditorAssistantPreviewResponse:
    if record.state != "completed" or not isinstance(record.completed_result, Mapping):
        raise ValueError("stored preview is not a completed DTO")
    response = EditorAssistantPreviewResponse.model_validate(
        dict(record.completed_result)
    )
    if (
        response.state is not EditorPreviewState.COMPLETED
        or response.request_id != record.request_id
        or response.preview_id != record.id
    ):
        raise ValueError("stored preview identity is invalid")
    del context
    return response


def _stored_failure(
    record: EditorPreviewRecord,
    context: ResolvedQuestionContext,
) -> EditorAssistantPreviewResponse:
    try:
        code = EditorAssistantFailureCode(record.failure_code or "")
    except (TypeError, ValueError):
        code = EditorAssistantFailureCode.INTERNAL_ERROR
    return _failed_response(
        context,
        request_id=record.request_id,
        preview_id=record.id,
        code=code,
    )


def _observed_record_response(
    record: EditorPreviewRecord,
    context: ResolvedQuestionContext,
) -> EditorAssistantPreviewResponse:
    if record.state == "pending":
        return _pending_response(
            context,
            request_id=record.request_id,
            preview_id=record.id,
        )
    if record.state == "failed":
        return _stored_failure(record, context)
    if record.state == "completed":
        return _stored_response(record, context)
    raise ValueError("stored preview state is invalid")


async def _read_terminal_response(
    repository: AIEditorRequestPreviewRepository,
    context: ResolvedQuestionContext,
    *,
    tenant_id: UUID,
    request_id: UUID,
    preview_key: str,
    expected_fingerprint: str,
    expected_state: str,
    expected_failure: EditorAssistantFailureCode | None = None,
) -> EditorAssistantPreviewResponse | None:
    stored = await repository.read_preview(
        tenant_id=tenant_id,
        request_id=request_id,
        preview_key=preview_key,
    )
    if not _record_is_bound(
        stored,
        tenant_id=tenant_id,
        request_id=request_id,
        preview_key=preview_key,
        fingerprint=expected_fingerprint,
    ) or stored.state != expected_state:
        return None
    if expected_failure is not None and stored.failure_code != expected_failure.value:
        return None
    try:
        return _observed_record_response(stored, context)
    except Exception:
        return None


async def _fail_once(
    repository: AIEditorRequestPreviewRepository,
    context: ResolvedQuestionContext,
    *,
    tenant_id: UUID,
    request_id: UUID,
    preview_key: str,
    payload_fingerprint: str,
    claim_token: str,
    code: EditorAssistantFailureCode,
) -> EditorAssistantPreviewResponse:
    try:
        failed = await repository.fail_preview(
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key=preview_key,
            payload_fingerprint=payload_fingerprint,
            claim_token=claim_token,
            failure_code=code.value,
        )
        if failed is None:
            return _failed_response(
                context,
                request_id=request_id,
                preview_id=_fallback_preview_id(tenant_id, UUID(preview_key)),
                code=EditorAssistantFailureCode.INTERNAL_ERROR,
            )
        observed = await _read_terminal_response(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key=preview_key,
            expected_fingerprint=payload_fingerprint,
            expected_state="failed",
            expected_failure=code,
        )
        if observed is None:
            return _failed_response(
                context,
                request_id=request_id,
                preview_id=failed.id,
                code=EditorAssistantFailureCode.INTERNAL_ERROR,
            )
        return observed
    except Exception:
        return _failed_response(
            context,
            request_id=request_id,
            preview_id=_fallback_preview_id(tenant_id, UUID(preview_key)),
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )


async def coordinate_question_preview(
    *,
    tenant_id: UUID,
    editor_request_id: UUID,
    context: ResolvedQuestionContext,
    request: EditorAssistantPreviewRequest,
    repository: AIEditorRequestPreviewRepository,
    application_runner: PreviewApplicationRunner,
) -> EditorAssistantPreviewResponse:
    """Coordinate one durable, idempotent pure preview application."""

    preview_key = str(request.preview_key)
    fallback_preview_id = _fallback_preview_id(tenant_id, request.preview_key)
    if (
        not isinstance(tenant_id, UUID)
        or not isinstance(context.tenant_id, UUID)
        or context.tenant_id != tenant_id
    ):
        return _failed_response(
            context,
            request_id=editor_request_id,
            preview_id=fallback_preview_id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
            base_snapshot_token=_neutral_snapshot_token(editor_request_id, request),
        )
    try:
        fingerprint = _payload_fingerprint(context, request)
    except Exception:
        return _failed_response(
            context,
            request_id=editor_request_id,
            preview_id=fallback_preview_id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )

    try:
        claimed = await repository.claim_preview(
            tenant_id=tenant_id,
            request_id=editor_request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
        )
    except PatchIdempotencyCollisionError:
        return _failed_response(
            context,
            request_id=editor_request_id,
            preview_id=fallback_preview_id,
            code=EditorAssistantFailureCode.CONTRACT_VIOLATION,
        )
    except Exception:
        return _failed_response(
            context,
            request_id=editor_request_id,
            preview_id=fallback_preview_id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )

    if claimed is None:
        return _failed_response(
            context,
            request_id=editor_request_id,
            preview_id=fallback_preview_id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )
    if not _record_is_bound(
        claimed,
        tenant_id=tenant_id,
        request_id=editor_request_id,
        preview_key=preview_key,
        fingerprint=fingerprint,
    ):
        return _failed_response(
            context,
            request_id=editor_request_id,
            preview_id=fallback_preview_id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )

    if not claimed.owns_claim:
        try:
            return _observed_record_response(claimed, context)
        except Exception:
            return _failed_response(
                context,
                request_id=claimed.request_id,
                preview_id=claimed.id,
                code=EditorAssistantFailureCode.INTERNAL_ERROR,
            )

    if not isinstance(claimed.claim_token, str) or not claimed.claim_token:
        return _failed_response(
            context,
            request_id=claimed.request_id,
            preview_id=claimed.id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )

    def identity_factory(_: EditorAssistantPreviewRequest) -> tuple[UUID, UUID]:
        return claimed.request_id, claimed.id

    try:
        response = await application_runner(
            context,
            request,
            cast(PreviewIdentityFactory, identity_factory),
        )
    except Exception:
        return await _fail_once(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
            claim_token=claimed.claim_token,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )

    if not isinstance(response, EditorAssistantPreviewResponse):
        return await _fail_once(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
            claim_token=claimed.claim_token,
            code=EditorAssistantFailureCode.CONTRACT_VIOLATION,
        )

    if (
        response.request_id != claimed.request_id
        or response.preview_id != claimed.id
    ):
        return await _fail_once(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
            claim_token=claimed.claim_token,
            code=EditorAssistantFailureCode.CONTRACT_VIOLATION,
        )

    if response.state is EditorPreviewState.FAILED:
        code = (
            response.failure.error_code
            if response.failure is not None
            else EditorAssistantFailureCode.CONTRACT_VIOLATION
        )
        return await _fail_once(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
            claim_token=claimed.claim_token,
            code=code,
        )

    if (
        response.state is not EditorPreviewState.COMPLETED
    ):
        return await _fail_once(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
            claim_token=claimed.claim_token,
            code=EditorAssistantFailureCode.CONTRACT_VIOLATION,
        )

    try:
        completed = await repository.complete_preview(
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            payload_fingerprint=fingerprint,
            claim_token=claimed.claim_token,
            completed_result=response.model_dump(mode="json"),
        )
        if completed is None:
            return _failed_response(
                context,
                request_id=claimed.request_id,
                preview_id=claimed.id,
                code=EditorAssistantFailureCode.INTERNAL_ERROR,
            )
        observed = await _read_terminal_response(
            repository,
            context,
            tenant_id=tenant_id,
            request_id=claimed.request_id,
            preview_key=preview_key,
            expected_fingerprint=fingerprint,
            expected_state="completed",
        )
        if observed is None:
            return _failed_response(
                context,
                request_id=claimed.request_id,
                preview_id=claimed.id,
                code=EditorAssistantFailureCode.INTERNAL_ERROR,
            )
        return observed
    except Exception:
        return _failed_response(
            context,
            request_id=claimed.request_id,
            preview_id=claimed.id,
            code=EditorAssistantFailureCode.INTERNAL_ERROR,
        )


__all__ = [
    "AIEditorRequestPreviewRepository",
    "PreviewApplicationRunner",
    "coordinate_question_preview",
]
