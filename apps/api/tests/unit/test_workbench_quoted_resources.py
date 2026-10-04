"""Service-level regressions for quoted natural-assignment resource names."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.methodologist_workbench import assignment_service as service
from app.modules.methodologist_workbench.assignment_schemas import AssignmentPreviewRequest, Recipient
from app.modules.methodologist_workbench.natural_assignment_intent import AssignmentCandidate
from app.modules.methodologist_workbench.plan_contract import ActorContext

NOW = datetime(2026, 10, 1, 10, tzinfo=UTC)


def uid(number: int) -> UUID:
    return UUID(int=number)


def _rows(values: list[object]) -> SimpleNamespace:
    return SimpleNamespace(all=lambda: values)


def _fixtures() -> tuple[ActorContext, AssignmentPreviewRequest, tuple[object, ...]]:
    actor = ActorContext(tenant_id=uid(2), actor_id=uid(3), active_role="methodologist")
    course = SimpleNamespace(
        id=uid(4), title="QA: можно повторить", current_release_id=uid(8), status="published"
    )
    department = SimpleNamespace(id=uid(5), name="Отдел проверки")
    release = SimpleNamespace(id=uid(8), snapshot_sha256="a" * 64)
    recipients = (Recipient(user_id=uid(6), label="Новый", already_assigned=False, access_warning=False),)
    candidate = AssignmentCandidate(
        course_query="«QA: можно повторить»",
        department_query="«Отдел проверки»",
        due_date="2026-10-20",
        due_time="23:59:59",
    )
    body = AssignmentPreviewRequest(
        instruction="ignored in candidate mode",
        timezone_name="Asia/Almaty",
        candidate=candidate,
    )
    return actor, body, (course, department, release, recipients, "b" * 64)


@pytest.mark.asyncio
async def test_candidate_mode_falls_back_once_for_paired_outer_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    actor, body, binding = _fixtures()
    course, department, _, _, _ = binding
    db = SimpleNamespace(
        # Each resource performs raw first, then its own unwrapped fallback only after a miss.
        scalars=AsyncMock(side_effect=[_rows([]), _rows([course]), _rows([]), _rows([department])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    monkeypatch.setattr(service, "_bindings", AsyncMock(return_value=binding))

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "preview_ready"
    assert result.course_title == "QA: можно повторить"
    assert result.department_name == "Отдел проверки"
    assert db.scalars.await_count == 4
    assert db.scalar.await_count == 1  # outstanding-preview limit only; resource resolution uses scalars
    assert db.add.call_count == db.flush.await_count == 1

    statements = [call.args[0] for call in db.scalars.await_args_list]
    compiled = [statement.compile(dialect=postgresql.dialect()) for statement in statements]
    sql = [str(statement) for statement in compiled]
    assert all("LIMIT" in statement and 21 in compiled_item.params.values() for statement, compiled_item in zip(sql, compiled, strict=True))
    assert "courses.tenant_id" in sql[0] and "courses.status" in sql[0]
    assert "courses.tenant_id" in sql[1] and "courses.status" in sql[1]
    assert "departments.tenant_id" in sql[2] and "departments.is_active" in sql[2]
    assert "departments.tenant_id" in sql[3] and "departments.is_active" in sql[3]
    assert all("departments.archived_at" in sql[index] for index in (2, 3))
    assert body.candidate is not None
    assert body.candidate.course_query == "«QA: можно повторить»"
    assert body.candidate.department_query == "«Отдел проверки»"


@pytest.mark.asyncio
async def test_candidate_mode_preserves_exact_literal_quoted_resource_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, body, binding = _fixtures()
    course, department, _, _, _ = binding
    literal_course = SimpleNamespace(
        id=uid(40), title="«QA: можно повторить»", current_release_id=uid(8), status="published"
    )
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([literal_course]), _rows([department])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    monkeypatch.setattr(service, "_bindings", AsyncMock(return_value=(literal_course, department, *binding[2:])))

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "preview_ready"
    assert result.course_title == "«QA: можно повторить»"
    assert result.course_id == literal_course.id
    assert db.scalars.await_count == 2


@pytest.mark.asyncio
async def test_department_fallback_ambiguity_returns_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    actor, body, binding = _fixtures()
    course, department, _, _, _ = binding
    department_two = SimpleNamespace(id=uid(55), name="Отдел проверки 2")
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([course]), _rows([]), _rows([department, department_two])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    bindings = AsyncMock(return_value=binding)
    monkeypatch.setattr(service, "_bindings", bindings)

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "clarification_needed"
    assert result.code == "choose_exact_resources"
    assert tuple(choice.id for choice in result.department_choices) == (department.id, department_two.id)
    bindings.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_selected_wrong_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    actor, body, binding = _fixtures()
    course, department, _, _, _ = binding
    body = body.model_copy(update={"course_id": uid(99)})
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([]), _rows([course]), _rows([department])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    bindings = AsyncMock(return_value=binding)
    monkeypatch.setattr(service, "_bindings", bindings)

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "clarification_needed"
    assert result.code == "choose_exact_resources"
    bindings.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_duplicate_limit_does_not_attempt_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    actor, body, binding = _fixtures()
    department = binding[1]
    raw_courses = [SimpleNamespace(id=uid(100 + index), title="«QA: можно повторить»") for index in range(21)]
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows(raw_courses), _rows([department])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    monkeypatch.setattr(service, "_bindings", AsyncMock(return_value=binding))

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "clarification_needed" and result.code == "too_many_matches"
    assert db.scalars.await_count == 2


@pytest.mark.asyncio
async def test_legacy_exact_mode_never_attempts_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    actor, _, binding = _fixtures()
    course, department, _, _, _ = binding
    body = AssignmentPreviewRequest(
        instruction='Назначь курс "«QA: можно повторить»" отделу "«Отдел проверки»" до 2026-10-20',
        timezone_name="Asia/Almaty",
    )
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([]), _rows([])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    monkeypatch.setattr(service, "_bindings", AsyncMock(return_value=binding))

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "clarification_needed" and result.code == "resource_not_found"
    assert db.scalars.await_count == 2
    assert course.title not in [choice.label for choice in result.course_choices]


@pytest.mark.asyncio
@pytest.mark.parametrize("course_query", ["«QA: можно повторить'", "««QA: можно повторить»", "«  »"])
async def test_mismatched_nested_or_empty_wrapper_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, course_query: str
) -> None:
    actor, body, binding = _fixtures()
    department = binding[1]
    candidate = body.candidate.model_copy(update={"course_query": course_query})
    body = body.model_copy(update={"candidate": candidate})
    db = SimpleNamespace(
        scalars=AsyncMock(side_effect=[_rows([]), _rows([department])]),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    monkeypatch.setattr(service, "_bindings", AsyncMock(return_value=binding))

    result = await service.create_assignment_preview(db, actor, body, now=NOW)

    assert result.state == "clarification_needed" and result.code == "resource_not_found"
    assert db.scalars.await_count == 2
