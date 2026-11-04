import copy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from app.modules.ai.v3.response_contracts import matches_response_contract
from app.modules.ai.v3.revision_policy import PRACTICAL_REVIEW_POLICY
from tests.unit.test_v3_practical_concise_review import concise_review

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def test_p14_strict_finding_targets_and_answerability(case):
    _, packet, course = case
    fmt = practical_review_format(packet, course, concise=True, strict_targets=True)
    assert is_practical_review_format(fmt)
    value = concise_review(packet, course)
    assert matches_practical_review(value, fmt)
    finding = {'scope': 'assessment', 'target_id': 'q1', 'problem': 'Missing assessment.',
               'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Rule.', 'correction': 'Fix.'}
    value['findings'] = [finding]
    assert not matches_practical_review(value, fmt)
    finding['target_id'] = 'l1'
    assert matches_practical_review(value, fmt)
    finding['source_refs'] = ['foreign']
    assert not matches_practical_review(value, fmt)
    value = concise_review(packet, course)
    value['answerability'][0].update(status='DEPENDS', possible_options=[0, 1])
    assert not interpret_practical_review(value, packet, course, concise=True, strict_targets=True).accepted
    message = practical_review_messages(packet, course, concise=True, lesson_scoped=True)
    assert 'correct_index' not in message[1]['content']
    for block in packet.blocks:
        assert block.text in message[1]['content']
    tampered = copy.deepcopy(fmt)
    tampered['json_schema']['schema']['properties']['findings']['items']['anyOf'][0]['properties']['target_id']['enum'].append('foreign')
    assert not is_practical_review_format(tampered)


def test_p14_single_lesson_1000_source_schema_passes_shipped_runner():
    source = ''.join(f'Operational paragraph {i}.\n\n' for i in range(1000))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
                               'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    assert len(packet.blocks) == 1000
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text.',
        'questions': [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
                       'correct_index': 0, 'explanation': 'Explanation.', 'source_refs': [packet.blocks[i].block_id]}
                      for i in range(4)]}]}
    fmt = practical_review_format(packet, course, concise=True, strict_targets=True)
    view = PracticalModelView(packet)
    wire = view.schema(fmt)
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('p14_practical_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(wire) == wire['json_schema']['schema']
    assert matches_response_contract(view.encode(concise_review(packet, course)), wire)
    duplicated = copy.deepcopy(course)
    duplicated['lessons'].append(copy.deepcopy(course['lessons'][0]))
    duplicated['lessons'][1]['id'] = 'l2'
    for question in duplicated['lessons'][1]['questions']:
        question['id'] += '_other'
    with pytest.raises(ValueError):
        practical_review_format(packet, duplicated, concise=True, strict_targets=True)


@pytest.mark.asyncio
async def test_fresh_service_dispatch_skips_legacy_reader(case, monkeypatch):
    from app.modules.ai.v3 import practical_lesson_cycle, practical_service

    corpus, packet, course = case
    expected = object()
    callbacks = []
    invoke = AsyncMock()

    async def cycle(actual_packet, intent, stage, *, max_revisions):
        assert actual_packet == packet and intent['audience'] == 'Staff' and max_revisions == 3
        invoke.return_value = course
        await stage('lesson', 'practical:author:v1', [], {}, lambda _: None)
        fmt = practical_review_format(packet, course, concise=True, strict_targets=True)
        value = concise_review(packet, course)
        invoke.return_value = value
        await stage('review', 'practical:review:lesson:l1', [], fmt,
                    lambda response: interpret_practical_review(response, packet, course, concise=True, strict_targets=True))
        invoke.return_value = {'new_lessons': [{'id': 'l2'}]}
        await stage('repair', 'practical:repair:example', [], {}, lambda _: None)
        return expected

    async def progress(*args):
        callbacks.append(args)

    monkeypatch.setattr(practical_lesson_cycle, 'run_lesson_practical_cycle', cycle)
    monkeypatch.setattr(practical_service, 'source_reader_parts', lambda _: pytest.fail('legacy reader invoked'))
    monkeypatch.setattr(practical_service, 'practical_artifacts', lambda result, *_: result)
    result = await practical_service.generate_practical_course(corpus, intent=CourseIntent(audience='Staff'),
        invoke=invoke, source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
        progress_callback=progress, review_policy=PRACTICAL_REVIEW_POLICY)
    assert result is expected and invoke.await_count == 3
    assert callbacks == [('realization', 1, 12, None, 1), ('realization', 2, 12, None, 1),
                         ('realization', 3, 16, None, 1)]
    assert all(0 < current < total for _, current, total, _, _ in callbacks)


@pytest.mark.asyncio
@pytest.mark.parametrize('returned_model', ['gpt-6-luna', 'gpt-5.6-luna'])
async def test_lesson_review_cold_journal_replay_and_model_binding(case, monkeypatch, returned_model):
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_direct_luna_owned_stage import setup

    _, packet, course = case
    view = PracticalModelView(packet)
    wire = view.encode(concise_review(packet, course))
    _, journal, _, _, _ = setup()
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1', model='gpt-6-luna', reasoning_effort='high', deadline_seconds=300)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model=returned_model,
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate(value):
        interpret_practical_review(view.decode(value), packet, course, concise=True, strict_targets=True)
    options = dict(journal=journal, direct_client=client, stage='review',
        group_id='practical:review:lesson:l1', source_sha256='b' * 64,
        route_fingerprint=client.cache_fingerprint(),
        messages=practical_review_messages(packet, course, concise=True, lesson_scoped=True, model_view=view),
        response_format=view.schema(practical_review_format(packet, course, concise=True, strict_targets=True)),
        direct_max_output_tokens=128, response_validator=validate, invoke=AsyncMock())
    if returned_model == 'gpt-6-luna':
        assert await stage_once(**options) == wire
        assert await stage_once(**{**options, 'journal': copy.copy(journal)}) == wire
    else:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(**options)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(**{**options, 'journal': copy.copy(journal)})
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
