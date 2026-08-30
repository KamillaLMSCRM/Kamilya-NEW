from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.editor_assistant.patch_contract import (
    PatchIdempotencyCollisionError,
)
from app.modules.editor_assistant.preview_coordinator import (
    coordinate_question_preview,
)
from app.modules.editor_assistant.question_context import (
    QuestionChoiceContext,
    QuestionSourceFact,
    QuestionSourceReference,
    ResolvedQuestionContext,
)
from app.modules.editor_assistant.repository import EditorPreviewRecord
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

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_ID = UUID("22222222-2222-4222-8222-222222222222")
REQUEST_KEY = UUID("33333333-3333-4333-8333-333333333333")
PREVIEW_KEY = UUID("44444444-4444-4444-8444-444444444444")
ROW_ID = UUID("55555555-5555-4555-8555-555555555555")
SOURCE_ID = UUID("66666666-6666-4666-8666-666666666666")
CHOICE_1 = UUID("77777777-7777-4777-8777-777777777777")
CHOICE_2 = UUID("88888888-8888-4888-8888-888888888888")
COURSE_ID = UUID("99999999-9999-4999-8999-999999999999")
MODULE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
LESSON_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
QUIZ_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
QUESTION_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
CLAIM_TOKEN = "claim-token-0123456789"
FINGERPRINT = "a" * 64


