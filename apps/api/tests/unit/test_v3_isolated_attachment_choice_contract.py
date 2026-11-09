import copy
import importlib.util
from pathlib import Path

import pytest

from app.modules.ai.v3.isolated_attachment_choice_contract import (
    attachment_choice_format,
    is_attachment_choice_format,
    matches_attachment_choice_response,
)
from app.modules.ai.v3.response_contracts import (
    matches_response_contract,
    matches_transport_contract,
    response_contract,
)

INPUT = 'a' * 64
SOURCE = 'b' * 64
COURSE = 'c' * 64


def sample(role='source'):
    bindings = {
        'T1': {'record_id': 'record-a', 'modifier_token_id': '10:15', 'allowed_head_token_ids': ['0:4', '5:9']},
        'T2': {'record_id': 'record-b', 'modifier_token_id': '10:15', 'allowed_head_token_ids': []},
    }
    fmt = attachment_choice_format(INPUT, SOURCE, COURSE, role, bindings)
    decisions = {task: {'record_id': row['record_id'], 'modifier_token_id': row['modifier_token_id'],
                        'selected_head_id': 'UNKNOWN', 'rationale': ''} for task, row in bindings.items()}
    value = {'input_fingerprint': INPUT, 'source_fingerprint': SOURCE, 'course_fingerprint': COURSE,
             'role': role, 'decisions': decisions}
    return bindings, fmt, value


@pytest.mark.parametrize('role', ['source', 'learner'])
def test_closed_native_registered_format_and_unknown(role):
    bindings, fmt, value = sample(role)
    assert is_attachment_choice_format(fmt)
    assert response_contract(fmt) == 'practical_isolated_attachment_choice'
    assert matches_attachment_choice_response(value, fmt)
    assert matches_response_contract(value, fmt) and matches_transport_contract(value, fmt)
    value['decisions']['T1']['selected_head_id'] = '5:9'
    assert matches_attachment_choice_response(value, fmt)  # A valid choice is still an unverified hypothesis.
    bindings['T1']['allowed_head_token_ids'].append('16:20')
    assert is_attachment_choice_format(fmt)  # Caller mutation did not alter the bound format.
    assert response_contract({'type': 'json_object'}) is None
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('attachment_contract_runner', path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


@pytest.mark.parametrize('mutation', ['record', 'modifier', 'foreign_head', 'empty_head', 'input_fp', 'source_fp',
                                      'course_fp', 'swap_fps', 'role', 'missing', 'extra', 'paraphrase', 'boolean'])
def test_response_ownership_and_closed_shape(mutation):
    _, fmt, value = sample()
    if mutation == 'record':
        value['decisions']['T1']['record_id'] = 'record-b'
    elif mutation == 'modifier':
        value['decisions']['T1']['modifier_token_id'] = '0:4'
    elif mutation == 'foreign_head':
        value['decisions']['T1']['selected_head_id'] = '12:19'
    elif mutation == 'empty_head':
        value['decisions']['T2']['selected_head_id'] = '0:4'
    elif mutation in {'input_fp', 'source_fp', 'course_fp'}:
        key = {'input_fp': 'input_fingerprint', 'source_fp': 'source_fingerprint', 'course_fp': 'course_fingerprint'}[mutation]
        value[key] = 'd' * 64
    elif mutation == 'swap_fps':
        value['source_fingerprint'], value['course_fingerprint'] = value['course_fingerprint'], value['source_fingerprint']
    elif mutation == 'role':
        value['role'] = 'learner'
    elif mutation == 'missing':
        del value['decisions']['T1']
    elif mutation == 'extra':
        value['decisions']['T3'] = copy.deepcopy(value['decisions']['T1'])
    elif mutation == 'paraphrase':
        value['decisions']['T1']['paraphrase'] = ''
    else:
        value['decisions']['T1']['rationale'] = True
    assert not matches_attachment_choice_response(value, fmt)
    assert not matches_response_contract(value, fmt)


@pytest.mark.parametrize('mutation', ['duplicate_binding', 'duplicate_head', 'reserved_head', 'bad_modifier',
                                      'bad_record', 'bad_role', 'bad_fingerprint', 'empty_tasks'])
def test_invalid_binding_rejected(mutation):
    bindings, _, _ = sample()
    role, fingerprint = 'source', INPUT
    if mutation == 'duplicate_binding':
        bindings['T2']['record_id'] = 'record-a'
    elif mutation == 'duplicate_head':
        bindings['T1']['allowed_head_token_ids'] = ['0:4', '0:4']
    elif mutation == 'reserved_head':
        bindings['T1']['allowed_head_token_ids'] = ['UNKNOWN']
    elif mutation == 'bad_modifier':
        bindings['T1']['modifier_token_id'] = ''
    elif mutation == 'bad_record':
        bindings['T1']['record_id'] = ''
    elif mutation == 'bad_role':
        role = 'other'
    elif mutation == 'bad_fingerprint':
        fingerprint = 'A' * 64
    else:
        bindings = {}
    with pytest.raises(ValueError):
        attachment_choice_format(fingerprint, SOURCE, COURSE, role, bindings)


def test_recognizer_reconstructs_and_checks_size():
    _, fmt, value = sample()
    malformed = copy.deepcopy(fmt)
    tasks = malformed['json_schema']['schema']['properties']['decisions']['properties']
    tasks['T1']['properties']['selected_head_id']['enum'].append('forged')
    assert not is_attachment_choice_format(malformed)
    assert not matches_attachment_choice_response(value, malformed)
    for invalid in (None, True, [], {'json_schema': {}}):
        assert not is_attachment_choice_format(invalid)
        assert not matches_attachment_choice_response(value, invalid)
    with pytest.raises(ValueError, match='too_large'):
        attachment_choice_format(INPUT, SOURCE, COURSE, 'source', {
            'T' * 66000: {'record_id': 'r', 'modifier_token_id': '0:1', 'allowed_head_token_ids': []}})
