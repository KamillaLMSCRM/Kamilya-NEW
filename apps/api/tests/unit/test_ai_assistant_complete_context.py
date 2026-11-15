from __future__ import annotations

import json
from types import SimpleNamespace as Row
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import assistant_context as context
from app.modules.ai import router
from app.modules.ai.schemas import AIChatRequest
from app.modules.source_editorial_review.domain import SOURCE_PINS, ReviewConflictError


class DB:
    def __init__(self, course, *groups):
        self.course, self.groups, self.statements = course, iter(groups), []

    async def scalar(self, statement):
        self.statements.append(str(statement))
        return self.course

    async def scalars(self, statement):
        self.statements.append(str(statement))
        return Row(all=lambda: next(self.groups))


def rows():
    tenant, course, module, lesson, quiz, question, document = [uuid4() for _ in range(7)]
    return Row(tenant=tenant,
        course=Row(id=course, title='Course', description='Description', status='draft', review_status='pending',
            source_document_ids=[str(document)], source_instruction_id=None, source_analysis={SOURCE_PINS: ['pinned']}),
        module=Row(id=module, title='Module'),
        lesson=Row(id=lesson, module_id=module, title='Lesson', content_type='text',
            content='начало ' * 1000 + 'LATE_LESSON_CONDITION', duration_seconds=60,
            source_references=[{'doc_id': str(document)}]),
        quiz=Row(id=quiz, lesson_id=lesson, title='Quiz', review_status='pending'),
        question=Row(id=question, quiz_id=quiz, text='Which action?', type='MCQ',
            explanation='UNVERIFIED_EXPLANATION', source_quote='CLAIMED_QUOTE'),
        choices=[Row(id=uuid4(), question_id=question, text='WRONG_AUTHORED_KEY', is_correct=True),
                 Row(id=uuid4(), question_id=question, text='ACTUAL_SOURCE_ACTION', is_correct=False)],
        document=Row(id=document, title='Source'),
        approved=Row(approval_id=str(uuid4()), source_revision='document:'+'a'*64,
            working_sha256='b'*64, working_text='SOURCE_BEGIN ' + 'правило ' * 2000 + 'SOURCE_TAIL_CONDITION'))


@pytest.mark.asyncio
async def test_complete_course_sources_and_quiz_are_sent_without_clipping(monkeypatch):
    r = rows()
    resolve = AsyncMock(return_value={str(r.document.id): r.approved})
    monkeypatch.setattr('app.modules.source_editorial_review.service.resolve_pins', resolve)
    db = DB(r.course, [r.module], [r.lesson], [r.quiz], [r.question], r.choices, [r.document])
    raw = await context.load_course_context(db, r.course.id, r.tenant)
    body = json.loads(raw)
    lesson = body['modules'][0]['lessons'][0]
    assert lesson['text'] == r.lesson.content
    assert body['sources']['documents'][0]['text'] == r.approved.working_text
    assert body['sources']['documents'][0]['approval_id'] == r.approved.approval_id
    question = lesson['quizzes'][0]['questions'][0]
    assert question['explanation'] == 'UNVERIFIED_EXPLANATION'
    assert body['quote_texts'][question['source_quote']['quote_ref']] == 'CLAIMED_QUOTE'
    assert [(c['text'], c['is_correct']) for c in question['choices']] == [
        ('WRONG_AUTHORED_KEY', True), ('ACTUAL_SOURCE_ACTION', False)]
    resolve.assert_awaited_once_with(db, r.tenant, [str(r.document.id)], ['pinned'])
    # Queries for descendants each retain the tenant owner; question/choice
    # rows inherit ownership through the tenant-filtered quiz join.
    assert all('tenant_id' in statement for statement in db.statements)


@pytest.mark.asyncio
async def test_missing_course_never_reads_descendants_or_sources():
    db = DB(None)
    assert await context.load_course_context(db, uuid4(), uuid4()) == ''
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_real_chat_path_delivers_complete_source_and_authored_key_to_model(monkeypatch):
    r = rows()
    monkeypatch.setattr('app.modules.source_editorial_review.service.resolve_pins',
        AsyncMock(return_value={str(r.document.id): r.approved}))
    db = DB(r.course, [r.module], [r.lesson], [r.quiz], [r.question], r.choices, [r.document])
    captured = {}
    async def invoke(messages):
        captured['messages'] = messages
        return Row(content='Проверьте ключ вопроса по источнику.')
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async',
        AsyncMock(return_value=Row(ainvoke=invoke)))
    await router.chat(AIChatRequest(course_id=r.course.id, message='Проверь курс'),
        db=db, user=Row(tenant_id=r.tenant, role='methodologist'))
    body = captured['messages'][1]['content']
    assert 'SOURCE_TAIL_CONDITION' in body and 'LATE_LESSON_CONDITION' in body
    assert 'WRONG_AUTHORED_KEY' in body and 'ACTUAL_SOURCE_ACTION' in body
    assert 'UNVERIFIED_EXPLANATION' in body


