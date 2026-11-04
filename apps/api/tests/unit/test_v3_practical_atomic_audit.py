import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_atomic_audit import (
    atomic_audit_format,
    atomic_audit_messages,
    atomic_audit_narrative_sources,
    compiled_atomic_audit_findings,
    is_atomic_audit_format,
    matches_atomic_audit,
    validate_atomic_audit,
)
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def audit_value(packet, course):
    lesson = course['lessons'][0]['id']
    return {'source_fingerprint': packet.fingerprint, 'source_review': 'Reviewed.', 'source_notes': [], 'findings': [],
            'source_checks': [{'source_refs': [b.block_id], 'status': 'TAUGHT', 'lesson_ids': [lesson], 'reason': ''}
                              for b in packet.blocks if b.text.strip()]}


def test_unmirrored_source_defects_compile_and_keep_distinct_reasons(case):
    _, packet, course = case
    value = audit_value(packet, course)
    row = value['source_checks'][0]
    row.update(status='MISSING', reason='Exception omitted.')
    original = copy.deepcopy(value)
    compiled = compiled_atomic_audit_findings(value, packet, course)
    assert value == original and compiled[0]['scope'] == 'coverage'
    assert compiled[0]['target_id'] == 'l1' and compiled[0]['problem'] == 'Exception omitted.'
    assert atomic_audit_narrative_sources(value, packet, course)['l1']
    row.update(status='CONTRADICTED', reason='The rule was reversed.')
    value['findings'] = [{'scope': 'lesson', 'target_id': 'l1', 'problem': 'Other issue.',
                          'source_refs': row['source_refs'], 'expected_rule': 'Rule.', 'correction': 'Fix.'}]
    compiled = compiled_atomic_audit_findings(value, packet, course)
    assert len(compiled) == 2 and compiled[1]['scope'] == 'lesson'
    assert compiled[1]['problem'] == 'The rule was reversed.'


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'foreign', 'empty_owner', 'blank_reason', 'bad_target'])
def test_exact_atomic_inventory_and_targets_fail_closed(case, defect):
    _, packet, course = case
    value = audit_value(packet, course)
    if defect == 'missing':
        value['source_checks'].pop()
    elif defect == 'duplicate':
        value['source_checks'][1]['source_refs'] = value['source_checks'][0]['source_refs']
    elif defect == 'foreign':
        value['source_checks'][0]['source_refs'] = ['foreign']
    elif defect == 'empty_owner':
        value['source_checks'][0].update(status='CONTRADICTED', lesson_ids=[], reason='Contradiction.')
    elif defect == 'blank_reason':
        value['source_checks'][0].update(status='MISSING', reason=' ')
    else:
        value['findings'] = [{'scope': 'assessment', 'target_id': 'q1', 'problem': 'Problem.',
                              'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Rule.', 'correction': 'Fix.'}]
    assert not matches_atomic_audit(value, atomic_audit_format(packet, course))


def test_unowned_missing_routes_to_source_and_uncertainty_stays_source(case):
    _, packet, course = case
    value = audit_value(packet, course)
    value['source_checks'][0].update(status='MISSING', lesson_ids=[], reason='Missing rule.')
    finding = compiled_atomic_audit_findings(value, packet, course)[0]
    assert finding['scope'] == 'coverage' and finding['target_id'] == packet.blocks[0].block_id
    value['source_checks'][0].update(status='UNCERTAIN', reason='Source is ambiguous.')
    finding = compiled_atomic_audit_findings(value, packet, course)[0]
    assert finding['scope'] == 'source' and finding['target_id'] == packet.blocks[0].block_id


@pytest.mark.parametrize(('question_count', 'source_count'), [(50, 276), (100, 300), (3, 1000)])
def test_aliased_atomic_schema_fits_shipped_runner(question_count, source_count):
    text = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(source_count))
    revision = 'document:' + hashlib.sha256(text.encode()).hexdigest()
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general', revision, (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    assert len(packet.blocks) == source_count
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
                  'correct_index': 0, 'explanation': 'Explanation.', 'source_refs': [packet.blocks[i].block_id]}
                 for i in range(question_count)]
    course = {'title': 'Course', 'lessons': [{'id': f'l{i}', 'title': f'Lesson {i}', 'content': 'Text.',
                 'questions': questions[i:i + 4]} for i in range(0, question_count, 4)]}
    fmt = atomic_audit_format(packet, course)
    wire_fmt = PracticalModelView(packet).schema(fmt)
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('atomic_audit_scale_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert is_atomic_audit_format(fmt) and response_contract(wire_fmt) == 'practical_source_audit'
    assert module._checked_structured_format(wire_fmt) == wire_fmt['json_schema']['schema']
    assert len(json.dumps(wire_fmt, ensure_ascii=False, separators=(',', ':')).encode()) <= module.MAX_SCHEMA_BYTES
    assert matches_response_contract(PracticalModelView(packet).encode(audit_value(packet, course)), wire_fmt)


@pytest.mark.asyncio
async def test_managed_atomic_stage_cold_replay_and_wrong_model_or_format_rejected(case, monkeypatch):
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_direct_luna_owned_stage import setup

    _, packet, course = case
    view = PracticalModelView(packet)
    wire = view.encode(audit_value(packet, course))
    fmt = view.schema(atomic_audit_format(packet, course))
    messages = atomic_audit_messages(packet, course, model_view=view)

    def client_for(journal):
        return ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
            credential_revision='r1', model='gpt-6-luna', reasoning_effort='high', deadline_seconds=300)

    def options(journal, client, response_format=fmt):
        def validate(value):
            validate_atomic_audit(view.decode(value), packet, course)
        return dict(journal=journal, direct_client=client, stage='review',
            group_id='practical:source-audit:synthetic-v14', source_sha256='b' * 64,
            route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=response_format,
            direct_max_output_tokens=128, response_validator=validate, invoke=AsyncMock())

    _, journal, _, _, _ = setup()
    client = client_for(journal)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=1)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    assert await stage_once(**options(journal, client)) == wire
    assert await stage_once(**options(copy.copy(journal), client)) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()

    _, other_journal, _, _, _ = setup()
    other = client_for(other_journal)
    monkeypatch.setattr(other, 'prepare', AsyncMock(return_value=object()))
    monkeypatch.setattr(other, 'invoke', AsyncMock(return_value=SimpleNamespace(content=wire, model='wrong-model',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=1))))
    with pytest.raises((ValueError, ExtractionOutcomeUnknownError)):
        await stage_once(**options(other_journal, other))

    invalid = copy.deepcopy(fmt)
    invalid['json_schema']['schema']['properties']['extra'] = {'type': 'string'}
    _, bad_journal, _, _, _ = setup()
    bad_client = client_for(bad_journal)
    bad_prepare = AsyncMock(return_value=object())
    monkeypatch.setattr(bad_client, 'prepare', bad_prepare)
    with pytest.raises(ValueError, match='direct_owned_format_invalid'):
        await stage_once(**options(bad_journal, bad_client, invalid))
    bad_prepare.assert_not_awaited()
