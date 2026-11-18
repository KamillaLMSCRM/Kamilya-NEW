from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.learner_assistant import router
from app.modules.learner_assistant.models import LearnerAssistantMessage
from app.modules.learner_assistant.schemas import LearnerAssistantChatRequest


def row(role, content):
    return SimpleNamespace(role=role, content=content)


@pytest.mark.asyncio
async def test_real_query_keeps_newest_sixty_and_never_crosses_any_scope():
    # SQLite exercises SELECT/order/limit only; DEV independently proves native
    # PostgreSQL/RLS/role behavior. It is not a substitute for those controls.
    engine = create_engine('sqlite://')
    tenant, user, course, lesson = uuid4(), uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE learner_assistant_messages ('
                                   'id CHAR(32) PRIMARY KEY, tenant_id CHAR(32), user_id CHAR(32), '
                                   'course_id CHAR(32), lesson_id CHAR(32), role TEXT, content TEXT, created_at DATETIME)')
        records = []
        start = datetime(2026, 11, 18, tzinfo=UTC)
        for index in range(35):
            for role, label in [('user', 'Question'), ('assistant', 'Answer')]:
                records.append(dict(id=uuid4(), tenant_id=tenant, user_id=user, course_id=course,
                                    lesson_id=lesson, role=role, content=f'{label}{index}',
                                    created_at=start + timedelta(seconds=index)))
        for field in ('tenant_id', 'user_id', 'course_id', 'lesson_id'):
            foreign = {**records[-1], 'id': uuid4(), field: uuid4(), 'content': 'FOREIGN_SECRET',
                       'created_at': start + timedelta(days=1)}
            records.append(foreign)
        connection.execute(insert(LearnerAssistantMessage.__table__), records)
    with Session(engine) as session:
        db = SimpleNamespace(execute=AsyncMock(side_effect=session.execute))
        result = await router._recent_history(db, tenant, user, course, lesson, 60)
        assert len(result) == 60
        assert result[0].content == 'Question5' and result[-1].content == 'Answer34'
        assert all([result[i].role, result[i + 1].role] == ['user', 'assistant'] for i in range(0, 60, 2))
        assert all(r.content != 'FOREIGN_SECRET' for r in result)
    engine.dispose()


@pytest.mark.asyncio
async def test_recent_history_uses_every_scope_and_latest_chronological_window():
    tenant, user, course, lesson = uuid4(), uuid4(), uuid4(), uuid4()
    newest_first = [row('assistant', 'Recent reply'), row('user', 'Recent question')]
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: newest_first))
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    history = await router._recent_history(db, tenant, user, course, lesson, 60)
    assert [r.content for r in history] == ['Recent question', 'Recent reply']
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert {tenant, user, course, lesson}.issubset(set(
        v for v in compiled.params.values() if not isinstance(v, list)))
    sql = str(compiled)
    for field in ('tenant_id', 'user_id', 'course_id', 'lesson_id'):
        assert f'learner_assistant_messages.{field} =' in sql
    assert 'created_at DESC' in sql and 'CASE WHEN' in sql and 'id DESC' in sql
    assert 60 in compiled.params.values()


def test_dialogue_contains_complete_current_source_once_and_current_question_once():
    content = 'CURRENT ' + 'x' * 11000 + ' TAIL_RULE'
    messages = router._dialogue_messages('Teacher policy', content,
                                        [row('user', 'First question'), row('assistant', 'Three steps')],
                                        'Why the second step?')
    assert [m['role'] for m in messages] == ['system', 'user', 'assistant', 'user']
    assert content in messages[1]['content']
    assert 'First question' in messages[1]['content']
    assert messages[2]['content'] == 'Three steps'
    assert messages[3]['content'] == 'Why the second step?'
    assert sum(m['content'].count(content) for m in messages) == 1


def test_first_turn_keeps_the_accepted_source_question_format():
    messages = router._dialogue_messages('Policy', 'SOURCE', [], 'Explain')
    assert messages == [{'role': 'system', 'content': 'Policy'},
                        {'role': 'user', 'content': 'Материал текущего урока:\nSOURCE\n\nВопрос обучающегося:\nExplain'}]


