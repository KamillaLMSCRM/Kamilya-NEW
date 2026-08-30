from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.models.user_roles import UserRole
from app.models.users import User
from app.modules.editor_assistant.patch_contract import PatchIdempotencyCollisionError
from app.modules.editor_assistant.preview_coordinator import coordinate_question_preview
from app.modules.editor_assistant.preview_use_case import (
    ActorAuthorizationError,
    PreviewUseCaseError,
    PreviewUseCaseFailureCode,
    QuestionPreviewUseCase,
    TenantBoundEditorPrincipal,
    authorize_tenant_editor_principal,
)
from app.modules.editor_assistant.question_context import (
    AuthorizedEditorRole,
    QuestionChoiceContext,
    QuestionContextError,
    QuestionContextFailureCode,
    QuestionSourceFact,
    QuestionSourceReference,
    ResolvedQuestionContext,
)
from app.modules.editor_assistant.repository import EditorPreviewRecord
from app.modules.editor_assistant.router import (
    get_editor_preview_repository,
    get_editor_request_service,
    get_question_context_resolver,
    get_question_preview_application_runner,
    get_question_preview_coordinator,
    get_tenant_editor_actor_authorizer,
)
from app.modules.editor_assistant.schemas import (
    EditorApplicability,
    EditorAssistantFailure,
    EditorAssistantFailureCode,
    EditorAssistantPatchOperation,
    EditorAssistantPreviewRequest,
    EditorAssistantPreviewResponse,
    EditorAssistantProvenance,
    EditorAssistantSourceProjection,
    EditorAssistantSourceReference,
    EditorAssistantValidationReport,
    EditorIntent,
    EditorPatchPath,
    EditorPreviewState,
    EditorValidationStatus,
    editor_assistant_failure_contract,
)
from app.modules.editor_assistant.service import EditorRequestService
from app.modules.quizzes.router import router as quizzes_router


@dataclass(frozen=True)
class ActorRecord:
    tenant_id: UUID | None
    role: str
    is_active: bool = True
    assigned_roles: frozenset[str] = frozenset()


class ContractActorAuthorizer:
    def __init__(self, users: dict[UUID, ActorRecord], order: list[str]) -> None:
        self.users = users
        self.order = order
        self.calls = 0

    async def __call__(self, db, principal):
        del db
        self.calls += 1
        self.order.append("authorize")
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
        record = self.users.get(principal.actor_user_id)
        if (
            record is None
            or record.tenant_id != principal.tenant_id
            or not record.is_active
            or (
                record.role != role.value
                and role.value not in record.assigned_roles
            )
            or role
            not in {
                AuthorizedEditorRole.METHODOLOGIST,
                AuthorizedEditorRole.SUPERADMIN,
            }
        ):
            raise ActorAuthorizationError
        return TenantBoundEditorPrincipal(
            principal.tenant_id, principal.actor_user_id, role
        )


class InMemoryRequestRepository:
    """Exact canonical service seam, including durable request fingerprints."""

    def __init__(self, actors: set[tuple[UUID, UUID]], order: list[str]) -> None:
        self.actors = actors
        self.order = order
        self.requests: dict[UUID, object] = {}
        self.events: list[object] = []

    async def actor_exists_for_tenant(self, actor_id, tenant_id):
        return (tenant_id, actor_id) in self.actors

    async def claim_request(self, request):
        self.order.append("persist")
        existing = self.requests.get(request.id)
        if existing is not None:
            return existing, False
        self.requests[request.id] = request
        return request, True

    async def next_event_sequence(self, request_id, tenant_id):
        del request_id, tenant_id
        return len(self.events) + 1

    async def _append_event(self, event):
        self.events.append(event)
        return event


class ExactContextResolver:
    def __init__(self, context: ResolvedQuestionContext, order: list[str]) -> None:
        self.context = context
        self.order = order
        self.error: QuestionContextError | None = None
        self.calls = 0

    async def __call__(
        self,
        db,
        *,
        tenant_id,
        authorized_role,
        quiz_id,
        question_id,
    ):
        del db, tenant_id, authorized_role, quiz_id, question_id
        self.calls += 1
        self.order.append("context")
        if self.error is not None:
            raise self.error
        return self.context


