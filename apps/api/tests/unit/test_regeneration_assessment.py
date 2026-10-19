"""Regeneration must use adaptive, reviewed lesson-snapshot targets, not three questions."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.ai.evidence_engine import semantic_assessment
from app.modules.ai.evidence_engine.models import QuestionDraft
from app.modules.ai.regeneration_assessment import prepare_lesson_assessment


def lesson_snapshot(content):
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), title="Выдача оборудования",
                           content=content, source_validation_status="verified",
                           source_document_ids=[uuid4()])


def complete_audit():
    return {"terminal_status": "completed",
            "coverage": {"audit_incomplete": False, "requires_review": False},
            "contract_coverage": {"audit_incomplete": False, "omitted_contract_count": 0,
                                  "uncovered_contract_count": 0, "unassessable_source_count": 0}}


@pytest.mark.asyncio
async def test_regeneration_preserves_five_independent_targets_and_tail(monkeypatch):
    navigation = "# Содержание\n\n" + "Справочная навигационная строка материала.\n" * 85
    assert len(navigation) > 3000
    text = navigation + "\n\n# Рабочие правила\n\n" + "\n\n".join([
        "Перед выдачей сотрудник обязан проверить исправность оборудования.",
        "При повреждении сотрудник обязан остановить выдачу оборудования.",
        "О неисправности сотрудник обязан сообщить руководителю смены.",
        "До передачи сотрудник обязан проверить комплектность оборудования.",
        "После возврата сотрудник обязан оформить запись в журнале.",
    ])
    lesson = lesson_snapshot(text)
    captured = []

    async def reviewed(lessons, facts, client):
        captured.extend(facts.values())
        assert len(lessons) == 1 and lessons[0].lesson_id == str(lesson.id)
        assert len(facts) == 5
        questions = tuple(QuestionDraft(
            question_id=f"q-{i}", lesson_id=str(lesson.id), kind="single_choice",
            prompt=f"Какое действие требуется в ситуации {i}?",
            options=(f.value, "Не выполнять требование.", "Выполнить другое действие."),
            correct_answer=f.value, explanation=f.value, fact_id=f.fact_id,
            semantic_reviewed=True,
        ) for i, f in enumerate(facts.values()))
        return SimpleNamespace(questions=questions, audit=complete_audit())

    monkeypatch.setattr(semantic_assessment, "generate_block_assessment", reviewed)
    result = await prepare_lesson_assessment(lesson=lesson, client=object())
    assert len(result) == 5
    assert "После возврата" in captured[-1].value
    assert text.index("После возврата") > 3000
    assert all(q["choices"][q["correct_index"]] for q in result)
    assert lesson.content == text


@pytest.mark.asyncio
async def test_incomplete_adaptive_regeneration_fails_without_replacement(monkeypatch):
    async def incomplete(*args, **kwargs):
        return SimpleNamespace(questions=(), audit={"coverage": {"audit_incomplete": True}})

    monkeypatch.setattr(semantic_assessment, "generate_block_assessment", incomplete)
    lesson = lesson_snapshot("При повреждении сотрудник обязан остановить выдачу оборудования.")
    with pytest.raises(ValueError, match="покры"):
        await prepare_lesson_assessment(lesson=lesson, client=object())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["critical_missing", "omitted", "uncovered", "unsupported", "missing_terminal"])
async def test_nonempty_review_required_result_never_replaces_old_quiz(monkeypatch, failure):
    audit = complete_audit()
    if failure == "critical_missing":
        audit["coverage"].update(requires_review=True, critical_missing_axis_ids=["missing-axis"])
        audit["terminal_status"] = "review_required"
    elif failure == "missing_terminal":
        del audit["terminal_status"]
    else:
        key = {"omitted": "omitted_contract_count", "uncovered": "uncovered_contract_count",
               "unsupported": "unassessable_source_count"}[failure]
        audit["contract_coverage"][key] = 1

    async def reviewed(*args, **kwargs):
        return SimpleNamespace(questions=(object(),), audit=audit)

    monkeypatch.setattr(semantic_assessment, "generate_block_assessment", reviewed)
    lesson = lesson_snapshot("При повреждении сотрудник обязан остановить выдачу оборудования.")
    with pytest.raises(ValueError, match="покры"):
        await prepare_lesson_assessment(lesson=lesson, client=object())


@pytest.mark.asyncio
async def test_unverified_lesson_never_becomes_an_approved_source(monkeypatch):
    lesson = lesson_snapshot("Перед выдачей проверьте оборудование.")
    lesson.source_validation_status = "review_required"
    with pytest.raises(ValueError, match="источ"):
        await prepare_lesson_assessment(lesson=lesson, client=object())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,mode", [
    (kind, mode) for kind in ("lesson", "module")
    for mode in ("complete", "coverage_failed", "has_attempts", "unchecked")
    if kind == "lesson" or mode != "unchecked"
])
async def test_legacy_job_replaces_only_reviewed_unused_quiz(monkeypatch, kind, mode):
    from fastapi import HTTPException

    from app.modules.ai import regeneration_assessment, router
    from app.modules.quizzes import router as quizzes_router
    from app.modules.quizzes.models import Question, Quiz, QuizChoice

    lesson = lesson_snapshot("Перед выдачей проверьте оборудование.")
    lesson.module_id = uuid4()
    lesson.description = ""
    lesson.duration_seconds = 600
    module = SimpleNamespace(id=lesson.module_id, course_id=uuid4(), title="Модуль", description="")
    old_quiz = SimpleNamespace(id=uuid4())
    db = MagicMock()
    module.tenant_id = lesson.tenant_id
    bound = False
    objects = iter([lesson, module] if kind == "lesson" else [module])

    async def get(*args):
        assert bound, "regeneration content reads require a tenant-bound transaction"
        return next(objects)

    db.get = AsyncMock(side_effect=get)
    rows = [SimpleNamespace(scalar_one=lambda: SimpleNamespace(id=module.course_id, title="Курс"))]
    if kind == "module":
        rows.append(SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [lesson])))
    rows.append(SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [old_quiz])))
    results = iter(rows)

    async def execute(statement, parameters=None):
        nonlocal bound
        if str(statement).startswith("SELECT set_current_tenant"):
            assert parameters == {"tid": str(lesson.tenant_id)}
            bound = True
            return None
        assert bound
        return next(results)

    db.execute = AsyncMock(side_effect=execute)
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: context)
    monkeypatch.setattr(router, "_set_regeneration_job_state", AsyncMock(return_value=True))
    monkeypatch.setattr(router, "_rewrite_grounded_lesson", AsyncMock())
    finish = AsyncMock(return_value=True)
    monkeypatch.setattr(router, "_finish_regeneration_job", finish)
    client = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="{}")))
    monkeypatch.setattr(router.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=client))
    questions = [{"text": f"Ситуация {i}?", "choices": [f"Верно {i}", "Ошибка 1", "Ошибка 2"],
                  "correct_index": 0, "explanation": "Правило источника."} for i in range(5)]
    prepare = AsyncMock(return_value=questions)
    if mode == "coverage_failed":
        prepare.side_effect = ValueError("Тест не покрывает правила.")
    monkeypatch.setattr(regeneration_assessment, "prepare_lesson_assessment", prepare)
    guard = AsyncMock()
    if mode == "has_attempts":
        guard.side_effect = HTTPException(status_code=409, detail="Есть результаты.")
    monkeypatch.setattr(quizzes_router, "_ensure_quiz_has_no_attempts", guard)
    invocation = (router._regenerate_lesson_job("owned-job", lesson.id, "", mode != "unchecked",
                                               lesson.tenant_id, uuid4()) if kind == "lesson" else
                  router._regenerate_module_job("owned-job", module.id, "", "ru", lesson.tenant_id, uuid4()))
    if mode in {"coverage_failed", "has_attempts"}:
        with pytest.raises((ValueError, HTTPException)):
            await invocation
        db.delete.assert_not_awaited()
        db.rollback.assert_awaited_once()
        finish.assert_not_awaited()
    else:
        assert (await invocation)["status"] == "completed"
        if mode == "unchecked":
            prepare.assert_not_awaited()
            db.delete.assert_not_awaited()
        else:
            guard.assert_awaited_once_with(db, old_quiz.id, lesson.tenant_id)
            db.delete.assert_awaited_once_with(old_quiz)
            added = [call.args[0] for call in db.add.call_args_list]
            quizzes = [row for row in added if isinstance(row, Quiz)]
            assert len(quizzes) == 1 and quizzes[0].review_status == "needs_review"
            assert len([row for row in added if isinstance(row, Question)]) == 5
            assert sum(row.is_correct for row in added if isinstance(row, QuizChoice)) == 5
