from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.auth import _ActiveRoleUser, _ImpersonatedUser, get_current_active_user
from app.models.users import User
from app.modules.editor_assistant.preview_use_case import (
    PreviewUseCaseError,
    PreviewUseCaseFailureCode,
    TenantBoundEditorPrincipal,
)
from app.modules.editor_assistant.router import (
    get_question_preview_application_runner,
    get_question_preview_use_case,
)
from app.modules.editor_assistant.schemas import (
    EditorApplicability,
    EditorAssistantErrorResponse,
    EditorAssistantPreviewResponse,
    EditorAssistantSourceProjection,
    EditorPreviewState,
)
from app.modules.quizzes.router import router as quizzes_router

QUIZ_ID = UUID("11111111-1111-4111-8111-111111111111")
QUESTION_ID = UUID("22222222-2222-4222-8222-222222222222")
REQUEST_KEY = UUID("33333333-3333-4333-8333-333333333333")
PREVIEW_KEY = UUID("44444444-4444-4444-8444-444444444444")
ROUTE = f"/api/v1/quizzes/{QUIZ_ID}/questions/{QUESTION_ID}/assistant/preview"


def _request_payload() -> dict[str, str]:
    return {
        "request_key": str(REQUEST_KEY),
        "preview_key": str(PREVIEW_KEY),
        "intent": "add_context",
        "instruction": "Add one source-grounded detail.",
    }


def _response() -> EditorAssistantPreviewResponse:
    return EditorAssistantPreviewResponse(
        request_id=REQUEST_KEY,
        preview_id=PREVIEW_KEY,
        state=EditorPreviewState.PENDING,
        applicability=EditorApplicability.NOT_APPLICABLE,
        base_snapshot_token="a" * 64,
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
    )


def _user(*, role: str, tenant_id: UUID | None = None) -> User:
    return User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=None,
        first_name="Synthetic",
        last_name="Editor",
        role=role,
        is_active=True,
    )


@dataclass
class StubUseCase:
    response: EditorAssistantPreviewResponse | None = None
    error: PreviewUseCaseError | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, **kwargs) -> EditorAssistantPreviewResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _client(current_user: object, use_case: StubUseCase) -> TestClient:
    app = FastAPI()
    app.include_router(quizzes_router, prefix="/api/v1")

    async def override_current_user():
        return current_user

    def override_use_case():
        return use_case

    app.dependency_overrides[get_current_active_user] = override_current_user
    app.dependency_overrides[get_question_preview_use_case] = override_use_case
    return TestClient(app)


@pytest.mark.parametrize(
    "current_user",
    (
        _user(role="methodologist", tenant_id=uuid4()),
        _user(role="superadmin", tenant_id=uuid4()),
    ),
)
def test_tenant_editor_preview_returns_canonical_dto(current_user: User) -> None:
    use_case = StubUseCase(response=_response())

    with _client(current_user, use_case) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == 200
    assert response.json() == _response().model_dump(mode="json")
    assert len(use_case.calls) == 1
    call = use_case.calls[0]
    assert call["principal"] == TenantBoundEditorPrincipal(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        effective_role=current_user.role,
    )
    assert call["quiz_id"] == QUIZ_ID
    assert call["question_id"] == QUESTION_ID


def test_user_role_derived_effective_methodologist_is_preserved() -> None:
    base_user = _user(role="student", tenant_id=uuid4())
    current_user = _ActiveRoleUser(base_user, "methodologist")
    use_case = StubUseCase(response=_response())

    with _client(current_user, use_case) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == 200
    assert use_case.calls[0]["principal"] == TenantBoundEditorPrincipal(
        tenant_id=base_user.tenant_id,
        actor_user_id=base_user.id,
        effective_role="methodologist",
    )


@pytest.mark.parametrize("role", ("admin", "student"))
def test_tenant_admin_and_student_are_denied_by_use_case(role: str) -> None:
    current_user = _user(role=role, tenant_id=uuid4())
    use_case = StubUseCase(
        error=PreviewUseCaseError(PreviewUseCaseFailureCode.AUTHORIZATION_FAILED)
    )

    with _client(current_user, use_case) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == 403
    assert response.json() == {"detail": "Editor access is unavailable."}
    assert len(use_case.calls) == 1


def test_tenantless_platform_superadmin_is_denied_before_use_case() -> None:
    current_user = _user(role="superadmin", tenant_id=None)
    use_case = StubUseCase(response=_response())

    with _client(current_user, use_case) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == 403
    assert response.json() == {"detail": "Editor access is unavailable."}
    assert use_case.calls == []


def test_realistic_platform_impersonation_is_denied_before_use_case() -> None:
    platform_user = _user(role="superadmin", tenant_id=None)
    current_user = _ImpersonatedUser(
        real_user=platform_user,
        tenant_id=uuid4(),
        role="methodologist",
    )
    use_case = StubUseCase(response=_response())

    with _client(current_user, use_case) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == 403
    assert response.json() == {"detail": "Editor access is unavailable."}
    assert use_case.calls == []


def test_authority_cannot_be_influenced_by_query_or_resource_paths() -> None:
    current_user = _user(role="methodologist", tenant_id=uuid4())
    use_case = StubUseCase(response=_response())
    foreign_tenant = uuid4()

    with _client(current_user, use_case) as client:
        response = client.post(
            f"{ROUTE}?tenant_id={foreign_tenant}&actor_user_id={uuid4()}&effective_role=superadmin",
            json=_request_payload(),
        )

    assert response.status_code == 200
    principal = use_case.calls[0]["principal"]
    assert principal == TenantBoundEditorPrincipal(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        effective_role="methodologist",
    )