class InMemoryPreviewRepository:
    """Accepted preview seam with strict live claim-token ownership."""

    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.rows: dict[tuple[UUID, str], EditorPreviewRecord] = {}
        self.live_tokens: dict[tuple[UUID, str], str] = {}

    async def claim_preview(
        self, *, tenant_id, request_id, preview_key, payload_fingerprint
    ):
        self.order.append("preview")
        key = (tenant_id, preview_key)
        existing = self.rows.get(key)
        if existing is not None:
            if (
                existing.request_id != request_id
                or existing.payload_fingerprint != payload_fingerprint
            ):
                raise PatchIdempotencyCollisionError("bounded collision")
            return existing
        now = datetime.now(UTC)
        token = f"claim-{uuid4().hex}"
        record = EditorPreviewRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            request_id=request_id,
            preview_key=preview_key,
            payload_fingerprint=payload_fingerprint,
            state="pending",
            owns_claim=True,
            claim_token=token,
            completed_result=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            failed_at=None,
        )
        self.rows[key] = record
        self.live_tokens[key] = token
        return record

    async def read_preview(self, *, tenant_id, request_id, preview_key):
        record = self.rows.get((tenant_id, preview_key))
        if record is None or record.request_id != request_id:
            return None
        return record

    def _owned(self, key, request_id, payload_fingerprint, claim_token):
        record = self.rows.get(key)
        return (
            record
            if record is not None
            and record.state == "pending"
            and record.owns_claim
            and record.request_id == request_id
            and record.payload_fingerprint == payload_fingerprint
            and self.live_tokens.get(key) == claim_token
            else None
        )

    async def complete_preview(
        self,
        *,
        tenant_id,
        request_id,
        preview_key,
        payload_fingerprint,
        claim_token,
        completed_result,
    ):
        key = (tenant_id, preview_key)
        record = self._owned(key, request_id, payload_fingerprint, claim_token)
        if record is None:
            return None
        updated = replace(
            record,
            state="completed",
            owns_claim=False,
            claim_token=None,
            completed_result=MappingProxyType(dict(completed_result)),
            completed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.rows[key] = updated
        self.live_tokens.pop(key, None)
        return updated

    async def fail_preview(
        self,
        *,
        tenant_id,
        request_id,
        preview_key,
        payload_fingerprint,
        claim_token,
        failure_code,
    ):
        key = (tenant_id, preview_key)
        record = self._owned(key, request_id, payload_fingerprint, claim_token)
        if record is None:
            return None
        updated = replace(
            record,
            state="failed",
            owns_claim=False,
            claim_token=None,
            failure_code=failure_code,
            failed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.rows[key] = updated
        self.live_tokens.pop(key, None)
        return updated


class CountedApplicationRunner:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls = 0

    async def __call__(self, context, request, identity_factory):
        del context
        self.calls += 1
        self.order.append("ai")
        request_id, preview_id = identity_factory(request)
        return _failed_response(request_id, preview_id)


class EchoCoordinator:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = 0

    async def __call__(
        self,
        *,
        tenant_id,
        editor_request_id,
        context,
        request,
        repository,
        application_runner,
    ):
        del (
            tenant_id,
            editor_request_id,
            context,
            request,
            repository,
            application_runner,
        )
        self.calls += 1
        return self.response


def _context(**overrides: object) -> ResolvedQuestionContext:
    tenant_id = overrides.pop("tenant_id", uuid4())
    quiz_id = overrides.pop("quiz_id", uuid4())
    question_id = overrides.pop("question_id", uuid4())
    source_id = uuid4()
    correct_id = uuid4()
    values = {
        "tenant_id": tenant_id,
        "course_id": uuid4(),
        "module_id": uuid4(),
        "lesson_id": uuid4(),
        "quiz_id": quiz_id,
        "question_id": question_id,
        "question_type": "MCQ",
        "question_text": "What is approved?",
        "choices": (
            QuestionChoiceContext(correct_id, "Approved", True, 0),
            QuestionChoiceContext(uuid4(), "Rejected", False, 1),
        ),
        "correct_choice_id": correct_id,
        "explanation": "Use the approved action.",
        "locale": "ru",
        "source_references": (
            QuestionSourceReference(source_id, "Source", "Section 1", "a" * 64),
        ),
        "source_facts": (
            QuestionSourceFact(
                "fact-1",
                source_id,
                "RAW SOURCE FACT MUST NOT BE PERSISTED",
                "Section 1",
                "a" * 64,
            ),
        ),
        "snapshot_fingerprint": "b" * 64,
    }
    values.update(overrides)
    return ResolvedQuestionContext(**values)


def _request(**overrides: object) -> EditorAssistantPreviewRequest:
    values = {
        "request_key": uuid4(),
        "preview_key": uuid4(),
        "intent": EditorIntent.REWRITE_WORDING,
        "instruction": "Rewrite this question clearly.",
    }
    values.update(overrides)
    return EditorAssistantPreviewRequest(**values)


def _failed_response(request_id: UUID, preview_id: UUID):
    message, applicability = editor_assistant_failure_contract(
        EditorAssistantFailureCode.INTERNAL_ERROR
    )
    return EditorAssistantPreviewResponse(
        request_id=request_id,
        preview_id=preview_id,
        state=EditorPreviewState.FAILED,
        applicability=applicability,
        base_snapshot_token="s" * 64,
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
        failure=EditorAssistantFailure(
            error_code=EditorAssistantFailureCode.INTERNAL_ERROR,
            message=message,
        ),
    )


def _completed_response(request_id: UUID, preview_id: UUID):
    return EditorAssistantPreviewResponse(
        request_id=request_id,
        preview_id=preview_id,
        state=EditorPreviewState.COMPLETED,
        applicability=EditorApplicability.APPLICABLE,
        base_snapshot_token="s" * 64,
        operations=(
            EditorAssistantPatchOperation(
                operation="replace",
                field_path=EditorPatchPath.TEXT,
                before_value="Before",
                after_value="After",
            ),
        ),
        validation=EditorAssistantValidationReport(
            status=EditorValidationStatus.PASS,
            issues=(),
        ),
        source=EditorAssistantSourceProjection(
            source_reference_count=1,
            references=(
                EditorAssistantSourceReference(
                    source_id="source-1",
                    document_title="Source",
                    locator="Section 1",
                ),
            ),
        ),
        provenance=EditorAssistantProvenance(
            prompt_version="prompt-v1",
            generator_version="generator-v1",
            validator_version="validator-v1",
        ),
    )


@dataclass
class Environment:
    use_case: QuestionPreviewUseCase
    principal: TenantBoundEditorPrincipal
    context: ResolvedQuestionContext
    authorizer: ContractActorAuthorizer
    resolver: ExactContextResolver
    request_repository: InMemoryRequestRepository
    preview_repository: InMemoryPreviewRepository
    runner: CountedApplicationRunner
    order: list[str]

    async def execute(self, *, principal=None, context=None, request=None):
        selected_context = context or self.resolver.context
        self.resolver.context = selected_context
        return await self.use_case.execute(
            principal=principal or self.principal,
            quiz_id=selected_context.quiz_id,
            question_id=selected_context.question_id,
            request=request or _request(),
        )


def _environment(*, role: AuthorizedEditorRole | str = "methodologist") -> Environment:
    order: list[str] = []
    context = _context()
    actor_id = uuid4()
    principal = TenantBoundEditorPrincipal(context.tenant_id, actor_id, role)
    role_value = AuthorizedEditorRole(role).value
    authorizer = ContractActorAuthorizer(
        {actor_id: ActorRecord(context.tenant_id, role_value)}, order
    )
    request_repository = InMemoryRequestRepository(
        {(context.tenant_id, actor_id)}, order
    )
    service = object.__new__(EditorRequestService)
    service._repo = request_repository
    resolver = ExactContextResolver(context, order)
    preview_repository = InMemoryPreviewRepository(order)
    runner = CountedApplicationRunner(order)
    use_case = QuestionPreviewUseCase(
        object(),
        preview_repository=preview_repository,
        application_runner=runner,
        request_service=service,
        actor_authorizer=authorizer,
        context_resolver=resolver,
        coordinator=coordinate_question_preview,
    )
    return Environment(
        use_case,
        principal,
        context,
        authorizer,
        resolver,
        request_repository,
        preview_repository,
        runner,
        order,
    )


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "foreign_tenant",
        "inactive",
        "admin",
        "student",
        "platform_superadmin",
        "platform_impersonation",
        "uppercase_role",
    ],
)
async def test_authorization_failures_are_identical_and_have_zero_side_effects(case):
    env = _environment()
    tenant_id = env.context.tenant_id
    actor_id = env.principal.actor_user_id
    principal: object = env.principal
    if case == "unknown":
        principal = TenantBoundEditorPrincipal(tenant_id, uuid4(), "methodologist")
    elif case == "foreign_tenant":
        env.authorizer.users[actor_id] = ActorRecord(uuid4(), "methodologist")
    elif case == "inactive":
        env.authorizer.users[actor_id] = ActorRecord(
            tenant_id, "methodologist", is_active=False
        )
    elif case in {"admin", "student"}:
        env.authorizer.users[actor_id] = ActorRecord(tenant_id, case)
        principal = TenantBoundEditorPrincipal(tenant_id, actor_id, case)
    elif case == "platform_superadmin":
        env.authorizer.users[actor_id] = ActorRecord(None, "superadmin")
        principal = TenantBoundEditorPrincipal(None, actor_id, "superadmin")
    elif case == "platform_impersonation":
        env.authorizer.users[actor_id] = ActorRecord(None, "superadmin")
        principal = TenantBoundEditorPrincipal(tenant_id, actor_id, "superadmin")
    elif case == "uppercase_role":
        principal = TenantBoundEditorPrincipal(tenant_id, actor_id, "METHODOLOGIST")

    with pytest.raises(PreviewUseCaseError) as error:
        await env.execute(principal=principal)

    assert error.value.code is PreviewUseCaseFailureCode.AUTHORIZATION_FAILED
    assert str(error.value) == "Editor access is unavailable."
    assert env.resolver.calls == 0
    assert env.request_repository.requests == {}
    assert env.request_repository.events == []
    assert env.preview_repository.rows == {}
    assert env.runner.calls == 0
    assert env.order == ["authorize"]


