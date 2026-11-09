import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3 import practical_attachment_planner as planner
from app.modules.ai.v3.isolated_attachment_choice_contract import attachment_choice_format
from app.modules.ai.v3.practical_contract import _digest


def record(identifier, text):
    return {'id': identifier, 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}


def test_common_homograph_does_not_hide_different_nominal_anchors(monkeypatch):
    monkeypatch.setattr(planner, '_nominal_only', lambda text: text in ('alpha', 'beta'))
    source = [{'text': text, 'start': i, 'end': i + 1} for i, text in enumerate(('alpha', 'ambiguous', 'beta'))]
    learner = [{'text': text, 'start': i + 10, 'end': i + 11} for i, text in enumerate(('alpha', 'ambiguous', 'beta'))]
    s = {'head_candidates': [{'start': 0, 'end': 1}, {'start': 1, 'end': 2}]}
    learner_row = {'head_candidates': [{'start': 11, 'end': 12}, {'start': 12, 'end': 13}]}
    result = planner._origin(source, learner, s, learner_row)
    assert result['status'] == 'DIFFERENT_POSSIBLE_ANCHORS_UNVERIFIED'
    assert result['source_positions'] == [0] and result['learner_positions'] == [2]
    assert result['uncertain_positions'] == [1]


def test_numeric_context_requires_exact_surface():
    assert not planner._matches_token({'text': '02', 'lemmas': {'2'}}, {'text': '2', 'lemmas': {'2'}})


def test_all_dictionary_readings_survive_in_local_provenance():
    prepared = planner.plan([record('s', 'Пила.')], [record('l', 'Пила.')], 'a' * 64, 'b' * 64)
    readings = prepared['source_token_provenance'][0]['segments'][0]['tokens'][0]['all_readings']
    assert {'NOUN', 'VERB'} <= {item['pos'] for item in readings}
    assert prepared['source_plans'] == [] and prepared['learner_plans'] == []


def test_zero_selected_and_changed_inputs_are_not_success():
    source = [record('src', 'Большой дом.')]
    learner = [record('lesson', 'Большой дом.')]
    prepared = planner.plan(source, learner, 'a' * 64, 'b' * 64)
    assert prepared['source_plans'] == [] and prepared['learner_plans'] == []
    assert prepared['coverage'] == 'UNMATCHED_AND_UNFLAGGED_UNKNOWN' and not prepared['semantic_acceptance']
    assert planner.compile_choices(prepared, source, learner, 'a' * 64, 'b' * 64, [], [])['semantic_acceptance'] is False
    changed = [record('src', 'Другой дом.')]
    with pytest.raises(ValueError, match='attachment_input_changed'):
        planner.compile_choices(prepared, changed, learner, 'a' * 64, 'b' * 64, [], [])
    with pytest.raises(ValueError):
        planner.plan([{'id': 'src', 'text': 'x', 'sha256': 'forged'}], learner, 'a' * 64, 'b' * 64)


def test_actual_chosen_token_instances_not_lemmas(monkeypatch):
    source, learner = [record('s', 'abc')], [record('l', 'abc')]
    sf, cf = 'a' * 64, 'b' * 64
    sb = {'s:W1_2': {'record_id': 's', 'modifier_token_id': 'W1_2', 'allowed_head_token_ids': ['W0_1', 'W2_3']}}
    lb = {'l:W1_2': {'record_id': 'l', 'modifier_token_id': 'W1_2', 'allowed_head_token_ids': ['W0_1', 'W2_3']}}
    fs, fl = attachment_choice_format('c' * 64, sf, cf, 'source', sb), attachment_choice_format('d' * 64, sf, cf, 'learner', lb)
    prepared = {'source_fingerprint': sf, 'course_fingerprint': cf, 'source_records_fingerprint': _digest(source),
        'learner_records_fingerprint': _digest(learner), 'source_plans': [{'response_format': fs}],
        'learner_plans': [{'response_format': fl}], 'pairs': [{'source_task_id': 's:W1_2', 'learner_task_id': 'l:W1_2',
        'status': 'FLAGGED_UNVERIFIED', 'origins': [{'aligned_coordinates': [
            {'source_start': 0, 'source_end': 1, 'learner_start': 0, 'learner_end': 1},
            {'source_start': 2, 'source_end': 3, 'learner_start': 2, 'learner_end': 3}]}]}]}
    monkeypatch.setattr(planner, 'plan', lambda *_args: copy.deepcopy(prepared))
    def value(role, fp, task_id, record_id, selected):
        return {'role': role, 'input_fingerprint': fp, 'source_fingerprint': sf, 'course_fingerprint': cf,
                'decisions': {task_id: {'record_id': record_id, 'modifier_token_id': 'W1_2',
                                         'selected_head_id': selected, 'rationale': ''}}}
    sv, lv = value('source', 'c' * 64, 's:W1_2', 's', 'W0_1'), value('learner', 'd' * 64, 'l:W1_2', 'l', 'W2_3')
    out = planner.compile_choices(prepared, source, learner, sf, cf, [sv], [lv])
    assert out['pairs'][0]['origins'][0]['selected_instance_relation'] == 'DIFFERENT_ALIGNED_POSITION_UNVERIFIED'
    lv['decisions']['l:W1_2']['selected_head_id'] = 'UNKNOWN'
    assert planner.compile_choices(prepared, source, learner, sf, cf, [sv], [lv])['pairs'][0]['origins'][0]['selected_instance_relation'] == 'UNKNOWN'
    sv['decisions']['s:W1_2']['selected_head_id'] = 'W9_10'
    with pytest.raises(ValueError, match='attachment_response_invalid'):
        planner.compile_choices(prepared, source, learner, sf, cf, [sv], [lv])


@pytest.mark.asyncio
async def test_native_role_plan_grammar_and_offline_prepare(monkeypatch):
    rows = [{'record': record('owned', 'A synthetic record'), 'tasks': [{'task_id': 'owned:W0_1', 'record_id': 'owned',
        'modifier_token_id': 'W0_1', 'modifier_text': 'A', 'head_candidates': [{'token_id': 'W2_11', 'text': 'synthetic'}]}]}]
    prepared = planner._role_plan('source', rows, {'owned:W0_1'}, 'a' * 64, 'b' * 64)[0]
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('attachment_planner_runner', path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, runner)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(prepared['response_format']) == prepared['response_format']['json_schema']['schema']
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic', tenant_id=uuid4(),
        user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic', model='gpt-6-luna',
        deadline_seconds=300, reasoning_effort='high')
    try:
        cap = await client.prepare(prepared['messages'], max_output_tokens=1000, ownership_checkpoint=AsyncMock(return_value=True),
                                   response_format=prepared['response_format'])
        assert json.loads(client._prepared.pop(cap))['response_format'] == prepared['response_format']
    finally:
        client.close()