@pytest.mark.parametrize(
    "authority_field,authority_value",
    (
        ("tenant_id", str(uuid4())),
        ("actor_user_id", str(uuid4())),
        ("effective_role", "superadmin"),
    ),
)
def test_request_body_rejects_client_authored_authority(
    authority_field: str,
    authority_value: str,
) -> None:
    current_user = _user(role="methodologist", tenant_id=uuid4())
    use_case = StubUseCase(response=_response())

    with _client(current_user, use_case) as client:
        response = client.post(
            ROUTE,
            json={**_request_payload(), authority_field: authority_value},
        )

    assert response.status_code == 422
    assert use_case.calls == []


@pytest.mark.parametrize(
    "code,status_code,detail",
    (
        (PreviewUseCaseFailureCode.AUTHORIZATION_FAILED, 403, "Editor access is unavailable."),
        (PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE, 404, "Question context is unavailable."),
        (PreviewUseCaseFailureCode.REQUIRES_NEW_DRAFT_REVISION, 409, "A new draft revision is required."),
        (PreviewUseCaseFailureCode.IDEMPOTENCY_CONFLICT, 409, "Editor request idempotency conflict."),
        (PreviewUseCaseFailureCode.SOURCE_EVIDENCE_UNAVAILABLE, 422, "Verified source evidence is unavailable."),
        (PreviewUseCaseFailureCode.NOT_APPLICABLE, 422, "Question type is not supported."),
        (PreviewUseCaseFailureCode.MALFORMED_QUESTION, 422, "Question structure is invalid."),
        (PreviewUseCaseFailureCode.UNSUPPORTED_INTENT, 422, "Editor intent is not supported."),
        (PreviewUseCaseFailureCode.INTERNAL_ERROR, 500, "Preview preparation failed."),
    ),
)
def test_typed_use_case_error_has_exact_bounded_http_mapping(
    code: PreviewUseCaseFailureCode,
    status_code: int,
    detail: str,
) -> None:
    current_user = _user(role="methodologist", tenant_id=uuid4())
    use_case = StubUseCase(error=PreviewUseCaseError(code))

    with _client(current_user, use_case) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}


def test_invalid_path_uuid_uses_fastapi_validation() -> None:
    current_user = _user(role="methodologist", tenant_id=uuid4())
    use_case = StubUseCase(response=_response())

    with _client(current_user, use_case) as client:
        response = client.post(
            f"/api/v1/quizzes/not-a-uuid/questions/{QUESTION_ID}/assistant/preview",
            json=_request_payload(),
        )

    assert response.status_code == 422
    assert use_case.calls == []


def test_openapi_contract_publishes_only_resource_and_preview_models() -> None:
    app = FastAPI()
    app.include_router(quizzes_router, prefix="/api/v1")
    schema = app.openapi()
    path = "/api/v1/quizzes/{quiz_id}/questions/{question_id}/assistant/preview"

    assert set(schema["paths"][path]) == {"post"}
    operation = schema["paths"][path]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EditorAssistantPreviewRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EditorAssistantPreviewResponse"
    }
    assert set(operation["responses"]) == {"200", "401", "403", "404", "409", "422", "500"}
    assert operation["security"] == [{"HTTPBearer": []}]
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    error_properties = schema["components"]["schemas"][
        "EditorAssistantErrorResponse"
    ]["properties"]
    assert set(error_properties) == {"detail"}
    for status_code in ("401", "403", "404", "409", "500"):
        assert operation["responses"][status_code]["content"][
            "application/json"
        ]["schema"] == {
            "$ref": "#/components/schemas/EditorAssistantErrorResponse"
        }
    assert operation["responses"]["422"]["content"]["application/json"][
        "schema"
    ]["anyOf"] == [
        {"$ref": "#/components/schemas/EditorAssistantErrorResponse"},
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
    request_properties = schema["components"]["schemas"][
        "EditorAssistantPreviewRequest"
    ]["properties"]
    assert set(request_properties) == {
        "request_key",
        "preview_key",
        "intent",
        "instruction",
    }
    assert not {
        "tenant_id",
        "actor_id",
        "actor_user_id",
        "role",
        "effective_role",
    } & set(request_properties)


def test_expired_or_blocked_tenant_stops_before_use_case_construction() -> None:
    app = FastAPI()
    app.include_router(quizzes_router, prefix="/api/v1")
    constructions = 0

    async def blocked_tenant():
        raise HTTPException(status_code=403, detail="Tenant access is unavailable.")

    def forbidden_construction():
        nonlocal constructions
        constructions += 1
        raise AssertionError("use case must not be constructed")

    app.dependency_overrides[get_current_active_user] = blocked_tenant
    app.dependency_overrides[get_question_preview_use_case] = forbidden_construction

    with TestClient(app) as client:
        response = client.post(ROUTE, json=_request_payload())

    assert response.status_code == 403
    assert constructions == 0


@pytest.mark.asyncio
async def test_provider_resolution_is_lazy_and_occurs_once_per_runner_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = 0
    expected = _response()

    async def resolve_provider():
        nonlocal resolutions
        resolutions += 1
        return object()

    async def create_response(context, request, adapter, identity_factory):
        del context, request, adapter, identity_factory
        return expected

    monkeypatch.setattr(
        "app.modules.editor_assistant.router.create_question_preview_response",
        create_response,
    )
    runner = get_question_preview_application_runner(resolve_provider)
    assert resolutions == 0

    response = await runner(object(), object(), object())

    assert response is expected
    assert resolutions == 1


def test_public_error_dto_rejects_internal_fields() -> None:
    assert EditorAssistantErrorResponse(detail="Bounded failure.").model_dump() == {
        "detail": "Bounded failure."
    }
    with pytest.raises(ValidationError):
        EditorAssistantErrorResponse(
            detail="Bounded failure.",
            tenant_id=str(uuid4()),
        )