@pytest.mark.parametrize(
    "role",
    [
        "methodologist",
        AuthorizedEditorRole.METHODOLOGIST,
        "superadmin",
        AuthorizedEditorRole.SUPERADMIN,
    ],
)
async def test_tenant_bound_allowed_roles_accept_real_strings_and_enums(role):
    env = _environment(role=role)

    response = await env.execute(request=_request())

    assert response.state is EditorPreviewState.FAILED
    assert env.runner.calls == 1
    assert env.order[:5] == ["authorize", "context", "persist", "preview", "ai"]


@pytest.mark.parametrize(
    ("context_code", "expected"),
    [
        (
            QuestionContextFailureCode.CONTEXT_UNAVAILABLE,
            PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE,
        ),
        (
            QuestionContextFailureCode.REQUIRES_NEW_DRAFT_REVISION,
            PreviewUseCaseFailureCode.REQUIRES_NEW_DRAFT_REVISION,
        ),
        (
            QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE,
            PreviewUseCaseFailureCode.SOURCE_EVIDENCE_UNAVAILABLE,
        ),
    ],
)
async def test_context_failure_follows_authorization_and_has_no_side_effects(
    context_code, expected
):
    env = _environment()
    env.resolver.error = QuestionContextError(context_code)

    with pytest.raises(PreviewUseCaseError) as error:
        await env.execute()

    assert error.value.code is expected
    assert env.order == ["authorize", "context"]
    assert env.request_repository.requests == {}
    assert env.preview_repository.rows == {}
    assert env.runner.calls == 0