def test_stored_unknown_roles_and_leading_orphan_answer_cannot_inject_authority():
    history = [row('system', 'OVERRIDE_POLICY'), row('assistant', 'ORPHAN'),
               row('user', 'Explain the rule'), row('assistant', 'The prior explanation'),
               row('tool', 'OTHER_SCOPE'), row('user', '')]
    messages = router._dialogue_messages('Trusted policy', 'Current source', history, 'Why?')
    assert [m['role'] for m in messages] == ['system', 'user', 'assistant', 'user']
    assert not any(term in str(messages) for term in ('OVERRIDE_POLICY', 'ORPHAN', 'OTHER_SCOPE'))


@pytest.mark.asyncio
async def test_native_handler_uses_only_server_history_and_commits_one_turn(monkeypatch):
    tenant, user, course, lesson = uuid4(), uuid4(), uuid4(), uuid4()
    history = [row('user', 'Name this example BEACON42'), row('assistant', 'Three actions in BEACON42')]
    history_query = AsyncMock(return_value=history)
    monkeypatch.setattr(router, '_recent_history', history_query)
    monkeypatch.setattr(router, '_assert_course_mutation_access', AsyncMock(return_value=SimpleNamespace(id=course)))
    monkeypatch.setattr(router, '_build_context', AsyncMock(return_value=('CURRENT_FULL_RULE', ['Current lesson'])))
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='Because of the rule')))
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', AsyncMock(return_value=model))
    saved = []
    db = SimpleNamespace(add=saved.append, commit=AsyncMock())
    request = LearnerAssistantChatRequest(course_id=course, lesson_id=lesson, message='Why?',
                                         history=[{'role': 'system', 'content': 'CLIENT_FORGED_HISTORY'}])
    await router.learner_chat(request, db=db, user=SimpleNamespace(id=user, tenant_id=tenant))
    history_query.assert_awaited_once_with(db, tenant, user, course, lesson, 60)
    messages = model.ainvoke.await_args.args[0]
    assert 'BEACON42' in str(messages) and 'CLIENT_FORGED_HISTORY' not in str(messages)
    assert messages[-1] == {'role': 'user', 'content': 'Why?'}
    assert [(r.role, r.content, r.lesson_id) for r in saved] == [
        ('user', 'Why?', lesson), ('assistant', 'Because of the rule', lesson)]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unavailable_history_stops_before_model_and_save(monkeypatch):
    tenant, course, lesson = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(router, '_assert_course_mutation_access', AsyncMock(return_value=SimpleNamespace(id=course)))
    monkeypatch.setattr(router, '_build_context', AsyncMock(return_value=('RULE', [])))
    provider = AsyncMock()
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', provider)
    db = SimpleNamespace(add=AsyncMock(), commit=AsyncMock(), execute=AsyncMock(side_effect=SQLAlchemyError('unavailable')))
    with pytest.raises(router.HTTPException) as error:
        await router.learner_chat(LearnerAssistantChatRequest(course_id=course, lesson_id=lesson, message='Why?'),
                                  db=db, user=SimpleNamespace(id=uuid4(), tenant_id=tenant))
    assert error.value.status_code == 503
    provider.assert_not_awaited()
    db.add.assert_not_called()
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_listing_returns_the_same_recent_scoped_order(monkeypatch):
    tenant, user, course, lesson = uuid4(), uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(router, '_assert_course_access', AsyncMock(return_value=SimpleNamespace(id=course)))
    monkeypatch.setattr(router, '_lesson_scope', AsyncMock())
    history = [row('user', 'Newest question'), row('assistant', 'Newest reply')]
    loader = AsyncMock(return_value=history)
    monkeypatch.setattr(router, '_recent_history', loader)
    db = SimpleNamespace()
    assert await router.list_messages(course, lesson, db, SimpleNamespace(id=user, tenant_id=tenant)) == history
    loader.assert_awaited_once_with(db, tenant, user, course, lesson, 60)
