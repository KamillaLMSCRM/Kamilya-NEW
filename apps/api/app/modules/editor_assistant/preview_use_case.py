"""Pure application orchestration for one question-assistant preview.

Ownership boundaries are explicit: context resolution owns tenant-safe reads,
``EditorRequestService`` owns request-level idempotency, and the accepted
preview coordinator owns preview-level idempotency and AI invocation.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_roles import UserRole
from app.models.users import User

from .preview_coordinator import (
    AIEditorRequestPreviewRepository,
    PreviewApplicationRunner,
    coordinate_question_preview,
)
from .question_context import (
    AuthorizedEditorRole,
    QuestionContextError,
    QuestionContextFailureCode,
    ResolvedQuestionContext,
    resolve_question_context,
)
from .schemas import EditorAssistantPreviewRequest, EditorAssistantPreviewResponse
from .service import (
    EditorActorContext,
    EditorIdempotencyCollisionError,
    EditorRequestDraft,
    EditorRequestService,
    EditorRequestServiceError,
)
from .taxonomy import EditorIntentCategory


class PreviewUseCaseFailureCode(StrEnum):
    AUTHORIZATION_FAILED = "authorization_failed"
    CONTEXT_UNAVAILABLE = "question_context_unavailable"
    REQUIRES_NEW_DRAFT_REVISION = "requires_new_draft_revision"
    SOURCE_EVIDENCE_UNAVAILABLE = "source_evidence_unavailable"
    NOT_APPLICABLE = "not_applicable"
    MALFORMED_QUESTION = "malformed_question"
    UNSUPPORTED_INTENT = "unsupported_intent"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INTERNAL_ERROR = "internal_error"


_FAILURE_MESSAGES: dict[PreviewUseCaseFailureCode, str] = {
    PreviewUseCaseFailureCode.AUTHORIZATION_FAILED: "Editor access is unavailable.",
    PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE: "Question context is unavailable.",
    PreviewUseCaseFailureCode.REQUIRES_NEW_DRAFT_REVISION: (
        "A new draft revision is required."
    ),
    PreviewUseCaseFailureCode.SOURCE_EVIDENCE_UNAVAILABLE: (
        "Verified source evidence is unavailable."
    ),
    PreviewUseCaseFailureCode.NOT_APPLICABLE: "Question type is not supported.",
    PreviewUseCaseFailureCode.MALFORMED_QUESTION: "Question structure is invalid.",
    PreviewUseCaseFailureCode.UNSUPPORTED_INTENT: "Editor intent is not supported.",
    PreviewUseCaseFailureCode.IDEMPOTENCY_CONFLICT: (
        "Editor request idempotency conflict."
    ),
    PreviewUseCaseFailureCode.INTERNAL_ERROR: "Preview preparation failed.",
}


class PreviewUseCaseError(RuntimeError):
    """Typed, bounded, non-reflecting application failure."""

    def __init__(self, code: PreviewUseCaseFailureCode) -> None:
        self.code = code
        super().__init__(_FAILURE_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class TenantBoundEditorPrincipal:
    """One immutable effective tenant authority for editor operations.

    Direct platform superadmin authority (``tenant_id=None``) and platform
    impersonation are intentionally unsupported. A later audited impersonation
    contract must carry effective-tenant and audit-actor identities separately;
    this principal must never persist the platform operator as a tenant actor.
    """

    tenant_id: UUID
    actor_user_id: UUID
    effective_role: AuthorizedEditorRole | str


class ActorAuthorizationError(RuntimeError):
    """Bounded non-enumerating tenant-actor authorization failure."""

    def __init__(self) -> None:
        super().__init__("Editor access is unavailable.")


class TenantEditorActorAuthorizer(Protocol):
    def __call__(
        self,
        db: AsyncSession,
        principal: TenantBoundEditorPrincipal,
    ) -> Awaitable[TenantBoundEditorPrincipal]: ...


async def authorize_tenant_editor_principal(
    db: AsyncSession,
    principal: TenantBoundEditorPrincipal,
) -> TenantBoundEditorPrincipal:
    """Verify one active tenant-bound methodologist or superadmin user."""

    if type(principal) is not TenantBoundEditorPrincipal:
        raise ActorAuthorizationError
    if not isinstance(principal.tenant_id, UUID) or not isinstance(
        principal.actor_user_id, UUID
    ):
        raise ActorAuthorizationError
    try:
        role = AuthorizedEditorRole(principal.effective_role)
    except (TypeError, ValueError):
        raise ActorAuthorizationError from None
    if role not in {
        AuthorizedEditorRole.METHODOLOGIST,
        AuthorizedEditorRole.SUPERADMIN,
    }:
        raise ActorAuthorizationError
    result = await db.execute(
        select(User)
        .where(
            User.id == principal.actor_user_id,
            User.tenant_id == principal.tenant_id,
            User.is_active.is_(True),
            User.status == "active",
        )
        .limit(1)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ActorAuthorizationError
    if user.role != role.value:
        assigned_role = await db.execute(
            select(UserRole.id)
            .where(
                UserRole.user_id == principal.actor_user_id,
                UserRole.tenant_id == principal.tenant_id,
                UserRole.role == role.value,
            )
            .limit(1)
        )
        if assigned_role.scalar_one_or_none() is None:
            raise ActorAuthorizationError
    return TenantBoundEditorPrincipal(
        principal.tenant_id,
        principal.actor_user_id,
        role,
    )


class QuestionContextResolver(Protocol):
    def __call__(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        authorized_role: AuthorizedEditorRole | str,
        quiz_id: UUID,
        question_id: UUID,
    ) -> Awaitable[ResolvedQuestionContext]: ...


class PreviewCoordinator(Protocol):
    def __call__(
        self,
        *,
        tenant_id: UUID,
        editor_request_id: UUID,
        context: ResolvedQuestionContext,
        request: EditorAssistantPreviewRequest,
        repository: AIEditorRequestPreviewRepository,
        application_runner: PreviewApplicationRunner,
    ) -> Awaitable[EditorAssistantPreviewResponse]: ...


_CONTEXT_FAILURE_MAP = {
    QuestionContextFailureCode.CONTEXT_UNAVAILABLE: (
        PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE
    ),
    QuestionContextFailureCode.REQUIRES_NEW_DRAFT_REVISION: (
        PreviewUseCaseFailureCode.REQUIRES_NEW_DRAFT_REVISION
    ),
    QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE: (
        PreviewUseCaseFailureCode.SOURCE_EVIDENCE_UNAVAILABLE
    ),
    QuestionContextFailureCode.NOT_APPLICABLE: PreviewUseCaseFailureCode.NOT_APPLICABLE,
    QuestionContextFailureCode.MALFORMED_QUESTION: (
        PreviewUseCaseFailureCode.MALFORMED_QUESTION
    ),
}


class QuestionPreviewUseCase:
    """Compose the accepted context, request, and preview contracts."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        preview_repository: AIEditorRequestPreviewRepository,
        application_runner: PreviewApplicationRunner,
        request_service: EditorRequestService | None = None,
        actor_authorizer: TenantEditorActorAuthorizer = (
            authorize_tenant_editor_principal
        ),
        context_resolver: QuestionContextResolver = resolve_question_context,
        coordinator: PreviewCoordinator = coordinate_question_preview,
    ) -> None:
        self._db = db
        self._preview_repository = preview_repository
        self._application_runner = application_runner
        self._request_service = request_service or EditorRequestService(db)
        self._actor_authorizer = actor_authorizer
        self._context_resolver = context_resolver
        self._coordinator = coordinator

    async def execute(
        self,
        *,
        principal: TenantBoundEditorPrincipal,
        quiz_id: UUID,
        question_id: UUID,
        request: EditorAssistantPreviewRequest,
    ) -> EditorAssistantPreviewResponse:
        try:
            authorized_principal = await self._actor_authorizer(self._db, principal)
        except ActorAuthorizationError:
            raise PreviewUseCaseError(
                PreviewUseCaseFailureCode.AUTHORIZATION_FAILED
            ) from None
        except Exception:
            raise PreviewUseCaseError(PreviewUseCaseFailureCode.INTERNAL_ERROR) from None
        context = await self._resolve_context(
            tenant_id=authorized_principal.tenant_id,
            role=AuthorizedEditorRole(authorized_principal.effective_role),
            quiz_id=quiz_id,
            question_id=question_id,
        )
        _require_bound_context(
            context,
            tenant_id=authorized_principal.tenant_id,
            quiz_id=quiz_id,
            question_id=question_id,
        )
        try:
            intent = EditorIntentCategory(request.intent.value)
        except (TypeError, ValueError):
            raise PreviewUseCaseError(
                PreviewUseCaseFailureCode.UNSUPPORTED_INTENT
            ) from None

        draft = EditorRequestDraft(
            target_entity_type="quiz_question",
            target_entity_id=context.question_id,
            instruction_text=request.instruction,
            intent_category=intent.value,
            base_content_version=context.snapshot_fingerprint,
            locale=context.locale,
            selected_scope="question",
            operation_constraints={},
        )
        actor = EditorActorContext(
            tenant_id=authorized_principal.tenant_id,
            actor_id=authorized_principal.actor_user_id,
        )
        try:
            durable_request = await self._request_service.create_or_reuse_request(
                actor,
                draft,
                request_key=request.request_key,
            )
        except EditorIdempotencyCollisionError:
            raise PreviewUseCaseError(
                PreviewUseCaseFailureCode.IDEMPOTENCY_CONFLICT
            ) from None
        except EditorRequestServiceError:
            raise PreviewUseCaseError(PreviewUseCaseFailureCode.INTERNAL_ERROR) from None

        try:
            return await self._coordinator(
                tenant_id=authorized_principal.tenant_id,
                editor_request_id=durable_request.id,
                context=context,
                request=request,
                repository=self._preview_repository,
                application_runner=self._application_runner,
            )
        except Exception:
            raise PreviewUseCaseError(PreviewUseCaseFailureCode.INTERNAL_ERROR) from None

    async def _resolve_context(
        self,
        *,
        tenant_id: UUID,
        role: AuthorizedEditorRole,
        quiz_id: UUID,
        question_id: UUID,
    ) -> ResolvedQuestionContext:
        try:
            return await self._context_resolver(
                self._db,
                tenant_id=tenant_id,
                authorized_role=role,
                quiz_id=quiz_id,
                question_id=question_id,
            )
        except QuestionContextError as error:
            code = _CONTEXT_FAILURE_MAP.get(
                error.code,
                PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE,
            )
            raise PreviewUseCaseError(code) from None


def _require_bound_context(
    context: ResolvedQuestionContext,
    *,
    tenant_id: UUID,
    quiz_id: UUID,
    question_id: UUID,
) -> None:
    if (
        not isinstance(context, ResolvedQuestionContext)
        or context.tenant_id != tenant_id
        or context.quiz_id != quiz_id
        or context.question_id != question_id
    ):
        raise PreviewUseCaseError(PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE)


__all__ = [
    "ActorAuthorizationError",
    "PreviewUseCaseError",
    "PreviewUseCaseFailureCode",
    "QuestionPreviewUseCase",
    "TenantBoundEditorPrincipal",
    "TenantEditorActorAuthorizer",
    "authorize_tenant_editor_principal",
]