async def test_context_tenant_binding_precedes_persistence():
    env = _environment()
    foreign_context = replace(env.context, tenant_id=uuid4())

    with pytest.raises(PreviewUseCaseError) as error:
        await env.execute(context=foreign_context)

    assert error.value.code is PreviewUseCaseFailureCode.CONTEXT_UNAVAILABLE
    assert env.order == ["authorize", "context"]
    assert env.request_repository.requests == {}


async def test_exact_replay_has_one_request_event_preview_and_ai_call():
    env = _environment()
    request = _request()

    first = await env.execute(request=request)
    second = await env.execute(request=request)

    assert second == first
    assert len(env.request_repository.requests) == 1
    assert len(env.request_repository.events) == 1
    assert len(env.preview_repository.rows) == 1
    assert env.runner.calls == 1


@pytest.mark.parametrize(
    "change", ["instruction", "intent", "actor", "target", "snapshot"]
)
async def test_request_fingerprint_changes_conflict_before_coordinator(change):
    env = _environment()
    request = _request()
    await env.execute(request=request)
    preview_count = len(env.preview_repository.rows)
    ai_count = env.runner.calls
    next_request = request
    next_principal = env.principal
    next_context = env.context
    if change == "instruction":
        next_request = request.model_copy(update={"instruction": "PRIVATE CHANGED TEXT"})
    elif change == "intent":
        next_request = request.model_copy(update={"intent": EditorIntent.SIMPLIFY_LANGUAGE})
    elif change == "actor":
        actor_id = uuid4()
        env.authorizer.users[actor_id] = ActorRecord(
            env.context.tenant_id, "methodologist"
        )
        env.request_repository.actors.add((env.context.tenant_id, actor_id))
        next_principal = TenantBoundEditorPrincipal(
            env.context.tenant_id, actor_id, "methodologist"
        )
    elif change == "target":
        next_context = replace(env.context, question_id=uuid4())
    elif change == "snapshot":
        next_context = replace(env.context, snapshot_fingerprint="c" * 64)

    with pytest.raises(PreviewUseCaseError) as error:
        await env.execute(
            principal=next_principal,
            context=next_context,
            request=next_request,
        )

    assert error.value.code is PreviewUseCaseFailureCode.IDEMPOTENCY_CONFLICT
    assert str(error.value) == "Editor request idempotency conflict."
    assert "PRIVATE CHANGED TEXT" not in str(error.value)
    assert len(env.request_repository.requests) == 1
    assert len(env.request_repository.events) == 1
    assert len(env.preview_repository.rows) == preview_count
    assert env.runner.calls == ai_count


