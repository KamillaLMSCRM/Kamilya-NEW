"""Database-free contract tests; database isolation needs a separate integration gate."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.knowledge_checks import router
from app.modules.knowledge_checks.schemas import Answer, Answers, Assign, Content, Create, Replace
from app.modules.knowledge_checks.service import digest, grade, normalize_answers, public_snapshot


@pytest.fixture
def content():
    questions = []
    for kind, points in [("MCQ", 2), ("multiple_choice", 3), ("true_false", 5)]:
        questions.append({"id": str(uuid4()), "text": "Question", "type": kind, "points": points,
            "explanation": "secret explanation", "choices": [
                {"id": str(uuid4()), "text": "A", "is_correct": True},
                {"id": str(uuid4()), "text": "B", "is_correct": kind == "multiple_choice"},
                *([{"id": str(uuid4()), "text": "C", "is_correct": False}] if kind == "multiple_choice" else [])]})
    return {"title": "Test", "instructions": "", "pass_score": 50, "attempt_limit": 2,
            "time_limit_minutes": 5, "questions": questions}


def answers_for(content):
    return [Answer(question_id=q["id"], selected_choice_ids=[c["id"] for c in q["choices"] if c["is_correct"]])
            for q in content["questions"]]


def test_oracle_and_public_snapshot(content):
    Content.model_validate(content)
    answers = answers_for(content)
    assert grade(content, normalize_answers(content, answers)) == {
        "earned_points": 10, "total_points": 10, "score_percent": 100, "passed": True}
    assert grade(content, normalize_answers(content, answers[:1])) == {
        "earned_points": 2, "total_points": 10, "score_percent": 20, "passed": False}
    public = public_snapshot(content)
    assert all("explanation" not in q and all("is_correct" not in c for c in q["choices"])
               for q in public["questions"])
    assert "is_correct" in content["questions"][0]["choices"][0]


def test_answer_validation_and_order_independent_replay(content):
    answers = answers_for(content)
    normalized = normalize_answers(content, answers, complete=True)
    assert digest(normalized) == digest(normalize_answers(content, list(reversed(answers)), complete=True))
    for invalid in ([answers[0], answers[0]], [Answer(question_id=uuid4(), selected_choice_ids=[])],
                    [Answer(question_id=answers[0].question_id, selected_choice_ids=[uuid4()])],
                    [Answer(question_id=answers[0].question_id,
                            selected_choice_ids=answers[0].selected_choice_ids * 2)]):
        with pytest.raises(HTTPException) as exc:
            normalize_answers(content, invalid)
        assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        normalize_answers(content, answers[:1], complete=True)


def test_content_rejects_invalid_keys_and_duplicate_ids(content):
    bad = deepcopy(content)
    bad["questions"][0]["choices"][1]["is_correct"] = True
    with pytest.raises(ValidationError):
        Content.model_validate(bad)
    bad = deepcopy(content)
    bad["questions"][1]["choices"][2]["is_correct"] = True
    with pytest.raises(ValidationError):
        Content.model_validate(bad)
    bad = deepcopy(content)
    bad["questions"][2]["id"] = bad["questions"][0]["id"]
    with pytest.raises(ValidationError):
        Content.model_validate(bad)


@pytest.mark.asyncio
async def test_submit_replay_and_expiry_uses_saved_answers(content, monkeypatch):
    now = datetime.now(UTC)
    saved = normalize_answers(content, answers_for(content)[:1])
    attempt = SimpleNamespace(id=uuid4(), assignment_id=uuid4(), number=1, status="started", started_at=now,
        deadline_at=now - timedelta(seconds=1), completed_at=None, score_percent=None, passed=None,
        earned_points=None, total_points=None, answers=saved, snapshot=content, submission_sha256=None)
    getter = AsyncMock(return_value=attempt)
    monkeypatch.setattr(router, "get_attempt", getter)
    db = SimpleNamespace(flush=AsyncMock())
    result = await router.submit(attempt.id, Answers(answers=answers_for(content)), object(), db)
    assert getter.await_args.kwargs["lock"] is True
    assert result["status"] == "expired" and result["score_percent"] == 20
    assert result["answers"] == saved
    replay = await router.submit(attempt.id, Answers(answers=[]), object(), db)
    assert replay["score_percent"] == 20
    assert db.flush.await_count == 1
    assert all("is_correct" not in c for q in replay["snapshot"]["questions"] for c in q["choices"])


@pytest.mark.asyncio
async def test_normal_submit_replay_conflict_and_save_expiry(content, monkeypatch):
    now = datetime.now(UTC)
    attempt = SimpleNamespace(id=uuid4(), assignment_id=uuid4(), number=1, status="started", started_at=now,
        deadline_at=now + timedelta(minutes=1), completed_at=None, score_percent=None, passed=None,
        earned_points=None, total_points=None, answers=[], snapshot=content, submission_sha256=None)
    monkeypatch.setattr(router, "get_attempt", AsyncMock(return_value=attempt))
    db = SimpleNamespace(flush=AsyncMock())
    body = Answers(answers=answers_for(content))
    first = await router.submit(attempt.id, body, object(), db)
    assert first["status"] == "submitted" and first["passed"] is True
    assert (await router.submit(attempt.id, Answers(answers=list(reversed(body.answers))), object(), db))["score_percent"] == 100
    with pytest.raises(HTTPException) as exc:
        await router.submit(attempt.id, Answers(answers=[]), object(), db)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await router.save_answers(attempt.id, body, object(), db)
    assert exc.value.status_code == 409
    attempt.completed_at = None
    attempt.deadline_at = now - timedelta(seconds=1)
    with pytest.raises(HTTPException) as exc:
        await router.save_answers(attempt.id, body, object(), db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_start_reuses_active_even_if_expired_and_locks_assignment(content, monkeypatch):
    now = datetime.now(UTC)
    attempt = SimpleNamespace(id=uuid4(), assignment_id=uuid4(), number=1, status="started", started_at=now,
        deadline_at=now - timedelta(seconds=1), completed_at=None, score_percent=None, passed=None,
        earned_points=None, total_points=None, answers=[], snapshot=content)
    assignment = SimpleNamespace(due_at=now - timedelta(seconds=1), snapshot=content)
    getter = AsyncMock(return_value=assignment)
    monkeypatch.setattr(router, "get_assignment", getter)
    monkeypatch.setattr(router, "assignment_attempts", AsyncMock(return_value=[attempt]))
    result = await router.start(uuid4(), object(), object())
    assert result["id"] == attempt.id
    assert getter.await_args.kwargs["lock"] is True


@pytest.mark.asyncio
async def test_create_replay_after_edit_and_stale_edit(content, monkeypatch):
    now = datetime.now(UTC)
    uid, tid, check_id = uuid4(), uuid4(), uuid4()
    body = Create.model_validate({**content, "id": check_id})
    check = SimpleNamespace(id=check_id, created_by=uid, tenant_id=tid, content={**content, "title": "Edited"},
        create_sha256=digest(body.model_dump(mode="json", exclude={"id"})), revision=2, status="draft",
        created_at=now, updated_at=now)
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=check), flush=AsyncMock())
    user = SimpleNamespace(id=uid, tenant_id=tid)
    assert (await router.create_check(body, user, db))["revision"] == 2
    changed = Create.model_validate({**content, "id": check_id, "title": "Other"})
    with pytest.raises(HTTPException) as exc:
        await router.create_check(changed, user, db)
    assert exc.value.status_code == 409
    monkeypatch.setattr(router, "get_check", AsyncMock(return_value=check))
    with pytest.raises(HTTPException) as exc:
        await router.replace_check(check_id, Replace.model_validate({**content, "expected_revision": 1}), user, db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_mixed_audience_rejects_nonstudent_before_any_insert(content, monkeypatch):
    student_id, nonstudent_id, tenant_id = uuid4(), uuid4(), uuid4()
    check = SimpleNamespace(id=uuid4(), revision=1, status="published", content=content)
    monkeypatch.setattr(router, "get_check", AsyncMock(return_value=check))
    rows = SimpleNamespace(all=lambda: [student_id])
    db = SimpleNamespace(scalars=AsyncMock(return_value=rows), execute=AsyncMock())
    body = Assign(expected_revision=1, user_ids=[student_id, nonstudent_id])
    with pytest.raises(HTTPException) as exc:
        await router.assign(check.id, body, SimpleNamespace(id=uuid4(), tenant_id=tenant_id), db)
    assert exc.value.status_code == 404
    db.execute.assert_not_awaited()
    query = db.scalars.await_args.args[0]
    compiled = query.compile()
    assert "users.role" in str(compiled)
    assert "student" in compiled.params.values()


def test_ordering_knowledge_check_keeps_saved_sequence_and_hides_the_key(content):
    question = content["questions"][0]
    question["type"] = "ordering"
    ids = [str(choice_id) for choice_id in sorted((uuid4() for _ in range(3)), reverse=True)]
    question["choices"] = [
        {"id": choice_id, "text": f"Step {index}", "is_correct": False}
        for index, choice_id in enumerate(ids)
    ]
    Content.model_validate(content)
    rest = answers_for(content)[1:]
    correct = Answer(question_id=question["id"], selected_choice_ids=ids)
    reversed_answer = Answer(question_id=question["id"], selected_choice_ids=ids[::-1])
    completed = normalize_answers(content, [correct, *rest], complete=True)
    reversed_submission = normalize_answers(content, [reversed_answer, *rest], complete=True)
    assert next(answer["selected_choice_ids"] for answer in completed if answer["question_id"] == question["id"]) == ids
    assert digest(completed) != digest(reversed_submission)
    assert grade(content, completed)["score_percent"] == 100
    assert grade(content, reversed_submission)["score_percent"] == 80
    assert [choice["id"] for choice in public_snapshot(content)["questions"][0]["choices"]] == ids[::-1]
    with pytest.raises(HTTPException, match="Include all steps"):
        normalize_answers(content, [Answer(question_id=question["id"], selected_choice_ids=ids[:2]), *rest], complete=True)
