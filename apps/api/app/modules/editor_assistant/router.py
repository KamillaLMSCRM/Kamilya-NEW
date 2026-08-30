"""Authenticated HTTP boundary for question-editor assistant previews."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.models.users import User
from app.modules.ai.llm_client import ResilientLLMClient
from app.modules.ai.question_preview import (
    QuestionPreviewContext,
    QuestionPreviewOutcome,
    preview_question_with_validation,
)

from .preview_application import (
    PreviewIdentityFactory,
    QuestionPreviewAdapter,
    create_question_preview_response,
)
from .preview_coordinator import (
    AIEditorRequestPreviewRepository,
    PreviewApplicationRunner,
    coordinate_question_preview,
)
from .preview_use_case import (
    PreviewCoordinator,
    PreviewUseCaseError,
    PreviewUseCaseFailureCode,
    QuestionContextResolver,
    QuestionPreviewUseCase,
    TenantBoundEditorPrincipal,
    TenantEditorActorAuthorizer,
    authorize_tenant_editor_principal,
)
from .question_context import ResolvedQuestionContext, resolve_question_context
from .repository import EditorRequestRepository
from .schemas import (
    EditorAssistantErrorResponse,
    EditorAssistantPreviewRequest,
    EditorAssistantPreviewResponse,
)
from .service import EditorRequestService

router = APIRouter()
QuestionPreviewProviderResolver = Callable[[], Awaitable[ResilientLLMClient]]

_ACCESS_UNAVAILABLE = "Editor access is unavailable."
_ERROR_RESPONSES: dict[PreviewUseCaseFailureCode, tuple[int, str]] = {
    PreviewUseCaseFailureCode.AUTHORIZATION_FAILED: (
        status.HTTP_403_FORBIDDEN,
        _ACCESS_UNAVAILABLE,
    ),
    PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE: (
        status.HTTP_404_NOT_FOUND,
        "Question context is unavailable.",
    ),
    PreviewUseCaseFailureCode.REQUIRES_NEW_DRAFT_REVISION: (
        status.HTTP_409_CONFLICT,
        "A new draft revision is required.",
    ),
    PreviewUseCaseFailureCode.IDEMPOTENCY_CONFLICT: (
        status.HTTP_409_CONFLICT,
        "Editor request idempotency conflict.",
    ),
    PreviewUseCaseFailureCode.SOURCE_EVIDENCE_UNAVAILABLE: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Verified source evidence is unavailable.",
    ),
    PreviewUseCaseFailureCode.NOT_APPLICABLE: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Question type is not supported.",
    ),
    PreviewUseCaseFailureCode.MALFORMED_QUESTION: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Question structure is invalid.",
    ),
    PreviewUseCaseFailureCode.UNSUPPORTED_INTENT: (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Editor intent is not supported.",
    ),
    PreviewUseCaseFailureCode.INTERNAL_ERROR: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Preview preparation failed.",
    ),
}


def _principal_from_current_user(user: User) -> TenantBoundEditorPrincipal:
    """Project only server-authenticated authority into the use-case principal."""

    if getattr(user, "is_impersonating", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_ACCESS_UNAVAILABLE,
        )
    tenant_id = getattr(user, "tenant_id", None)
    actor_user_id = getattr(user, "id", None)
    effective_role = getattr(user, "role", None)
    if (
        not isinstance(tenant_id, UUID)
        or not isinstance(actor_user_id, UUID)
        or not isinstance(effective_role, str)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_ACCESS_UNAVAILABLE,
        )
    return TenantBoundEditorPrincipal(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        effective_role=effective_role,
    )


class _ProviderQuestionPreviewAdapter:
    def __init__(self, llm: ResilientLLMClient) -> None:
        self._llm = llm

    async def __call__(
        self,
        context: QuestionPreviewContext,
    ) -> QuestionPreviewOutcome:
        return await preview_question_with_validation(
            context,
            self._llm,
            context.command.base_snapshot,
        )


def _application_runner(llm: ResilientLLMClient) -> PreviewApplicationRunner:
    adapter: QuestionPreviewAdapter = _ProviderQuestionPreviewAdapter(llm)

    async def run_preview(
        context: ResolvedQuestionContext,
        request: EditorAssistantPreviewRequest,
        identity_factory: PreviewIdentityFactory,
    ) -> EditorAssistantPreviewResponse:
        return await create_question_preview_response(
            context,
            request,
            adapter,
            identity_factory,
        )

    return run_preview


async def _resolve_question_preview_provider() -> ResilientLLMClient:
    """Resolve the provider-key-aware chain only at authorized execution time."""

    return await ResilientLLMClient.from_settings_async(
        temperature=0.2,
        max_tokens=4_096,
    )


def get_question_preview_provider_resolver() -> QuestionPreviewProviderResolver:
    return _resolve_question_preview_provider


def get_question_preview_application_runner(
    provider_resolver: Annotated[
        QuestionPreviewProviderResolver,
        Depends(get_question_preview_provider_resolver),
    ],
) -> PreviewApplicationRunner:
    """Build a lazy runner; provider keys and clients resolve on first execution."""

    async def run_preview(
        context: ResolvedQuestionContext,
        request: EditorAssistantPreviewRequest,
        identity_factory: PreviewIdentityFactory,
    ) -> EditorAssistantPreviewResponse:
        llm = await provider_resolver()
        return await _application_runner(llm)(context, request, identity_factory)

    return run_preview


def get_tenant_editor_actor_authorizer() -> TenantEditorActorAuthorizer:
    return authorize_tenant_editor_principal


async def get_tenant_editor_principal(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TenantBoundEditorPrincipal:
    """Project active server authority and reject unsupported platform contexts."""

    return _principal_from_current_user(current_user)


def get_editor_request_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EditorRequestService:
    return EditorRequestService(db)


def get_editor_preview_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AIEditorRequestPreviewRepository:
    return EditorRequestRepository(db)


def get_question_context_resolver() -> QuestionContextResolver:
    return resolve_question_context


def get_question_preview_coordinator() -> PreviewCoordinator:
    return coordinate_question_preview


def get_question_preview_use_case(
    db: Annotated[AsyncSession, Depends(get_db)],
    application_runner: Annotated[
        PreviewApplicationRunner,
        Depends(get_question_preview_application_runner),
    ],
    request_service: Annotated[
        EditorRequestService,
        Depends(get_editor_request_service),
    ],
    preview_repository: Annotated[
        AIEditorRequestPreviewRepository,
        Depends(get_editor_preview_repository),
    ],
    actor_authorizer: Annotated[
        TenantEditorActorAuthorizer,
        Depends(get_tenant_editor_actor_authorizer),
    ],
    context_resolver: Annotated[
        QuestionContextResolver,
        Depends(get_question_context_resolver),
    ],
    coordinator: Annotated[
        PreviewCoordinator,
        Depends(get_question_preview_coordinator),
    ],
) -> QuestionPreviewUseCase:
    """Compose the production use case from the request session and accepted seams."""

    return QuestionPreviewUseCase(
        db,
        preview_repository=preview_repository,
        application_runner=application_runner,
        request_service=request_service,
        actor_authorizer=actor_authorizer,
        context_resolver=context_resolver,
        coordinator=coordinator,
    )


def _http_error(error: PreviewUseCaseError) -> HTTPException:
    status_code, detail = _ERROR_RESPONSES[error.code]
    return HTTPException(status_code=status_code, detail=detail)


@router.post(
    "/{quiz_id}/questions/{question_id}/assistant/preview",
    response_model=EditorAssistantPreviewResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": EditorAssistantErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": EditorAssistantErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": EditorAssistantErrorResponse},
        status.HTTP_409_CONFLICT: {"model": EditorAssistantErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Request validation or bounded editor failure.",
            "content": {
                "application/json": {
                    "schema": {
                        "anyOf": [
                            {
                                "$ref": (
                                    "#/components/schemas/"
                                    "EditorAssistantErrorResponse"
                                )
                            },
                            {
                                "type": "object",
                                "required": ["detail"],
                                "properties": {
                                    "detail": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    }
                                },
                            },
                        ]
                    }
                }
            },
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": EditorAssistantErrorResponse
        },
    },
)
async def preview_question_with_assistant(
    quiz_id: UUID,
    question_id: UUID,
    request: EditorAssistantPreviewRequest,
    principal: Annotated[
        TenantBoundEditorPrincipal,
        Depends(get_tenant_editor_principal),
    ],
    use_case: Annotated[
        QuestionPreviewUseCase,
        Depends(get_question_preview_use_case),
    ],
) -> EditorAssistantPreviewResponse:
    try:
        return await use_case.execute(
            principal=principal,
            quiz_id=quiz_id,
            question_id=question_id,
            request=request,
        )
    except PreviewUseCaseError as error:
        raise _http_error(error) from None


__all__ = [
    "get_editor_preview_repository",
    "get_editor_request_service",
    "get_question_context_resolver",
    "get_question_preview_application_runner",
    "get_question_preview_coordinator",
    "get_question_preview_provider_resolver",
    "get_question_preview_use_case",
    "get_tenant_editor_actor_authorizer",
    "get_tenant_editor_principal",
    "router",
]