async def test_changing_only_preview_key_creates_preview_not_request():
    env = _environment()
    request = _request()
    await env.execute(request=request)

    await env.execute(request=request.model_copy(update={"preview_key": uuid4()}))

    assert len(env.request_repository.requests) == 1
    assert len(env.request_repository.events) == 1
    assert len(env.preview_repository.rows) == 2
    assert env.runner.calls == 2


@pytest.mark.parametrize("terminal", ["complete", "fail"])
async def test_foreign_and_stale_claim_tokens_cannot_transition_preview(terminal):
    repository = InMemoryPreviewRepository([])
    tenant_id, request_id = uuid4(), uuid4()
    preview_key, fingerprint = str(uuid4()), "a" * 64
    claim = await repository.claim_preview(
        tenant_id=tenant_id,
        request_id=request_id,
        preview_key=preview_key,
        payload_fingerprint=fingerprint,
    )
    method = (
        repository.complete_preview
        if terminal == "complete"
        else repository.fail_preview
    )
    common = {
        "tenant_id": tenant_id,
        "request_id": request_id,
        "preview_key": preview_key,
        "payload_fingerprint": fingerprint,
    }
    extra = (
        {"completed_result": {}}
        if terminal == "complete"
        else {"failure_code": "internal_error"}
    )

    assert await method(claim_token="foreign", **common, **extra) is None
    assert repository.rows[(tenant_id, preview_key)].state == "pending"
    assert await method(claim_token=claim.claim_token, **common, **extra) is not None
    assert await method(claim_token=claim.claim_token, **common, **extra) is None


