from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai import lesson_dialogue as owner
from app.modules.ai.schemas import AIChatRequest, AIChatResponse

COURSE = UUID('11111111-1111-4111-8111-111111111111')
TENANT = UUID('22222222-2222-4222-8222-222222222222')
LESSON = UUID('33333333-3333-4333-8333-333333333333')
ACTOR = UUID('44444444-4444-4444-8444-444444444444')
KEY = UUID('55555555-5555-4555-8555-555555555555')


def request(**overrides):
    return AIChatRequest.model_validate(dict(course_id=COURSE, context='lesson',
        target_id=LESSON, message='Сделай этот вариант проще', language='ru',
        durable_request_id=KEY) | overrides)


@pytest.mark.parametrize('change', [{'context': 'course'}, {'target_id': None},
    {'intent': 'audience_recommendation'}, {'history': dict(version=1, course_id=COURSE,
        context='lesson', target_id=LESSON, language='ru', turns=[{'role': 'user', 'content': 'x'}, {'role': 'assistant', 'content': 'y'}])}])
def test_durable_rejects_client_history_and_wrong_scope(change):
    with pytest.raises(ValidationError):
        request(**change)


def test_recall_excludes_refusals_and_keeps_whole_bounded_pairs():
    rows = [SimpleNamespace(message=f'question{i}', response=AIChatResponse(
        reply=f'answer{i}', history_eligible=i != 9).model_dump()) for i in range(10)]
    context = owner.admitted_history(rows, request())
    assert [turn.content for turn in context.turns][::2] == ['question5','question6','question7','question8']
    huge = [SimpleNamespace(message='u'*2000, response=AIChatResponse(reply='a'*12000,
        apply_lesson_id=LESSON, apply_lesson_content='b'*12000).model_dump()) for _ in range(4)]
    context = owner.admitted_history(huge, request())
    assert len(context.turns) == 2
    assert 'unverified, not an execution receipt' in context.turns[1].content
    assert owner.admitted_history([rows[-1]], request()) is None


def test_fingerprint_covers_semantic_payload_not_key():
    assert owner.fingerprint(request()) != owner.fingerprint(request(message='Другой вопрос'))
    assert owner.fingerprint(request()) == owner.fingerprint(request(durable_request_id=ACTOR))


class FakeDB:
    def __init__(self, existing=None, rows=()):
        self.existing = existing
        self.rows = rows
        self.commits = 0
        self.added = None
        self.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
        self.rollback = AsyncMock()

    async def scalar(self, statement):
        return self.existing

    async def scalars(self, statement):
        return SimpleNamespace(all=lambda: list(self.rows))

    def add(self, row):
        self.added = row

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_replay_returns_original_without_provider_or_writes(monkeypatch):
    monkeypatch.setattr(owner, 'authorize_lesson', AsyncMock())
    generate = AsyncMock()
    original = AIChatResponse(reply='Оригинал', apply_lesson_id=LESSON, apply_lesson_content='Предложение')
    db = FakeDB(SimpleNamespace(fingerprint=owner.fingerprint(request()), state='completed', response=original.model_dump()))
    result = await owner.send_durable(request(), db, SimpleNamespace(id=ACTOR, tenant_id=TENANT), generate)
    assert result == original
    generate.assert_not_awaited()
    db.execute.assert_not_awaited()
    assert db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('state,digest,status', [('completed','bad',409),('pending',None,409),('failed',None,503)])
async def test_existing_conflict_or_unknown_never_reinvokes(monkeypatch, state, digest, status):
    monkeypatch.setattr(owner, 'authorize_lesson', AsyncMock())
    generate = AsyncMock()
    db = FakeDB(SimpleNamespace(fingerprint=digest or owner.fingerprint(request()), state=state, created_at=datetime.now(UTC)))
    with pytest.raises(HTTPException) as error:
        await owner.send_durable(request(), db, SimpleNamespace(id=ACTOR, tenant_id=TENANT), generate)
    assert error.value.status_code == status
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_reservation_committed_and_context_rebound_before_ack(monkeypatch):
    authorize = AsyncMock()
    monkeypatch.setattr(owner, 'authorize_lesson', authorize)
    context = AsyncMock()
    monkeypatch.setattr(owner, '_context', context)
    prior = SimpleNamespace(message='Предложи пример', response=AIChatResponse(reply='Предлагаю проверку накладной').model_dump())
    db = FakeDB(rows=[prior])

    async def generate(req):
        assert db.commits == 1 and context.await_count == 1
        assert req.durable_request_id is None and req.history.turns[1].content == 'Предлагаю проверку накладной'
        return AIChatResponse(reply='Теперь проще.')

    result = await owner.send_durable(request(), db, SimpleNamespace(id=ACTOR, tenant_id=TENANT), generate)
    assert result.reply == 'Теперь проще.' and db.commits == 2 and context.await_count == 1
    assert authorize.await_count == 2 and authorize.call_args.kwargs == {'lock': True}
    assert db.added.tenant_id == TENANT and db.added.actor_id == ACTOR


