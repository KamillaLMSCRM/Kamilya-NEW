import copy
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient, _ResponseDecodeError
from app.modules.ai.v3.practical_action_object_graph import (
    candidate_inventory,
    compile_response,
    graph_format,
    is_action_object_graph_format,
    matches_action_object_graph,
    request,
)
from app.modules.ai.v3.response_contracts import (
    matches_transport_contract,
    response_contract,
    response_contract_hash,
)


@pytest.fixture
def graph_case():
    records = [{'id': 'source-block', 'text': 'Птица видит лес и видит море. Птица не видит лес.'}]
    messages, fmt, local = request('source', records)
    decisions = [{'token_id': row['token_id'], 'classification': 'OPERATIVE', 'object_kind': 'OBJECT',
                  'object_quote': quote, 'negation_quote': negation, 'note': ''}
                 for row, quote, negation in zip(local['candidates'], ('лес', 'море', 'not literal'),
                                                  ('', '', 'не'), strict=True)]
    value = {'role': 'source', 'input_fingerprint': local['input_fingerprint'], 'decisions': decisions}
    return records, messages, fmt, local, value


def test_all_readings_include_ambiguous_noun_verb():
    candidates, provenance = candidate_inventory([{'id': 'r', 'text': 'Пила.'}])
    assert candidates and {'NOUN', 'VERB'} <= {row['pos'] for row in provenance[0]['tokens'][0]['all_readings']}


def test_source_and_learner_requests_are_separate_and_role_bound(graph_case):
    records, source_messages, _, _, value = graph_case
    learner = [{'id': 'lesson', 'text': 'Ребёнок рисует дерево.'}]
    learner_messages, learner_fmt, learner_local = request('learner', learner)
    assert records[0]['text'] not in json.dumps(learner_messages, ensure_ascii=False)
    assert learner[0]['text'] not in json.dumps(source_messages, ensure_ascii=False)
    assert learner_local['input_fingerprint'] != value['input_fingerprint']
    assert not matches_action_object_graph(value, learner_fmt)


def test_quote_custody_and_native_grammar(graph_case, monkeypatch):
    records, _, fmt, _, value = graph_case
    assert response_contract(fmt) == 'practical_action_object_graph' and matches_transport_contract(value, fmt)
    result = compile_response(value, 'source', records)
    assert [row['object_evidence']['status'] for row in result['observations']] == [
        'AMBIGUOUS_COORDINATE', 'LITERAL_UNIQUE', 'UNVERIFIED_NONLITERAL']
    assert result['observations'][2]['negation_evidence']['status'] == 'LITERAL_UNIQUE'
    assert result['observations'][2]['decision']['object_quote'] == 'not literal' and not result['semantic_acceptance']
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('action_graph_native_test_runner', path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runner)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'foreign', 'role', 'fingerprint', 'extra', 'badtype'])
def test_exhaustive_owned_token_guards(graph_case, mutation):
    records, _, fmt, _, value = graph_case
    if mutation == 'missing':
        value['decisions'].pop()
    elif mutation == 'duplicate':
        value['decisions'][-1]['token_id'] = value['decisions'][0]['token_id']
    elif mutation == 'foreign':
        value['decisions'][0]['token_id'] = 'foreign'
    elif mutation == 'role':
        value['role'] = 'learner'
    elif mutation == 'fingerprint':
        value['input_fingerprint'] = 'f' * 64
    elif mutation == 'extra':
        value['decisions'][0]['verdict'] = 'forged'
    else:
        value['decisions'] = False
    assert not matches_action_object_graph(value, fmt)
    with pytest.raises(ValueError):
        compile_response(value, 'source', records)


def test_reconstruction_and_input_ownership(graph_case):
    records, _, fmt, _, value = graph_case
    forged = copy.deepcopy(fmt)
    forged['json_schema']['schema']['properties']['decisions']['maxItems'] += 1
    assert not is_action_object_graph_format(forged)
    changed = copy.deepcopy(records)
    changed[0]['text'] += ' changed'
    with pytest.raises(ValueError):
        compile_response(value, 'source', changed)
    for bad in (None, [], True, {'json_schema': {}}):
        assert not is_action_object_graph_format(bad)
    with pytest.raises(ValueError):
        graph_format('source', 'a' * 64, ['T1', 'T1'])


@pytest.mark.asyncio
async def test_native_prepare_and_decode_without_network(graph_case):
    _, messages, fmt, _, value = graph_case
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
        bad = copy.deepcopy(value)
        bad['decisions'][0]['token_id'] = 'foreign'
        with pytest.raises(_ResponseDecodeError, match='structured_shape'):
            client._decode_response(response(bad), wire)
    finally:
        client.close()