async def test_persistence_has_no_source_provider_and_one_instruction():
    env = _environment()
    request = _request(instruction="ONE CANONICAL INSTRUCTION")

    await env.execute(request=request)

    durable = next(iter(env.request_repository.requests.values()))
    assert durable.instruction_text == request.instruction
    assert durable.operation_constraints == {}
    assert durable.source_type_summary is None
    assert durable.model_id is None
    projection = repr(durable.__dict__)
    assert projection.count(request.instruction) == 1
    assert env.context.source_facts[0].text not in projection
    assert "provider_response" not in projection
    assert "exception_text" not in projection


@pytest.mark.parametrize("completed", [True, False])
async def test_coordinator_response_is_returned_unchanged(completed):
    env = _environment()
    expected = (
        _completed_response(uuid4(), uuid4())
        if completed
        else _failed_response(uuid4(), uuid4())
    )
    coordinator = EchoCoordinator(expected)
    env.use_case._coordinator = coordinator

    response = await env.execute(request=_request())

    assert response is expected
    assert coordinator.calls == 1


class ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class AuthorizerSession:
    def __init__(
        self,
        users: list[User],
        role_assignments: list[UserRole] | None = None,
    ) -> None:
        self.users = {user.id: user for user in users}
        self.role_assignments = {
            (assignment.user_id, assignment.tenant_id, assignment.role): assignment.id
            for assignment in role_assignments or []
        }
        self.statements: list[object] = []
        self.query_entities: list[type] = []

    async def execute(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        self.query_entities.append(entity)
        params = statement.compile().params
        if entity is User:
            actor_id = _statement_param(params, "id_")
            tenant_id = _statement_param(params, "tenant_id_")
            required_status = _statement_param(params, "status_")
            user = self.users.get(actor_id)
            if (
                user is None
                or user.tenant_id != tenant_id
                or not user.is_active
                or user.status != required_status
            ):
                return ScalarResult(None)
            return ScalarResult(user)
        if entity is UserRole:
            key = (
                _statement_param(params, "user_id_"),
                _statement_param(params, "tenant_id_"),
                _statement_param(params, "role_"),
            )
            return ScalarResult(self.role_assignments.get(key))
        raise AssertionError(f"Unexpected authorizer query entity: {entity}")


def _statement_param(params: dict[str, object], prefix: str):
    return next(value for name, value in params.items() if name.startswith(prefix))


def _user(
    *,
    actor_id: UUID,
    tenant_id: UUID | None,
    role: str,
    is_active: bool = True,
    status: str = "active",
) -> User:
    return User(
        id=actor_id,
        tenant_id=tenant_id,
        role=role,
        is_active=is_active,
        status=status,
    )


async def test_public_authorizer_accepts_primary_methodologist_without_role_query():
    tenant_id, actor_id = uuid4(), uuid4()
    session = AuthorizerSession(
        [_user(actor_id=actor_id, tenant_id=tenant_id, role="methodologist")]
    )
    principal = TenantBoundEditorPrincipal(
        tenant_id, actor_id, AuthorizedEditorRole.METHODOLOGIST
    )

    authorized = await authorize_tenant_editor_principal(session, principal)

    assert authorized == principal
    assert authorized.effective_role is AuthorizedEditorRole.METHODOLOGIST
    assert session.query_entities == [User]
    user_query = session.statements[0]
    assert "users.is_active IS true" in str(user_query)
    assert "users.status =" in str(user_query)
    assert _statement_param(user_query.compile().params, "status_") == "active"


async def test_public_authorizer_accepts_exact_assigned_methodologist_role():
    tenant_id, actor_id = uuid4(), uuid4()
    assignment = UserRole(
        id=uuid4(),
        user_id=actor_id,
        tenant_id=tenant_id,
        role="methodologist",
    )
    session = AuthorizerSession(
        [_user(actor_id=actor_id, tenant_id=tenant_id, role="student")],
        [assignment],
    )
    principal = TenantBoundEditorPrincipal(tenant_id, actor_id, "methodologist")

    authorized = await authorize_tenant_editor_principal(session, principal)

    assert authorized.effective_role is AuthorizedEditorRole.METHODOLOGIST
    assert session.query_entities == [User, UserRole]
    role_query = str(session.statements[1])
    assert "user_roles.user_id" in role_query
    assert "user_roles.tenant_id" in role_query
    assert "user_roles.role" in role_query


@pytest.mark.parametrize("assignment_tenant", [None, "foreign"])
async def test_public_authorizer_rejects_missing_or_cross_tenant_role_assignment(
    assignment_tenant,
):
    tenant_id, actor_id = uuid4(), uuid4()
    assignments = []
    if assignment_tenant == "foreign":
        assignments.append(
            UserRole(
                id=uuid4(),
                user_id=actor_id,
                tenant_id=uuid4(),
                role="methodologist",
            )
        )
    session = AuthorizerSession(
        [_user(actor_id=actor_id, tenant_id=tenant_id, role="student")],
        assignments,
    )
    principal = TenantBoundEditorPrincipal(tenant_id, actor_id, "methodologist")

    with pytest.raises(ActorAuthorizationError):
        await authorize_tenant_editor_principal(session, principal)

    assert session.query_entities == [User, UserRole]


async def test_public_authorizer_rejects_inactive_tenant_user_before_role_query():
    tenant_id, actor_id = uuid4(), uuid4()
    session = AuthorizerSession(
        [
            _user(
                actor_id=actor_id,
                tenant_id=tenant_id,
                role="methodologist",
                is_active=False,
            )
        ]
    )
    principal = TenantBoundEditorPrincipal(tenant_id, actor_id, "methodologist")

    with pytest.raises(ActorAuthorizationError):
        await authorize_tenant_editor_principal(session, principal)

    assert session.query_entities == [User]


@pytest.mark.parametrize("account_status", ("inactive", "banned"))
async def test_public_authorizer_rejects_non_active_status_before_all_side_effects(
    account_status: str,
) -> None:
    env = _environment()
    session = AuthorizerSession(
        [
            _user(
                actor_id=env.principal.actor_user_id,
                tenant_id=env.principal.tenant_id,
                role="methodologist",
                is_active=True,
                status=account_status,
            )
        ]
    )
    env.use_case._db = session
    env.use_case._actor_authorizer = authorize_tenant_editor_principal

    with pytest.raises(PreviewUseCaseError) as captured:
        await env.execute(request=_request())

    assert captured.value.code is PreviewUseCaseFailureCode.AUTHORIZATION_FAILED
    assert session.query_entities == [User]
    assert env.resolver.calls == 0
    assert env.request_repository.requests == {}
    assert env.request_repository.events == []
    assert env.preview_repository.rows == {}
    assert env.runner.calls == 0


def test_http_composition_reuses_real_request_service_and_coordinator() -> None:
    env = _environment()
    app = FastAPI()
    app.include_router(quizzes_router, prefix="/api/v1")
    user = _user(
        actor_id=env.principal.actor_user_id,
        tenant_id=env.principal.tenant_id,
        role="methodologist",
    )

    async def current_user():
        return user

    async def db():
        return object()

    app.dependency_overrides[get_current_active_user] = current_user
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_tenant_editor_actor_authorizer] = (
        lambda: env.authorizer
    )
    app.dependency_overrides[get_question_context_resolver] = lambda: env.resolver
    app.dependency_overrides[get_editor_request_service] = (
        lambda: env.use_case._request_service
    )
    app.dependency_overrides[get_editor_preview_repository] = (
        lambda: env.preview_repository
    )
    app.dependency_overrides[get_question_preview_application_runner] = (
        lambda: env.runner
    )
    app.dependency_overrides[get_question_preview_coordinator] = (
        lambda: coordinate_question_preview
    )
    request = _request()
    payload = request.model_dump(mode="json")
    route = (
        f"/api/v1/quizzes/{env.context.quiz_id}/questions/"
        f"{env.context.question_id}/assistant/preview"
    )

    with TestClient(app) as client:
        first = client.post(route, json=payload)
        replay = client.post(route, json=payload)
        changed_preview = client.post(
            route,
            json={**payload, "preview_key": str(uuid4())},
        )

    assert first.status_code == replay.status_code == changed_preview.status_code == 200
    assert len(env.request_repository.requests) == 1
    assert len(env.request_repository.events) == 1
    assert len(env.preview_repository.rows) == 2
    assert env.runner.calls == 2
    assert env.authorizer.calls == 3