@pytest.mark.asyncio
async def test_refusal_ownership_check_reads_no_content():
    r = rows()
    db = DB(r.course)
    assert await context.load_course_context(db, r.course.id, r.tenant, include_sources=False) == 'Course'
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_foreign_or_deleted_source_never_resolves_pins(monkeypatch):
    r = rows()
    resolve = AsyncMock(side_effect=AssertionError('must not access foreign source'))
    monkeypatch.setattr('app.modules.source_editorial_review.service.resolve_pins', resolve)
    result = await context.source_context(DB(r.course, []), r.course, r.tenant)
    assert result == {'status': 'unavailable', 'reason': 'linked_source_unavailable', 'documents': []}
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_pin_never_falls_back_to_latest_blob(monkeypatch):
    r = rows()
    monkeypatch.setattr('app.modules.source_editorial_review.service.resolve_pins',
        AsyncMock(side_effect=ReviewConflictError('source_review_snapshot_mismatch')))
    result = await context.source_context(DB(r.course, [r.document]), r.course, r.tenant)
    assert result == {'status': 'unavailable', 'reason': 'pinned_source_unavailable', 'documents': []}


@pytest.mark.asyncio
async def test_legacy_source_is_explicitly_unverified_not_reconverted():
    r = rows()
    r.course.source_analysis = {}
    result = await context.source_context(DB(r.course, [r.document]), r.course, r.tenant)
    assert result['reason'] == 'source_edition_not_pinned'
    assert result['documents'] == []


@pytest.mark.asyncio
async def test_full_selected_lesson_tail_reaches_provider(monkeypatch):
    r = rows()
    monkeypatch.setattr(router, '_fetch_course_summary', AsyncMock(return_value='{"sources":{"status":"complete"}}'))
    # Exercise the real focus builder, not a mocked/truncated target block.
    db = Row(get=AsyncMock(side_effect=[Row(**vars(r.lesson), tenant_id=r.tenant),
                                      Row(**vars(r.module), tenant_id=r.tenant, course_id=r.course.id)]))
    captured = {}
    async def invoke(messages):
        captured['messages'] = messages
        return Row(content='LATE_LESSON_CONDITION is retained.')
    factory = AsyncMock(return_value=Row(ainvoke=invoke))
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', factory)
    await router.chat(AIChatRequest(course_id=r.course.id, context='lesson', target_id=r.lesson.id,
        message='Проверь весь урок'), db=db, user=Row(tenant_id=r.tenant, role='methodologist'))
    assert 'LATE_LESSON_CONDITION' in captured['messages'][1]['content']
    assert factory.call_args.kwargs['max_tokens'] == 32768


@pytest.mark.asyncio
async def test_module_focus_does_not_retain_its_old_separate_clip():
    r = rows()
    db = Row(get=AsyncMock(return_value=Row(**vars(r.module), description='', tenant_id=r.tenant, course_id=r.course.id)),
        execute=AsyncMock(return_value=Row(scalars=lambda: Row(all=lambda: [r.lesson]))))
    result = await router._fetch_target_context(db, r.course.id, 'module', r.module.id, r.tenant)
    assert r.lesson.content in result


@pytest.mark.asyncio
async def test_unavailable_source_cannot_be_reported_as_full_source_review(monkeypatch):
    r = rows()
    monkeypatch.setattr(router, '_fetch_course_summary', AsyncMock(return_value='{"sources":{"status":"unavailable"}}'))
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async',
        AsyncMock(return_value=Row(ainvoke=AsyncMock(return_value=Row(content='Материал проверен.')))))
    response = await router.chat(AIChatRequest(course_id=r.course.id, message='Проверь'),
        db=object(), user=Row(tenant_id=r.tenant, role='methodologist'))
    assert response.reply.startswith('Исходная редакция недоступна.')
    assert 'сверка с исходником не выполнена' in response.reply


@pytest.mark.asyncio
async def test_output_limit_does_not_accept_partial_replacement(monkeypatch):
    r = rows()
    monkeypatch.setattr(router, '_fetch_course_summary', AsyncMock(return_value='{}'))
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', AsyncMock(return_value=Row(
        ainvoke=AsyncMock(return_value=Row(content='unfinished', finish_reason='length')))))
    with pytest.raises(HTTPException) as caught:
        await router.chat(AIChatRequest(course_id=r.course.id, message='Улучши'),
            db=object(), user=Row(tenant_id=r.tenant, role='methodologist'))
    assert caught.value.status_code == 422
    assert caught.value.detail == {'code': 'assistant_response_incomplete'}


@pytest.mark.asyncio
async def test_large_context_reaches_model_whole_without_a_new_arbitrary_clip(monkeypatch):
    r = rows()
    full = 'x' * 100_000 + 'FINAL_CONTEXT_SENTINEL'
    monkeypatch.setattr(router, '_fetch_course_summary', AsyncMock(return_value=full))
    seen = []
    async def invoke(messages):
        seen.append(messages[1]['content'])
        return Row(content='Review complete.')
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', AsyncMock(return_value=Row(ainvoke=invoke)))
    await router.chat(AIChatRequest(course_id=r.course.id, message='Проверь'),
        db=object(), user=Row(tenant_id=r.tenant, role='methodologist'))
    assert full in seen[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('focus', ['module', 'lesson'])
async def test_unavailable_focus_is_404_not_an_unfocused_review(monkeypatch, focus):
    r = rows()
    monkeypatch.setattr(router, '_fetch_course_summary', AsyncMock(return_value='owned course'))
    monkeypatch.setattr(router, '_fetch_target_context', AsyncMock(return_value=''))
    provider = AsyncMock(side_effect=AssertionError('foreign target must not reach model'))
    monkeypatch.setattr(router.ResilientLLMClient, 'from_settings_async', provider)
    with pytest.raises(HTTPException) as caught:
        await router.chat(AIChatRequest(course_id=r.course.id, context=focus, target_id=uuid4(), message='Проверь'),
            db=object(), user=Row(tenant_id=r.tenant, role='methodologist'))
    assert caught.value.status_code == 404
    provider.assert_not_awaited()
