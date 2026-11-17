"""Reading fully completed corrective receipts does not spend a new retry."""
import json

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaCompletedJsonError
from app.modules.source_editorial_review.analysis import _REISSUE_JSON_INSTRUCTION, _ManagedSourceJsonRecovery
from app.modules.source_editorial_review.request_custody import identity, invoke_once


@pytest.mark.asyncio
async def test_two_known_corrected_replies_replay_before_and_after_the_single_new_reissue():
    retained = {}
    wire_calls = []
    usage = []

    def key(messages):
        return identity(tenant='owned', document='same-source', original_sha='a' * 64, selected_sha='b' * 64,
                        policy='same-policy', route='same-route', messages=messages)

    async def save(name, value):
        retained[name] = value

    def messages(label):
        return [{'role': 'system', 'content': 'Review'}, {'role': 'user', 'content': label}]

    def corrected(m):
        return [{**m[0], 'content': m[0]['content'] + _REISSUE_JSON_INSTRUCTION}, *m[1:]]

    # Exact fully completed custody from two different prior worker turns.
    for label in ('saved-one', 'saved-two'):
        m = messages(label)
        retained[f'source-review-request-custody-v2:{key(m)}:initial:completed'] = {
            'identity': key(m), 'attempt': 'initial', 'status': 'invalid_json', 'usage': None}
        c = corrected(m)
        retained[f'source-review-request-custody-v2:{key(c)}:initial:completed'] = {
            'identity': key(c), 'attempt': 'initial', 'status': 'ok', 'usage': None,
            'value': {'label': label}}

    def completed(m):
        value = retained.get(f'source-review-request-custody-v2:{key(m)}:initial:completed')
        return bool(value and value.get('identity') == key(m) and value.get('status') == 'ok')

    async def request(m):
        async def network():
            wire_calls.append(m)
            assert m[1]['content'].startswith('fresh-'), 'A saved reply was sent to the model again'
            if _REISSUE_JSON_INSTRUCTION not in m[0]['content']:
                raise ManagedLunaCompletedJsonError('known_complete_bad_json')
            return json.dumps({'label': m[1]['content']}), None
        return await invoke_once(key=key(m), attempt='initial', retained=retained, save=save,
                                 before_post=lambda: None, invoke=network, usage=lambda *u: usage.append(u))

    recovery = _ManagedSourceJsonRecovery()
    for label in ('saved-one', 'saved-two'):
        assert await recovery.complete(messages(label), request, completed_correction=completed) == {'label': label}
    assert not recovery.used and not wire_calls
    assert await recovery.complete(messages('fresh-one'), request, completed_correction=completed) == {'label': 'fresh-one'}
    assert recovery.used and len(wire_calls) == 2
    assert await recovery.complete(messages('saved-two'), request, completed_correction=completed) == {'label': 'saved-two'}
    assert len(wire_calls) == 2 and recovery.used
    with pytest.raises(ManagedLunaCompletedJsonError):
        await recovery.complete(messages('fresh-two'), request, completed_correction=completed)
    assert len(wire_calls) == 3  # The second new invalid answer gets no new reissue.
    assert len(usage) >= 8  # Cached invalid/corrected usage remains visible too.