class UnexpectedAuthorizer:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, db, principal):
        del db, principal
        self.calls += 1
        raise RuntimeError("private database diagnostic must not leak")


def test_http_unexpected_authorizer_failure_is_one_pass_bounded_500() -> None:
    env = _environment()
    authorizer = UnexpectedAuthorizer()
    app = FastAPI()
    app.include_router(quizzes_router, prefix="/api/v1")
    user = _user(
        actor_id=env.principal.actor_user_id,
        tenant_id=env.principal.tenant_id,
        role="methodologist",
    )

    async def current_user():
        return user

    async def db():
        return object()

    app.dependency_overrides[get_current_active_user] = current_user
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_tenant_editor_actor_authorizer] = (
        lambda: authorizer
    )
    app.dependency_overrides[get_question_context_resolver] = lambda: env.resolver
    app.dependency_overrides[get_editor_request_service] = (
        lambda: env.use_case._request_service
    )
    app.dependency_overrides[get_editor_preview_repository] = (
        lambda: env.preview_repository
    )
    app.dependency_overrides[get_question_preview_application_runner] = (
        lambda: env.runner
    )
    app.dependency_overrides[get_question_preview_coordinator] = (
        lambda: coordinate_question_preview
    )
    route = (
        f"/api/v1/quizzes/{env.context.quiz_id}/questions/"
        f"{env.context.question_id}/assistant/preview"
    )

    with TestClient(app) as client:
        response = client.post(route, json=_request().model_dump(mode="json"))

    assert response.status_code == 500
    assert response.json() == {"detail": "Preview preparation failed."}
    assert "private database diagnostic" not in response.text
    assert authorizer.calls == 1
    assert env.resolver.calls == 0
    assert env.request_repository.requests == {}
    assert env.request_repository.events == []
    assert env.preview_repository.rows == {}
    assert env.runner.calls == 0


