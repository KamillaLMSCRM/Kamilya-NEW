"""Application-seam tests for trusted single-question assistant context."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.modules.editor_assistant.question_context import (
    AuthorizedEditorRole,
    QuestionContextError,
    QuestionContextFailureCode,
    resolve_question_context,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")
COURSE_ID = UUID("33333333-3333-4333-8333-333333333333")
MODULE_ID = UUID("44444444-4444-4444-8444-444444444444")
LESSON_ID = UUID("55555555-5555-4555-8555-555555555555")
QUIZ_ID = UUID("66666666-6666-4666-8666-666666666666")
QUESTION_ID = UUID("77777777-7777-4777-8777-777777777777")
CHOICE_IDS = (
    UUID("88888888-8888-4888-8888-888888888888"),
    UUID("99999999-9999-4999-8999-999999999999"),
)
DOCUMENT_IDS = (
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
)
DOCUMENT_HASHES = ("a" * 64, "b" * 64)


class _FakeScalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _FakeMappings:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self._values = values

    def all(self) -> list[dict[str, object]]:
        return self._values


class _FakeResult:
    def __init__(
        self,
        *,
        first: tuple[object, ...] | None = None,
        scalars: list[object] | None = None,
        mappings: list[dict[str, object]] | None = None,
    ) -> None:
        self._first = first
        self._scalars = scalars or []
        self._mappings = mappings or []

    def first(self) -> tuple[object, ...] | None:
        return self._first

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars)

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._mappings)


class FakeAsyncSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = iter(results)
        self.execute_count = 0

    async def execute(self, statement: object, params: object = None) -> _FakeResult:
        del statement, params
        self.execute_count += 1
        return next(self._results)


def _fixture(
    *,
    graph_tenant_id: UUID = TENANT_ID,
    course_status: str = "draft",
    current_release_id: UUID | None = None,
    lesson_published_at: datetime | None = None,
    question_type: str = "MCQ",
    question_quiz_id: UUID = QUIZ_ID,
    question_text: str = "Когда сотрудник должен отозвать доступ?",
    choice_texts: tuple[str, str] = ("Сразу после увольнения", "Через месяц"),
    explanation: str | None = "Доступ отзывают сразу после увольнения.",
    correct_flags: tuple[bool, bool] = (True, False),
    linked_document_ids: list[str] | None = None,
    lesson_document_ids: list[str] | None = None,
    document_overrides: dict[int, dict[str, object]] | None = None,
    fact_rows: list[dict[str, object]] | None = None,
    graph_present: bool = True,
) -> FakeAsyncSession:
    course = SimpleNamespace(
        id=COURSE_ID,
        tenant_id=graph_tenant_id,
        status=course_status,
        current_release_id=current_release_id,
        source_document_ids=(
            linked_document_ids
            if linked_document_ids is not None
            else [str(DOCUMENT_IDS[0])]
        ),
    )
    module = SimpleNamespace(
        id=MODULE_ID,
        tenant_id=graph_tenant_id,
        course_id=COURSE_ID,
    )
    lesson = SimpleNamespace(
        id=LESSON_ID,
        tenant_id=graph_tenant_id,
        module_id=MODULE_ID,
        source_document_ids=(
            lesson_document_ids
            if lesson_document_ids is not None
            else [str(DOCUMENT_IDS[1]), str(DOCUMENT_IDS[0])]
        ),
        published_at=lesson_published_at,
    )
    quiz = SimpleNamespace(
        id=QUIZ_ID,
        tenant_id=graph_tenant_id,
        lesson_id=LESSON_ID,
    )
    question = SimpleNamespace(
        id=QUESTION_ID,
        quiz_id=question_quiz_id,
        text=question_text,
        type=question_type,
        explanation=explanation,
    )
    choices = [
        SimpleNamespace(
            id=CHOICE_IDS[index],
            question_id=QUESTION_ID,
            text=text,
            is_correct=correct_flags[index],
            order_index=index,
        )
        for index, text in enumerate(choice_texts)
    ]
    documents = []
    for index in range(2):
        values: dict[str, object] = {
            "id": DOCUMENT_IDS[index],
            "tenant_id": graph_tenant_id,
            "title": f"Документ {index + 1}",
            "lifecycle_status": "active",
            "embedding_status": "success",
            "index_status": "ready" if index == 0 else "partial",
            "content_sha256": DOCUMENT_HASHES[index],
        }
        values.update((document_overrides or {}).get(index, {}))
        documents.append(SimpleNamespace(**values))
    facts = fact_rows if fact_rows is not None else [
        {
            "fact_id": f"chunk_{index + 1:02d}",
            "source_id": str(DOCUMENT_IDS[index]),
            "source_text": f"  Подтверждённый   факт {index + 1}.  ",
            "headings": [f"Раздел {index + 1}"],
            "chunk_index": index,
            "content_sha256": DOCUMENT_HASHES[index],
        }
        for index in range(2)
    ]
    graph = (quiz, question, lesson, module, course) if graph_present else None
    return FakeAsyncSession(
        [
            _FakeResult(first=graph),
            _FakeResult(scalars=choices),
            _FakeResult(scalars=documents),
            _FakeResult(mappings=facts),
        ]
    )


async def _resolve(session: FakeAsyncSession):
    return await resolve_question_context(
        session,
        tenant_id=TENANT_ID,
        authorized_role=AuthorizedEditorRole.METHODOLOGIST,
        quiz_id=QUIZ_ID,
        question_id=QUESTION_ID,
    )


@pytest.mark.asyncio
async def test_resolves_bounded_immutable_draft_mcq_context_deterministically() -> None:
    first = await _resolve(_fixture())
    second = await _resolve(_fixture())

    assert first.tenant_id == TENANT_ID
    assert (first.course_id, first.module_id, first.lesson_id, first.quiz_id) == (
        COURSE_ID,
        MODULE_ID,
        LESSON_ID,
        QUIZ_ID,
    )
    assert first.question_id == QUESTION_ID
    assert first.question_type == "MCQ"
    assert first.locale == "ru"
    assert first.question_text == "Когда сотрудник должен отозвать доступ?"
    assert first.explanation == "Доступ отзывают сразу после увольнения."
    assert [choice.choice_id for choice in first.choices] == list(CHOICE_IDS)
    assert first.correct_choice_id == CHOICE_IDS[0]
    assert [reference.source_id for reference in first.source_references] == list(
        DOCUMENT_IDS
    )
    assert [fact.text for fact in first.source_facts] == [
        "Подтверждённый факт 1.",
        "Подтверждённый факт 2.",
    ]
    assert len(first.snapshot_fingerprint) == 64
    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert "provider" not in first.__dataclass_fields__
    assert "model" not in first.__dataclass_fields__
    assert "raw_prompt" not in first.__dataclass_fields__
    with pytest.raises(FrozenInstanceError):
        first.question_text = "Changed"  # type: ignore[misc]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_override",
    (
        {"question_text": "Когда именно необходимо отозвать доступ сотрудника?"},
        {
            "choice_texts": (
                "Немедленно после увольнения",
                "Через месяц",
            )
        },
        {"explanation": "Доступ необходимо отозвать без задержки."},
    ),
)
async def test_snapshot_fingerprint_changes_with_each_editable_content_field(
    fixture_override: dict[str, object],
) -> None:
    baseline = await _resolve(_fixture())
    unchanged = await _resolve(_fixture())
    changed = await _resolve(_fixture(**fixture_override))  # type: ignore[arg-type]

    assert unchanged.snapshot_fingerprint == baseline.snapshot_fingerprint
    assert changed.snapshot_fingerprint != baseline.snapshot_fingerprint


@pytest.mark.asyncio
async def test_snapshot_fingerprint_currently_tracks_source_display_metadata() -> None:
    baseline = await _resolve(_fixture())
    renamed_source = await _resolve(
        _fixture(document_overrides={0: {"title": "Переименованный документ"}})
    )

    assert renamed_source.snapshot_fingerprint != baseline.snapshot_fingerprint


@pytest.mark.asyncio
async def test_missing_wrong_tenant_and_graph_mismatch_are_non_enumerating() -> None:
    sessions = (
        _fixture(graph_present=False),
        _fixture(graph_tenant_id=OTHER_TENANT_ID),
        _fixture(question_quiz_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")),
    )
    errors = []
    for session in sessions:
        with pytest.raises(QuestionContextError) as captured:
            await _resolve(session)
        errors.append(captured.value)

    assert {error.code for error in errors} == {
        QuestionContextFailureCode.CONTEXT_UNAVAILABLE
    }
    assert len({str(error) for error in errors}) == 1
    assert str(QUIZ_ID) not in str(errors[0])
    assert str(OTHER_TENANT_ID) not in str(errors[1])


@pytest.mark.asyncio
async def test_untrusted_role_is_rejected_before_context_read() -> None:
    session = _fixture()
    with pytest.raises(QuestionContextError) as captured:
        await resolve_question_context(
            session,
            tenant_id=TENANT_ID,
            authorized_role="employee",
            quiz_id=QUIZ_ID,
            question_id=QUESTION_ID,
        )
    assert captured.value.code is QuestionContextFailureCode.CONTEXT_UNAVAILABLE
    assert session.execute_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("course_status", ("published", "archived"))
async def test_non_draft_course_requires_new_draft_revision(
    course_status: str,
) -> None:
    with pytest.raises(QuestionContextError) as captured:
        await _resolve(_fixture(course_status=course_status))
    assert captured.value.code is QuestionContextFailureCode.REQUIRES_NEW_DRAFT_REVISION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    (
        {"current_release_id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")},
        {"lesson_published_at": datetime(2026, 8, 30, tzinfo=UTC)},
    ),
)
async def test_historical_release_metadata_does_not_block_current_draft(
    override: dict[str, object],
) -> None:
    context = await _resolve(_fixture(course_status="draft", **override))  # type: ignore[arg-type]

    assert context.course_id == COURSE_ID
    assert context.question_id == QUESTION_ID


@pytest.mark.asyncio
async def test_only_existing_single_correct_mcq_is_supported() -> None:
    with pytest.raises(QuestionContextError) as unsupported:
        await _resolve(_fixture(question_type="true_false"))
    assert unsupported.value.code is QuestionContextFailureCode.NOT_APPLICABLE
    assert unsupported.value.code.value == "not_applicable"
    assert str(unsupported.value) == "Этот тип вопроса пока не поддерживается."

    with pytest.raises(QuestionContextError) as malformed:
        await _resolve(_fixture(correct_flags=(True, True)))
    assert malformed.value.code is QuestionContextFailureCode.MALFORMED_QUESTION
    assert "correct" not in str(malformed.value).casefold()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document_overrides",
    (
        {0: {"tenant_id": OTHER_TENANT_ID}},
        {0: {"lifecycle_status": "deletion_pending"}},
        {0: {"embedding_status": "pending"}},
        {0: {"index_status": "processing"}},
        {0: {"content_sha256": None}},
    ),
)
async def test_invalid_linked_document_is_ignored_when_another_source_is_confirmed(
    document_overrides: dict[int, dict[str, object]],
) -> None:
    context = await _resolve(_fixture(document_overrides=document_overrides))

    assert [reference.source_id for reference in context.source_references] == [
        DOCUMENT_IDS[1]
    ]
    assert [fact.source_id for fact in context.source_facts] == [DOCUMENT_IDS[1]]


@pytest.mark.asyncio
async def test_all_linked_documents_invalid_still_fails_closed() -> None:
    with pytest.raises(QuestionContextError) as captured:
        await _resolve(
            _fixture(
                document_overrides={
                    0: {"embedding_status": "pending"},
                    1: {"lifecycle_status": "deletion_pending"},
                }
            )
        )
    assert captured.value.code is QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE


@pytest.mark.asyncio
async def test_linked_source_input_remains_bounded_to_eight_unique_values() -> None:
    linked_ids = [str(UUID(int=index + 1)) for index in range(9)]
    with pytest.raises(QuestionContextError) as captured:
        await _resolve(
            _fixture(
                linked_document_ids=linked_ids,
                lesson_document_ids=[],
            )
        )
    assert captured.value.code is QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE


@pytest.mark.asyncio
async def test_source_evidence_requires_well_formed_links_and_current_facts() -> None:
    valid_despite_invalid_link = await _resolve(
        _fixture(linked_document_ids=["not-a-uuid"])
    )
    assert [reference.source_id for reference in valid_despite_invalid_link.source_references] == list(
        DOCUMENT_IDS
    )

    with pytest.raises(QuestionContextError) as missing_fact:
        await _resolve(_fixture(fact_rows=[]))
    assert missing_fact.value.code is QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE

    stale_facts = [
        {
            "fact_id": "chunk_01",
            "source_id": str(DOCUMENT_IDS[0]),
            "source_text": "Факт",
            "headings": ["Раздел"],
            "chunk_index": 0,
            "content_sha256": "f" * 64,
        },
        {
            "fact_id": "chunk_02",
            "source_id": str(DOCUMENT_IDS[1]),
            "source_text": "Факт",
            "headings": ["Раздел"],
            "chunk_index": 0,
            "content_sha256": DOCUMENT_HASHES[1],
        },
    ]
    current_subset = await _resolve(_fixture(fact_rows=stale_facts))
    assert [reference.source_id for reference in current_subset.source_references] == [
        DOCUMENT_IDS[1]
    ]
    assert [fact.source_id for fact in current_subset.source_facts] == [DOCUMENT_IDS[1]]

    with pytest.raises(QuestionContextError) as no_confirmed_fact:
        await _resolve(
            _fixture(
                fact_rows=[
                    {**row, "content_sha256": "f" * 64}
                    for row in stale_facts
                ]
            )
        )
    assert no_confirmed_fact.value.code is QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE


@pytest.mark.asyncio
async def test_source_projection_is_bounded_and_does_not_expose_provider_metadata() -> None:
    oversized = [
        {
            "fact_id": "chunk_01",
            "source_id": str(DOCUMENT_IDS[0]),
            "source_text": "x" * 1_201,
            "headings": ["Раздел"],
            "chunk_index": 0,
            "content_sha256": DOCUMENT_HASHES[0],
            "embedding_provider": "must-not-leak",
            "embedding_model": "must-not-leak",
        },
        {
            "fact_id": "chunk_02",
            "source_id": str(DOCUMENT_IDS[1]),
            "source_text": "Факт",
            "headings": ["Раздел"],
            "chunk_index": 0,
            "content_sha256": DOCUMENT_HASHES[1],
        },
    ]
    bounded_subset = await _resolve(_fixture(fact_rows=oversized))
    assert [reference.source_id for reference in bounded_subset.source_references] == [
        DOCUMENT_IDS[1]
    ]
    assert [fact.source_id for fact in bounded_subset.source_facts] == [DOCUMENT_IDS[1]]

    context = await _resolve(_fixture())
    assert all("provider" not in fact.__dataclass_fields__ for fact in context.source_facts)
    assert all("model" not in fact.__dataclass_fields__ for fact in context.source_facts)