@pytest.mark.asyncio
@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('quote_case', [False, True, 'reference', 'long_literal', 'handoff_failure'])
async def test_native_worker_reuses_two_completed_corrections_without_provider_calls(monkeypatch, managed, quote_case):
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from app.modules.ai.direct_luna_api import LunaUsage
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.source_editorial_review import analysis
    from app.modules.source_editorial_review.domain import text_hash
    from app.modules.source_preparation.domain import PreparedSource, digest
    from app.modules.source_preparation.preparation import _VISUAL_REVIEW_POLICY
    from tests.unit.test_source_review_custody import row

    tenant, document, actor = QA_TENANT, uuid4(), uuid4()
    source = '| Item | Rule |\n| --- | --- |\n| A | A has two units. Units: 1 |\n' if quote_case else 'Source'
    literal = '| B | A shared introduction. Two units. Units: 1 |'
    if quote_case == 'reference':
        source = '| Item | Rule |\n| --- | --- |\n| A | A shared introduction. Units: 1 |\n' + literal + '\n'
    elif quote_case == 'long_literal':
        literal = '| A | ' + 'Source detail. ' * 180 + 'Two units. Units: 1 |'
        source = '| Item | Rule |\n| --- | --- |\n' + literal + '\n'
    blob, block_id = 'a' * 64, 'block-' + 'b' * 24
    package = PreparedSource.model_validate({'original_blob_sha256': blob,
        'blocks': [{'id': block_id, 'text': source, 'kind': 'text'}],
        'parts': [{'id': 'part-' + digest(blob + block_id + block_id)[:24], 'title': 'Source', 'role': 'learning',
                   'reason': 'Relevant', 'first_block': block_id, 'last_block': block_id}]})
    binding = package.binding([package.parts[0].id])
    config = SimpleNamespace(name='synthetic', model='fixture', base_url='local-test', endpoint='/test',
                             timeout=5, extra_body={}, managed_evidence_profile=False)
    route = 'managed-fixture' if managed else text_hash(json.dumps([
        config.name, config.model, config.base_url, config.endpoint, 5.0, 1000, {},
        'source-review-single-attempt-v2'], sort_keys=True))
    rows = []
    def event(kind, payload):
        value = row(kind, len(rows) + 1, actor, blob, payload)
        value.created_at = datetime.now(UTC)
        rows.append(value)
        return value
    event('queued', {})
    event('running', {'queued_event_id': str(rows[0].id)})
    event('analysis_block', {'key': 'source-preparation-v1:manifest:' + blob,
        'result': {'manifest': package.model_dump(), 'visual_review_policy': _VISUAL_REVIEW_POLICY}})
    messages = [[{'role': 'system', 'content': 'review'},
                 {'role': 'user', 'content': json.dumps({'saved': label})}] for label in ('one', 'two')]
    for original in messages:
        corrected = [{**original[0], 'content': original[0]['content'] + _REISSUE_JSON_INSTRUCTION}, original[1]]
        for m, bad in ((original, True), (corrected, False)):
            key = identity(tenant=str(tenant), document=str(document), original_sha=blob,
                           selected_sha=text_hash(json.dumps(binding, ensure_ascii=False, sort_keys=True)),
                           policy=analysis._ANALYSIS_POLICY, route=route, messages=m)
            event('analysis_block', {'key': 'source-review-request-custody-v2:' + key + ':initial:completed',
                'result': {'identity': key, 'attempt': 'initial', 'usage': None,
                           'status': 'invalid_json' if bad and managed else 'ok',
                           'value': '{bad' if bad else {'ok': True}}})
    event('failed', {'code': 'source_review_invalid_response'})
    queued = event('queued', {'preparation': binding})
    doc = SimpleNamespace(id=document, tenant_id=tenant, content_sha256=blob, filename='source.txt', s3_key='fixture')
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    @asynccontextmanager
    async def sessions():
        yield session
    def add_event(_db, _doc, *, kind, payload, **_):
        return event(kind, payload)
    async def analyze_fixture(source, *, complete_json, **_):
        if quote_case == 'handoff_failure':
            from app.modules.source_editorial_review.request_custody import BeforePostDeferred
            raise BeforePostDeferred()
        assert source == 'Source'
        for m in messages:
            assert await complete_json(m) == {'ok': True}
        return {'original': source, 'issues': [], 'automatic': [], 'model_calls': 0}

    async def synthetic_provider(m, **_):
        assert quote_case, 'Completed repair was sent again'
        payload = json.loads(m[1]['content'])
        if payload.get('task') == 'source-question-evidence-address-v2':
            assert quote_case is True, 'A literal source reference must not acquire a new quote-repair call'
            value = {'repairs': [{'question_index': 0, 'source_refs': payload['items'][0]['reported_source_refs'], 'excerpt': 'A has two units.'}]}
        elif 'proposal_sha256' not in payload:
            value = {'patches': [], 'unresolved': ([{'alias': 'B', 'excerpt': literal,
                      'category': 'conflict', 'reason': 'Two or one?'}] if quote_case == 'reference' else [])}
        else:
            ref = payload['source_question_context']['references'][0]['id']
            value = {'proposal_sha256': payload['proposal_sha256'], 'rows': [], 'source_questions': [
                {'excerpt': literal if quote_case in ('reference', 'long_literal') else 'A has two units. ... Units: 1', 'category': 'conflict', 'reason': 'One or two units?',
                 'source_refs': [ref], 'disposition': 'needs_human'}]}
        return SimpleNamespace(content=value, provider_name='synthetic', model='fixture',
                               prompt_tokens=1, completion_tokens=1, usage_complete=True, usage=LunaUsage(1, 1, None, None))
    network = AsyncMock(side_effect=synthetic_provider)
    async def prepare_messages(m, *, ownership_checkpoint, **_):
        assert await ownership_checkpoint()
        return m
    managed_client = SimpleNamespace(cache_fingerprint=lambda: route, generation_deadline_seconds=5,
                                     prepare=AsyncMock(side_effect=prepare_messages), discard=Mock(), invoke=network, close=Mock())
    monkeypatch.setattr(analysis, 'async_session_factory', sessions)
    monkeypatch.setattr(analysis, 'owned_document', AsyncMock(return_value=doc))
    archive_read = AsyncMock(side_effect=lambda *_: list(rows))
    monkeypatch.setattr(analysis, 'history', archive_read)
    monkeypatch.setattr(analysis, 'latest_event', AsyncMock(side_effect=lambda *_: rows[-1]), raising=False)
    monkeypatch.setattr(analysis, 'add_event', add_event)
    monkeypatch.setattr(analysis, 'review_enabled', lambda: True)
    monkeypatch.setattr(analysis, 'get_settings', lambda: SimpleNamespace(AI_MANAGED_LUNA_QA_DEV_ENABLED=managed))
    if not quote_case or quote_case == 'handoff_failure':
        monkeypatch.setattr(analysis, 'analyze', analyze_fixture)
    if quote_case == 'handoff_failure':
        from sqlalchemy.exc import DBAPIError
        monkeypatch.setattr(analysis, 'handoff', AsyncMock(side_effect=DBAPIError(
            None, None, Exception('synthetic disconnect'), connection_invalidated=True)))
    monkeypatch.setattr(analysis.ResilientLLMClient, 'from_settings_async',
                        AsyncMock(return_value=SimpleNamespace(_clients=[SimpleNamespace(config=config)])))
    monkeypatch.setattr('app.modules.admin.runtime_configuration.runtime.resolve_runtime_settings',
                        AsyncMock(return_value=SimpleNamespace(integer=lambda _: 1000)))
    monkeypatch.setattr('app.modules.ai.direct_luna_responses_factory.create_managed_qa_client',
                        AsyncMock(return_value=managed_client))
    monkeypatch.setattr('app.modules.ai.llm_client.LLMClient', lambda *_a, **_k: SimpleNamespace(ainvoke=network))
    if quote_case == 'handoff_failure':
        assert await analysis.run_analysis(tenant, document, queued.id) == 'failed'
        assert rows[-1].kind == 'failed'
        assert rows[-1].payload['code'] == 'source_review_continuation_failed'
        assert rows[-1].payload['phase'] == 'continuation_handoff'
        assert rows[-1].payload['cause_class'] == 'DBAPIError'
        assert not rows[-1].payload.get('unknown_request_key')
        network.assert_not_awaited()
        return
    assert await analysis.run_analysis(tenant, document, queued.id) == 'analyzed'
    archive_read.assert_awaited_once()  # Completed receipts loaded once, not per claim/checkpoint.
    assert rows[-1].kind == 'analyzed' and rows[-1].payload['original'] == source
    if quote_case == 'reference':
        assert network.await_count == 2
        question, = rows[-1].payload['issues']
        assert question['quote'] == literal and question['start'] == source.index(literal)
        assert question['source_labels'] == ['B'] and question['reported_source_refs'] != question['source_refs']
        assert question['source_ref_binding'] == 'unique_original_literal_v1'
    elif quote_case == 'long_literal':
        assert network.await_count == 2
        question, = rows[-1].payload['issues']
        assert len(question['quote']) > 2000 and question['quote'] == literal
        assert question['start'] == source.index(literal) and not question.get('needs_source_verification')
    elif quote_case:
        assert network.await_count == 3
        question, = rows[-1].payload['issues']
        assert question['quote'] == 'A has two units.' and question['start'] == source.index(question['quote'])
        assert question['reported_quote'] == 'A has two units. ... Units: 1'
        assert rows[-1].payload['question_quote_repairs'][0]['accepted'] == [0]
    else:
        network.assert_not_awaited()