async def test_public_authorizer_rejects_platform_actor_impersonation():
    target_tenant_id, platform_actor_id = uuid4(), uuid4()
    session = AuthorizerSession(
        [_user(actor_id=platform_actor_id, tenant_id=None, role="superadmin")]
    )
    principal = TenantBoundEditorPrincipal(
        target_tenant_id, platform_actor_id, "superadmin"
    )

    with pytest.raises(ActorAuthorizationError):
        await authorize_tenant_editor_principal(session, principal)

    assert session.query_entities == [User]


async def test_direct_platform_principal_is_rejected_without_query():
    session = AuthorizerSession([])
    principal = TenantBoundEditorPrincipal(None, uuid4(), "superadmin")

    with pytest.raises(ActorAuthorizationError):
        await authorize_tenant_editor_principal(session, principal)

    assert session.statements == []


def test_dependency_composition_uses_principal_and_async_production_signatures():
    parameters = inspect.signature(QuestionPreviewUseCase.execute).parameters

    assert "principal" in parameters
    assert "tenant_id" not in parameters
    assert "actor_user_id" not in parameters
    assert "actor_role" not in parameters
    assert inspect.iscoroutinefunction(QuestionPreviewUseCase.execute)
    assert inspect.iscoroutinefunction(authorize_tenant_editor_principal)
    assert inspect.iscoroutinefunction(coordinate_question_preview)
