"""A changed question or answer must not retain an old source quotation."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.quizzes import router
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.quizzes.schemas import QuestionResponse, QuestionUpdate, QuizChoiceCreate, QuizChoiceUpdate
from app.modules.quizzes.service import get_quizzes_with_questions


def test_question_quote_survives_orm_database_roundtrip():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.registry import load_all_models

    load_all_models()
    engine = create_engine("sqlite:///:memory:")
    Question.__table__.create(engine)
    with Session(engine) as session:
        session.add(Question(id=uuid4(), quiz_id=uuid4(), text="Synthetic question", type="MCQ",
                             points=1, order_index=0, source_quote="Synthetic quote"))
        session.commit()
        session.expire_all()
        assert session.scalar(select(Question)).source_quote == "Synthetic quote"
    engine.dispose()


def test_question_citation_migration_preserves_public_data_on_downgrade(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0184_question_source_quote.py"
    spec = spec_from_file_location("question_quote_migration_test", path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    executed = []
    monkeypatch.setattr(migration.op, "get_context", lambda: SimpleNamespace(opts={}))
    monkeypatch.setattr(migration.op, "execute", executed.append)
    migration.upgrade()
    assert executed == ['ALTER TABLE "public".questions ADD COLUMN source_quote TEXT']
    with pytest.raises(RuntimeError, match="retained_use_binary_rollback"):
        migration.downgrade()
    assert len(executed) == 1
    monkeypatch.setattr(migration.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "public;drop"}))
    with pytest.raises(ValueError, match="unsafe_schema"):
        migration.upgrade()
    assert len(executed) == 1


def test_release_question_snapshot_keeps_citation():
    from app.modules.courses.release_service import _question_snapshot_payload

    question = SimpleNamespace(id=uuid4(), text="q", type="MCQ", points=1, explanation="e", order_index=0,
                               pool_group=None, source_quote="Точная цитата")
    payload = _question_snapshot_payload(question, [])
    assert payload["source_quote"] == "Точная цитата"
    question.source_quote = None
    assert payload["source_quote"] == "Точная цитата"


def test_release_snapshot_of_legacy_question_keeps_its_existing_shape():
    from app.modules.courses.release_service import _question_snapshot_payload

    question = SimpleNamespace(id=uuid4(), text="q", type="MCQ", points=1, explanation="e", order_index=0,
                               pool_group=None, source_quote=None)
    assert "source_quote" not in _question_snapshot_payload(question, [])


def test_question_api_response_includes_saved_citation():
    question = SimpleNamespace(id=uuid4(), text="q", type="MCQ", points=1, explanation="e", order_index=0,
                               choices=[], source_quote="Точная цитата")
    assert QuestionResponse.model_validate(question).source_quote == "Точная цитата"


def test_learner_like_approval_snapshot_does_not_expose_answer_bearing_citation():
    from app.modules.course_approval.service import learner_safe_review_snapshot

    snapshot = {"modules": [{"questions": [{"text": "q", "source_quote": "correct answer"}]}]}
    safe = learner_safe_review_snapshot(snapshot)
    assert "source_quote" not in safe["modules"][0]["questions"][0]
    assert snapshot["modules"][0]["questions"][0]["source_quote"] == "correct answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("authoring", [False, True])
async def test_quiz_source_quote_follows_explanation_visibility(authoring):
    tenant, quiz_id, question_id = uuid4(), uuid4(), uuid4()
    quiz = SimpleNamespace(id=quiz_id, lesson_id=uuid4(), title="q", pass_score=80, time_limit=None,
                           attempt_limit=3, deferral_days=7, review_status="approved")
    question = SimpleNamespace(id=question_id, quiz_id=quiz_id, text="q", type="MCQ", points=1,
                               explanation="answer", source_quote="Answer-bearing source", order_index=0)
    choice = SimpleNamespace(id=uuid4(), question_id=question_id, text="answer", order_index=0, is_correct=True)

    class Result:
        def __init__(self, data): self.data = data
        def scalars(self): return self
        def all(self): return self.data

    class Session:
        def __init__(self): self.data = iter(([quiz], [question], [choice]))
        async def execute(self, statement): return Result(next(self.data))

    result = await get_quizzes_with_questions(Session(), [quiz_id], tenant,
                                              include_correct_answers=authoring, include_explanations=authoring)
    assert result[0]["questions"][0]["source_quote"] == ("Answer-bearing source" if authoring else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["question", "create", "update", "delete"])
async def test_content_changes_invalidate_saved_citation(monkeypatch, operation):
    tenant, quiz_id, question_id, choice_id = (uuid4() for _ in range(4))
    quiz = SimpleNamespace(tenant_id=tenant, lesson_id=uuid4())
    question = SimpleNamespace(quiz_id=quiz_id, source_quote="Исходная цитата")
    choice = SimpleNamespace(question_id=question_id, text="old", is_correct=False, order_index=0)

    class Session:
        async def get(self, model, key):
            return {Quiz: quiz, Question: question, QuizChoice: choice}.get(model)

        def add(self, value):
            pass

        flush = AsyncMock()
        delete = AsyncMock()

    session = Session()
    monkeypatch.setattr(router, "_ensure_quiz_has_no_attempts", AsyncMock())
    monkeypatch.setattr(router, "touch_course_by_lesson", AsyncMock())
    monkeypatch.setattr(router, "get_quiz_with_questions", AsyncMock(return_value={}))
    user = SimpleNamespace(tenant_id=tenant)
    if operation == "question":
        await router.update_question(quiz_id, question_id, QuestionUpdate(text="changed"), session, user)
    elif operation == "create":
        await router.create_choice(quiz_id, question_id, QuizChoiceCreate(text="new"), session, user)
    elif operation == "update":
        await router.update_choice(quiz_id, question_id, choice_id, QuizChoiceUpdate(text="new"), session, user)
    else:
        await router.delete_choice(quiz_id, question_id, choice_id, session, user)
    assert question.source_quote is None