def _expected_fingerprint(
    request: EditorAssistantPreviewRequest | None = None,
    context: ResolvedQuestionContext | None = None,
) -> str:
    current_request = request or _request()
    current_context = context or _context()
    normalized_instruction = " ".join(current_request.instruction.split())
    payload = {
        "schema_version": "editor_assistant.preview_coordinator.v1",
        "request_key": str(current_request.request_key),
        "preview_key": str(current_request.preview_key),
        "intent": current_request.intent.value,
        "tenant_id": str(current_context.tenant_id),
        "question_id": str(current_context.question_id),
        "context_snapshot_fingerprint": current_context.snapshot_fingerprint,
        "instruction_sha256": hashlib.sha256(
            normalized_instruction.encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _request(instruction: str = "Уточните формулировку вопроса") -> EditorAssistantPreviewRequest:
    return EditorAssistantPreviewRequest(
        request_key=REQUEST_KEY,
        preview_key=PREVIEW_KEY,
        intent=EditorIntent.REWRITE_WORDING,
        instruction=instruction,
    )


def _context() -> ResolvedQuestionContext:
    return ResolvedQuestionContext(
        tenant_id=TENANT_ID,
        course_id=COURSE_ID,
        module_id=MODULE_ID,
        lesson_id=LESSON_ID,
        quiz_id=QUIZ_ID,
        question_id=QUESTION_ID,
        question_type="MCQ",
        question_text="Как оформить доступ сотруднику?",
        choices=(
            QuestionChoiceContext(CHOICE_1, "Через утверждённый канал", True, 0),
            QuestionChoiceContext(CHOICE_2, "Через случайный канал", False, 1),
        ),
        correct_choice_id=CHOICE_1,
        explanation="Доступ оформляется по утверждённой процедуре.",
        locale="ru",
        source_references=(
            QuestionSourceReference(
                SOURCE_ID,
                "Регламент доступа",
                "Доступ / Раздел 1",
                "b" * 64,
            ),
        ),
        source_facts=(
            QuestionSourceFact(
                "fact-1",
                SOURCE_ID,
                "Сотрудник получает доступ через утверждённый канал.",
                "Доступ / Раздел 1",
                "b" * 64,
            ),
        ),
        snapshot_fingerprint="c" * 64,
    )


def _completed_response(context: ResolvedQuestionContext) -> EditorAssistantPreviewResponse:
    return EditorAssistantPreviewResponse(
        request_id=REQUEST_ID,
        preview_id=ROW_ID,
        state=EditorPreviewState.COMPLETED,
        applicability=EditorApplicability.APPLICABLE,
        base_snapshot_token="d" * 64,
        operations=(
            EditorAssistantPatchOperation(
                operation="replace",
                field_path=EditorPatchPath.TEXT,
                before_value=context.question_text,
                after_value="Как оформить доступ новому сотруднику?",
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
                    source_id=str(SOURCE_ID),
                    document_title="Регламент доступа",
                    locator="Доступ / Раздел 1",
                ),
            ),
        ),
        provenance=EditorAssistantProvenance(
            prompt_version="prompt-v1",
            generator_version="generator-v1",
            validator_version="validator-v1",
        ),
    )


def _failed_response(
    code: EditorAssistantFailureCode = EditorAssistantFailureCode.PROVIDER_TIMEOUT,
) -> EditorAssistantPreviewResponse:
    message, applicability = editor_assistant_failure_contract(code)
    return EditorAssistantPreviewResponse(
        request_id=REQUEST_ID,
        preview_id=ROW_ID,
        state=EditorPreviewState.FAILED,
        applicability=applicability,
        base_snapshot_token="d" * 64,
        source=EditorAssistantSourceProjection(source_reference_count=0, references=()),
        failure=EditorAssistantFailure(
            error_code=code,
            message=message,
        ),
    )


def _record(
    *,
    state: str = "pending",
    owns_claim: bool = False,
    claim_token: str | None = None,
    result: Mapping[str, Any] | None = None,
    failure_code: str | None = None,
    row_id: UUID = ROW_ID,
    request_id: UUID = REQUEST_ID,
    tenant_id: UUID = TENANT_ID,
    preview_key: str = str(PREVIEW_KEY),
    fingerprint: str = FINGERPRINT,
) -> EditorPreviewRecord:
    now = datetime.now(UTC)
    return EditorPreviewRecord(
        id=row_id,
        tenant_id=tenant_id,
        request_id=request_id,
        preview_key=preview_key,
        payload_fingerprint=fingerprint,
        state=state,
        owns_claim=owns_claim,
        claim_token=claim_token if owns_claim else None,
        completed_result=dict(result) if result is not None else None,
        failure_code=failure_code if state == "failed" else None,
        created_at=now,
        updated_at=now,
        completed_at=now if state == "completed" else None,
        failed_at=now if state == "failed" else None,
    )


class FakePreviewRepository:
    def __init__(self) -> None:
        self.request_ids = {(TENANT_ID, REQUEST_ID)}
        self.rows: dict[tuple[UUID, str], EditorPreviewRecord] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reject_complete = False
        self.reject_fail = False
        self.raise_on_claim = False
        self.raise_on_read = False
        self.terminal_fingerprint_override: str | None = None

    async def claim_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
        payload_fingerprint: str,
    ) -> EditorPreviewRecord | None:
        kwargs = {
            "tenant_id": tenant_id,
            "request_id": request_id,
            "preview_key": preview_key,
            "payload_fingerprint": payload_fingerprint,
        }
        self.calls.append(("claim_preview", kwargs))
        if self.raise_on_claim:
            raise RuntimeError("database detail must not escape")
        if (tenant_id, request_id) not in self.request_ids:
            return None
        key = (tenant_id, preview_key)
        existing = self.rows.get(key)
        if existing is not None:
            if (
                existing.request_id != request_id
                or existing.payload_fingerprint != payload_fingerprint
            ):
                raise PatchIdempotencyCollisionError("private collision detail")
            return existing
        row = _record(
            owns_claim=True,
            claim_token=CLAIM_TOKEN,
            fingerprint=payload_fingerprint,
            tenant_id=tenant_id,
            request_id=request_id,
        )
        self.rows[key] = row
        return row

    async def read_preview(
        self,
        *,
        tenant_id: Any,
        request_id: Any,
        preview_key: str,
    ) -> EditorPreviewRecord | None:
        self.calls.append(
            (
                "read_preview",
                {
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "preview_key": preview_key,
                },
            )
        )
        if self.raise_on_read:
            raise RuntimeError("database detail must not escape")
        row = self.rows.get((tenant_id, preview_key))
        if row is None or row.request_id != request_id:
            return None
        return row

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
        self.calls.append(
            (
                "complete_preview",
                {
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "preview_key": preview_key,
                    "payload_fingerprint": payload_fingerprint,
                    "claim_token": claim_token,
                    "completed_result": dict(completed_result),
                },
            )
        )
        if self.reject_complete:
            return None
        row = self.rows[(tenant_id, preview_key)]
        if row.claim_token != claim_token or row.state != "pending":
            return None
        updated = replace(
            row,
            payload_fingerprint=(
                self.terminal_fingerprint_override or row.payload_fingerprint
            ),
            state="completed",
            owns_claim=False,
            claim_token=None,
            completed_result=dict(completed_result),
            completed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.rows[(tenant_id, preview_key)] = updated
        return updated

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
        self.calls.append(
            (
                "fail_preview",
                {
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "preview_key": preview_key,
                    "payload_fingerprint": payload_fingerprint,
                    "claim_token": claim_token,
                    "failure_code": failure_code,
                },
            )
        )
        if self.reject_fail:
            return None
        row = self.rows[(tenant_id, preview_key)]
        if row.claim_token != claim_token or row.state != "pending":
            return None
        updated = replace(
            row,
            payload_fingerprint=(
                self.terminal_fingerprint_override or row.payload_fingerprint
            ),
            state="failed",
            owns_claim=False,
            claim_token=None,
            completed_result=None,
            failure_code=str(failure_code),
            failed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.rows[(tenant_id, preview_key)] = updated
        return updated

    async def reclaim_preview(self, **_: Any) -> EditorPreviewRecord | None:
        raise AssertionError("reclaim must not be called")


Runner = Callable[[ResolvedQuestionContext, EditorAssistantPreviewRequest, Any], Awaitable[EditorAssistantPreviewResponse]]


def _runner_for(
    response: EditorAssistantPreviewResponse | None = None,
    *,
    error: Exception | None = None,
    calls: list[int] | None = None,
) -> Runner:
    async def runner(
        context: ResolvedQuestionContext,
        request: EditorAssistantPreviewRequest,
        identity_factory: Any,
    ) -> EditorAssistantPreviewResponse:
        del context, request
        if calls is not None:
            calls.append(1)
        if error is not None:
            raise error
        assert response is not None
        assert identity_factory(_request()) == (REQUEST_ID, ROW_ID)
        return response

    return runner


async def _coordinate(
    repository: FakePreviewRepository,
    runner: Runner,
    *,
    tenant_id: UUID = TENANT_ID,
    request_id: UUID = REQUEST_ID,
    request: EditorAssistantPreviewRequest | None = None,
    context: ResolvedQuestionContext | None = None,
) -> EditorAssistantPreviewResponse:
    return await coordinate_question_preview(
        tenant_id=tenant_id,
        editor_request_id=request_id,
        context=context or _context(),
        request=request or _request(),
        repository=repository,
        application_runner=runner,
    )


@pytest.mark.asyncio
async def test_owner_completed_persists_only_dto_and_reads_back() -> None:
    repository = FakePreviewRepository()
    calls: list[int] = []
    response = await _coordinate(
        repository,
        _runner_for(_completed_response(_context()), calls=calls),
    )

    assert response.state is EditorPreviewState.COMPLETED
    assert response.request_id == REQUEST_ID
    assert response.preview_id == ROW_ID
    assert calls == [1]
    names = [name for name, _ in repository.calls]
    assert names == ["claim_preview", "complete_preview", "read_preview"]
    complete = repository.calls[1][1]
    assert set(complete) == {
        "tenant_id",
        "request_id",
        "preview_key",
        "payload_fingerprint",
        "claim_token",
        "completed_result",
    }
    assert complete["completed_result"] == response.model_dump(mode="json")
    assert complete["payload_fingerprint"] == _expected_fingerprint()
    assert complete["payload_fingerprint"] != _request().instruction
    assert "Регламент доступа" in repr(complete["completed_result"])


@pytest.mark.asyncio
async def test_owner_failed_persists_only_closed_failure_code() -> None:
    repository = FakePreviewRepository()
    response = await _coordinate(repository, _runner_for(_failed_response()))

    assert response.state is EditorPreviewState.FAILED
    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.PROVIDER_TIMEOUT
    fail = next(kwargs for name, kwargs in repository.calls if name == "fail_preview")
    assert fail["failure_code"] == "provider_timeout"
    assert set(fail) == {
        "tenant_id",
        "request_id",
        "preview_key",
        "payload_fingerprint",
        "claim_token",
        "failure_code",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    (
        EditorAssistantFailureCode.STALE_BASE_VERSION,
        EditorAssistantFailureCode.REQUIRES_NEW_DRAFT_REVISION,
    ),
)
async def test_owner_failure_preserves_canonical_applicability(
    code: EditorAssistantFailureCode,
) -> None:
    repository = FakePreviewRepository()
    response = await _coordinate(repository, _runner_for(_failed_response(code)))
    message, applicability = editor_assistant_failure_contract(code)

    assert response.request_id == REQUEST_ID
    assert response.preview_id == ROW_ID
    assert response.applicability is applicability
    assert response.failure is not None
    assert response.failure.error_code is code
    assert response.failure.message == message


@pytest.mark.asyncio
async def test_duplicate_completed_does_not_invoke_ai() -> None:
    repository = FakePreviewRepository()
    original = _completed_response(_context()).model_dump(mode="json")
    repository.rows[(TENANT_ID, str(PREVIEW_KEY))] = _record(
        state="completed", result=original, fingerprint=_expected_fingerprint()
    )
    calls: list[int] = []

    response = await _coordinate(repository, _runner_for(error=AssertionError(), calls=calls))

    assert response.state is EditorPreviewState.COMPLETED
    assert calls == []
    assert [name for name, _ in repository.calls] == ["claim_preview"]


@pytest.mark.asyncio
async def test_duplicate_failed_does_not_invoke_ai() -> None:
    repository = FakePreviewRepository()
    repository.rows[(TENANT_ID, str(PREVIEW_KEY))] = _record(
        state="failed",
        failure_code="provider_timeout",
        fingerprint=_expected_fingerprint(),
    )
    calls: list[int] = []

    response = await _coordinate(repository, _runner_for(error=AssertionError(), calls=calls))

    assert response.state is EditorPreviewState.FAILED
    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.PROVIDER_TIMEOUT
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    (
        EditorAssistantFailureCode.STALE_BASE_VERSION,
        EditorAssistantFailureCode.REQUIRES_NEW_DRAFT_REVISION,
    ),
)
async def test_duplicate_failure_preserves_canonical_applicability_without_ai(
    code: EditorAssistantFailureCode,
) -> None:
    repository = FakePreviewRepository()
    repository.rows[(TENANT_ID, str(PREVIEW_KEY))] = _record(
        state="failed",
        failure_code=code.value,
        fingerprint=_expected_fingerprint(),
    )
    calls: list[int] = []

    response = await _coordinate(
        repository,
        _runner_for(error=AssertionError(), calls=calls),
    )
    message, applicability = editor_assistant_failure_contract(code)

    assert response.applicability is applicability
    assert response.failure is not None
    assert response.failure.error_code is code
    assert response.failure.message == message
    assert calls == []


@pytest.mark.asyncio
async def test_duplicate_pending_returns_pending_without_ai() -> None:
    repository = FakePreviewRepository()
    repository.rows[(TENANT_ID, str(PREVIEW_KEY))] = _record(
        fingerprint=_expected_fingerprint(),
        claim_token=CLAIM_TOKEN,
    )
    calls: list[int] = []

    response = await _coordinate(repository, _runner_for(error=AssertionError(), calls=calls))

    assert response.state is EditorPreviewState.PENDING
    assert response.applicability is EditorApplicability.NOT_APPLICABLE
    assert calls == []


@pytest.mark.asyncio
async def test_fingerprint_mismatch_fails_closed_without_ai_or_failure_mutation() -> None:
    repository = FakePreviewRepository()
    repository.rows[(TENANT_ID, str(PREVIEW_KEY))] = _record(fingerprint="e" * 64)
    calls: list[int] = []

    response = await _coordinate(repository, _runner_for(error=AssertionError(), calls=calls))

    assert response.state is EditorPreviewState.FAILED
    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.CONTRACT_VIOLATION
    assert calls == []
    assert [name for name, _ in repository.calls] == ["claim_preview"]


@pytest.mark.asyncio
async def test_missing_or_cross_tenant_request_is_non_enumerating_and_bounded() -> None:
    repository = FakePreviewRepository()
    calls: list[int] = []
    missing_tenant = UUID("99999999-9999-4999-8999-999999999999")

    response = await _coordinate(
        repository,
        _runner_for(error=AssertionError(), calls=calls),
        tenant_id=missing_tenant,
        context=replace(_context(), tenant_id=missing_tenant),
    )

    assert response.state is EditorPreviewState.FAILED
    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert calls == []
    assert len(repository.calls) == 1
    assert repository.calls[0][0] == "claim_preview"


@pytest.mark.asyncio
async def test_context_tenant_mismatch_stops_before_repository_and_runner() -> None:
    repository = FakePreviewRepository()
    calls: list[int] = []
    foreign_tenant = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    first_foreign_context = replace(
        _context(),
        tenant_id=foreign_tenant,
        snapshot_fingerprint="1" * 64,
    )
    second_foreign_context = replace(
        first_foreign_context,
        snapshot_fingerprint="2" * 64,
    )

    first_response = await _coordinate(
        repository,
        _runner_for(error=AssertionError(), calls=calls),
        context=first_foreign_context,
    )
    second_response = await _coordinate(
        repository,
        _runner_for(error=AssertionError(), calls=calls),
        context=second_foreign_context,
    )

    assert first_response.failure is not None
    assert second_response.failure is not None
    assert first_response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert second_response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert first_response.base_snapshot_token == second_response.base_snapshot_token
    assert first_response.base_snapshot_token not in {
        first_foreign_context.snapshot_fingerprint,
        second_foreign_context.snapshot_fingerprint,
    }
    assert repository.calls == []
    assert calls == []


@pytest.mark.asyncio
async def test_payload_fingerprint_is_bound_to_context_tenant() -> None:
    first_repository = FakePreviewRepository()
    second_repository = FakePreviewRepository()
    second_tenant = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    second_context = replace(_context(), tenant_id=second_tenant)
    second_repository.request_ids.add((second_tenant, REQUEST_ID))

    await _coordinate(
        first_repository,
        _runner_for(_completed_response(_context())),
    )
    await _coordinate(
        second_repository,
        _runner_for(_completed_response(second_context)),
        tenant_id=second_tenant,
        context=second_context,
    )

    first_fingerprint = first_repository.calls[0][1]["payload_fingerprint"]
    second_fingerprint = second_repository.calls[0][1]["payload_fingerprint"]
    assert first_fingerprint == _expected_fingerprint()
    assert second_fingerprint == _expected_fingerprint(context=second_context)
    assert first_fingerprint != second_fingerprint


@pytest.mark.asyncio
async def test_malformed_stored_json_fails_closed_without_ai_or_mutation() -> None:
    repository = FakePreviewRepository()
    repository.rows[(TENANT_ID, str(PREVIEW_KEY))] = _record(
        state="completed",
        result={"state": "completed", "raw_instruction": "must not be returned"},
        fingerprint=_expected_fingerprint(),
    )
    calls: list[int] = []

    response = await _coordinate(repository, _runner_for(error=AssertionError(), calls=calls))

    assert response.state is EditorPreviewState.FAILED
    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert calls == []
    assert [name for name, _ in repository.calls] == ["claim_preview"]


@pytest.mark.asyncio
async def test_complete_token_mismatch_returns_bounded_error_without_second_mutation() -> None:
    repository = FakePreviewRepository()
    repository.reject_complete = True
    calls: list[int] = []

    response = await _coordinate(
        repository,
        _runner_for(_completed_response(_context()), calls=calls),
    )

    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert calls == [1]
    assert [name for name, _ in repository.calls] == ["claim_preview", "complete_preview"]


@pytest.mark.asyncio
async def test_fail_token_mismatch_returns_bounded_error_without_second_mutation() -> None:
    repository = FakePreviewRepository()
    repository.reject_fail = True
    calls: list[int] = []

    response = await _coordinate(
        repository,
        _runner_for(_failed_response(), calls=calls),
    )

    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert calls == [1]
    assert [name for name, _ in repository.calls] == ["claim_preview", "fail_preview"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner_response", "terminal_method"),
    (
        (_completed_response(_context()), "complete_preview"),
        (_failed_response(), "fail_preview"),
    ),
)
async def test_mutated_terminal_fingerprint_fails_closed_without_second_mutation(
    runner_response: EditorAssistantPreviewResponse,
    terminal_method: str,
) -> None:
    repository = FakePreviewRepository()
    repository.terminal_fingerprint_override = "f" * 64

    response = await _coordinate(repository, _runner_for(runner_response))

    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    terminal_calls = [
        name
        for name, _ in repository.calls
        if name in {"complete_preview", "fail_preview"}
    ]
    assert terminal_calls == [terminal_method]


@pytest.mark.asyncio
async def test_foreign_failed_runner_identity_persists_contract_violation() -> None:
    repository = FakePreviewRepository()
    foreign = _failed_response().model_copy(
        update={"request_id": uuid4(), "preview_id": uuid4()}
    )

    response = await _coordinate(repository, _runner_for(foreign))

    assert response.request_id == REQUEST_ID
    assert response.preview_id == ROW_ID
    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.CONTRACT_VIOLATION
    fail = next(kwargs for name, kwargs in repository.calls if name == "fail_preview")
    assert fail["failure_code"] == EditorAssistantFailureCode.CONTRACT_VIOLATION.value


@pytest.mark.asyncio
async def test_application_exception_fails_once_with_internal_error() -> None:
    repository = FakePreviewRepository()
    calls: list[int] = []

    response = await _coordinate(
        repository,
        _runner_for(error=RuntimeError("source and provider text must not escape"), calls=calls),
    )

    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert calls == [1]
    assert [name for name, _ in repository.calls] == [
        "claim_preview",
        "fail_preview",
        "read_preview",
    ]
    serialized_calls = repr(repository.calls)
    assert "source and provider text" not in serialized_calls


@pytest.mark.asyncio
async def test_claim_and_complete_arguments_contain_no_raw_instruction_or_source_content() -> None:
    repository = FakePreviewRepository()
    secret_instruction = "PRIVATE RAW INSTRUCTION 9f2e"
    response = await _coordinate(
        repository,
        _runner_for(_completed_response(_context())),
        request=_request(secret_instruction),
    )

    assert response.state is EditorPreviewState.COMPLETED
    serialized_calls = repr(repository.calls)
    assert secret_instruction not in serialized_calls
    assert "Сотрудник получает доступ" not in serialized_calls
    complete = next(kwargs for name, kwargs in repository.calls if name == "complete_preview")
    assert "Регламент доступа" in repr(complete["completed_result"])
    claim = repository.calls[0][1]
    assert len(claim["payload_fingerprint"]) == 64
    assert claim["payload_fingerprint"] != secret_instruction


@pytest.mark.asyncio
async def test_claim_database_exception_returns_internal_error_without_second_mutation() -> None:
    repository = FakePreviewRepository()
    repository.raise_on_claim = True
    calls: list[int] = []

    response = await _coordinate(repository, _runner_for(error=AssertionError(), calls=calls))

    assert response.failure is not None
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert calls == []
    assert [name for name, _ in repository.calls] == ["claim_preview"]