@pytest.mark.asyncio
async def test_provider_failure_closes_reserved_key_without_hidden_retry(monkeypatch):
    monkeypatch.setattr(owner, 'authorize_lesson', AsyncMock())
    monkeypatch.setattr(owner, '_context', AsyncMock())
    db = FakeDB()
    generate = AsyncMock(side_effect=HTTPException(502, 'Unavailable'))
    with pytest.raises(HTTPException):
        await owner.send_durable(request(), db, SimpleNamespace(id=ACTOR, tenant_id=TENANT), generate)
    assert generate.await_count == 1 and db.commits == 2
    assert db.execute.call_args.args[0].compile().params['error_code'] == 'provider_unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['student','admin','superadmin'])
async def test_active_role_refused_before_scope_query(role):
    db = FakeDB()
    with pytest.raises(HTTPException) as error:
        await owner.authorize_lesson(db, SimpleNamespace(role=role, tenant_id=TENANT), COURSE, LESSON)
    assert error.value.status_code == 403


def test_purge_lists_archive_before_lesson_owner():
    from app.modules.admin.superadmin.service import TENANT_DELETE_SQL
    assert TENANT_DELETE_SQL.index('DELETE FROM ai_lesson_dialogue_exchanges WHERE tenant_id = :tenant_id') < TENANT_DELETE_SQL.index('DELETE FROM lessons WHERE tenant_id = :tenant_id')


def test_migration_checks_context_before_scoped_owner_lookup():
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / 'alembic/versions/0179_ai_lesson_dialogue.py'
    source = path.read_text(encoding='utf-8')
    assert source.index("dialogue_context_required") < source.index("SELECT 1 FROM {s}.lessons")
    assert "dialogue_context_required' USING ERRCODE='42501'" in source


@pytest.mark.asyncio
async def test_authorized_read_rebinds_context_after_a_previous_commit(monkeypatch):
    context = AsyncMock()
    monkeypatch.setattr(owner, '_context', context)
    db = SimpleNamespace(scalar=AsyncMock(return_value=LESSON))
    user = SimpleNamespace(id=ACTOR, tenant_id=TENANT, role='methodologist')
    await owner.authorize_lesson(db, user, COURSE, LESSON)
    context.assert_awaited_once_with(db, user)
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_ownership_move_during_inference_closes_pending_without_archiving(monkeypatch):
    authorize = AsyncMock(side_effect=[None, HTTPException(404, 'Lesson not found')])
    monkeypatch.setattr(owner, 'authorize_lesson', authorize)
    monkeypatch.setattr(owner, '_context', AsyncMock())
    db = FakeDB()
    generate = AsyncMock(return_value=AIChatResponse(reply='Old scoped answer'))
    with pytest.raises(HTTPException) as error:
        await owner.send_durable(request(), db, SimpleNamespace(id=ACTOR, tenant_id=TENANT), generate)
    assert error.value.status_code == 404 and generate.await_count == 1
    params = db.execute.call_args.args[0].compile().params
    assert params['state'] == 'failed' and params['error_code'] == 'interrupted' and 'response' not in params


@pytest.mark.asyncio
async def test_durable_missing_focus_fails_before_model(monkeypatch):
    from app.modules.ai import router
    monkeypatch.setattr(router, '_fetch_course_summary', AsyncMock(return_value='Current course'))
    monkeypatch.setattr(router, '_fetch_target_context', AsyncMock(return_value=''))
    factory = AsyncMock()
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', factory)
    with pytest.raises(HTTPException) as error:
        await router._chat_once(request(durable_request_id=None), FakeDB(),
            SimpleNamespace(id=ACTOR, tenant_id=TENANT, role='methodologist'), release_reads=True)
    assert error.value.status_code == 404
    factory.assert_not_awaited()
