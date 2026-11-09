import copy
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.managed_luna_client import ManagedLunaClient, _ResponseDecodeError
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_editor import (
    compile,
    is_question_editor_format,
    matches_question_editor,
    request,
)
from app.modules.ai.v3.response_contracts import matches_transport_contract, response_contract, response_contract_hash


@pytest.fixture
def question_case():
    text = 'A worker reviews the record.'
    doc = DirectSourceDocument('doc', 'Source', 'f', 'other', 'r', (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    view = PracticalModelView(packet)
    def question(qid):
        return {'id': qid, 'prompt': 'Which action?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
                'explanation': 'Explanation', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [
        {'id': 'lesson1', 'title': 'One', 'content': 'BODY_SENTINEL_84b2', 'questions': [question('q1')]},
        {'id': 'lesson2', 'title': 'Two', 'content': 'Other prose', 'questions': [question('q2')]}]}
    messages, fmt = request(packet, course, view)
    value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
             'checks': [{'question_id': 'q1', 'status': 'VALID', 'reason': 'Reviewed'},
                        {'question_id': 'q2', 'status': 'UNVERIFIED', 'reason': 'Insufficient'}], 'updates': []}
    return packet, course, view, messages, fmt, value


def test_question_only_registry_and_unverified_preservation(question_case, monkeypatch):
    packet, course, view, messages, fmt, value = question_case
    assert 'BODY_SENTINEL_84b2' not in json.dumps([messages, fmt])
    assert response_contract(fmt) == 'practical_question_editor' and matches_transport_contract(value, fmt)
    proposed, receipt = compile(value, packet, course, view)
    assert proposed == course and proposed is not course
    assert receipt['unverified_question_ids'] == ['q2'] and not receipt['semantic_acceptance']
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('question_editor_native_runner', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(fmt) == fmt['json_schema']['schema']


def repaired_value(question_case):
    _, course, view, _, _, value = question_case
    q = copy.deepcopy(course['lessons'][0]['questions'][0])
    q['prompt'] = 'Repaired prompt'
    value['checks'][0]['status'] = 'REPAIRED'
    value['updates'] = [{'lesson_id': 'lesson1', 'question': view.encode(q)}]
    return value


def test_owned_update_preserves_bodies_titles_order_and_other_question(question_case):
    packet, course, view, _, _, _ = question_case
    original = copy.deepcopy(course)
    proposed, receipt = compile(repaired_value(question_case), packet, course, view)
    expected = copy.deepcopy(course)
    expected['lessons'][0]['questions'][0]['prompt'] = 'Repaired prompt'
    assert proposed == expected and course == original
    assert receipt['updated_question_ids'] == ['q1'] and receipt['unverified_question_ids'] == ['q2']


@pytest.mark.parametrize('mutation', ['source', 'course', 'missing', 'duplicate', 'foreign_q', 'foreign_ref',
                                      'wrong_owner', 'choicecount', 'status', 'extra', 'badtype'])
def test_malformed_or_foreign_question_proposals_fail(question_case, mutation):
    packet, course, view, _, fmt, _ = question_case
    value = repaired_value(question_case)
    if mutation == 'source':
        value['source_fingerprint'] = 'f' * 64
    elif mutation == 'course':
        value['course_fingerprint'] = 'f' * 64
    elif mutation == 'missing':
        value['checks'].pop()
    elif mutation == 'duplicate':
        value['checks'][1]['question_id'] = 'q1'
    elif mutation == 'foreign_q':
        value['updates'][0]['question']['id'] = 'foreign'
    elif mutation == 'foreign_ref':
        value['updates'][0]['question']['source_refs'] = ['SRC999']
    elif mutation == 'wrong_owner':
        value['updates'][0]['lesson_id'] = 'lesson2'
    elif mutation == 'choicecount':
        value['updates'][0]['question']['choices'].append('Fourth')
    elif mutation == 'status':
        value['checks'][0]['status'] = 'UNVERIFIED'
    elif mutation == 'extra':
        value['updates'][0]['content'] = 'Unexpected prose'
    else:
        value['checks'] = False
    if mutation not in ('wrong_owner', 'choicecount'):
        assert not matches_question_editor(value, fmt)
    with pytest.raises(ValueError):
        compile(value, packet, course, view)


def test_schema_tamper_fails_recognition(question_case):
    _, _, _, _, fmt, _ = question_case
    changed = copy.deepcopy(fmt)
    changed['json_schema']['schema']['properties']['checks']['maxItems'] += 1
    assert not is_question_editor_format(changed)
    for malformed in (None, True, [], {'json_schema': {}}):
        assert not is_question_editor_format(malformed)


@pytest.mark.asyncio
async def test_native_prepare_decode_and_foreign_rejection(question_case):
    _, _, _, messages, fmt, value = question_case
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic', tenant_id=uuid4(),
        user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic', model='gpt-6-luna',
        deadline_seconds=300, reasoning_effort='high')
    try:
        cap = await client.prepare(messages, max_output_tokens=1000, ownership_checkpoint=AsyncMock(return_value=True),
                                   response_format=fmt)
        wire = client._prepared.pop(cap)
        assert json.loads(wire)['response_format'] == fmt
        def response(item):
            return json.dumps({'model': 'gpt-6-luna', 'structured_output_policy': 'typed-json-object-v1',
                'response_format_sha256': response_contract_hash(fmt), 'choices': [{'message': {'content': json.dumps(item)}}],
                'usage': {'prompt_tokens': 20, 'completion_tokens': 30}}).encode()
        result, _ = client._decode_response(response(value), wire)
        assert result.content == value
        mutated = copy.deepcopy(value)
        mutated['checks'][0]['question_id'] = 'foreign'
        with pytest.raises(_ResponseDecodeError, match='structured_shape'):
            client._decode_response(response(mutated), wire)
    finally:
        client.close()
