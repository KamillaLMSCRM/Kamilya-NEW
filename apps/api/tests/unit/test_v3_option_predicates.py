import copy
import json

import pytest

from app.modules.ai.v3.practical_option_predicates import (
    interpret_option_predicates,
    is_option_predicates_format,
    matches_option_predicates,
    option_predicates_format,
    option_predicates_messages,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def twelve(case):
    _, packet, original = case
    course = copy.deepcopy(original)
    lesson = course['lessons'][0]
    template = lesson['questions'][0]
    lesson['questions'] = [{**copy.deepcopy(template), 'id': f'q{i}', 'prompt': f'Question {i}?',
                            'choices': ['A', 'B', 'C', 'D'], 'correct_index': key}
                           for i, key in ((1, 1), (2, 0), (3, 1))]
    fmt = option_predicates_format(packet, course)
    props = fmt['json_schema']['schema']['properties']
    ids = props['judgments']['items']['properties']['item_id']['enum']
    # Explicit semantic remap of the observed diagnostic, not its native response.
    supported = {1, 3, 4, 9}
    value = {'source_fingerprint': packet.fingerprint, 'bank_fingerprint': props['bank_fingerprint']['enum'][0],
             'judgments': [{'item_id': key, 'status': 'SUPPORTED' if i in supported else 'NOT_SUPPORTED',
                 'reason': 'Judged against the source.', 'source_refs': [packet.blocks[0].block_id],
                 'compatible_case': 'Source-described workflow' if i in supported else ''} for i, key in enumerate(ids)]}
    return packet, course, fmt, value


def test_adapted_twelve_judgments_preserve_multiple_answers_and_key_reinterpretation(case):
    packet, course, fmt, value = twelve(case)
    assert is_option_predicates_format(fmt) and matches_option_predicates(value, fmt)
    decision = interpret_option_predicates(value, packet, course)
    assert not decision.accepted and not decision.source_uncertain
    assert decision.question_ids == ('q1',)
    evidence = decision.feedback[0]['evidence']
    assert evidence['supported_options'] == [1, 3]
    assert evidence['option_judgments'][0]['source_blocks'][0]['text'] == packet.blocks[0].text
    changed = copy.deepcopy(course)
    changed['lessons'][0]['questions'][1]['correct_index'] = 2
    assert option_predicates_format(packet, changed) == fmt
    assert interpret_option_predicates(value, packet, changed).question_ids == ('q1', 'q2')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'foreign', 'source_fp', 'bank_fp', 'foreign_ref', 'empty_positive_ref'])
def test_custody_and_exact_inventory_fail_closed(case, fault):
    packet, course, fmt, value = twelve(case)
    if fault == 'missing':
        value['judgments'].pop()
    elif fault == 'duplicate':
        value['judgments'][1]['item_id'] = value['judgments'][0]['item_id']
    elif fault == 'foreign':
        value['judgments'][0]['item_id'] = 'foreign'
    elif fault == 'source_fp':
        value['source_fingerprint'] = 'a' * 64
    elif fault == 'bank_fp':
        value['bank_fingerprint'] = 'b' * 64
    elif fault == 'foreign_ref':
        value['judgments'][1]['source_refs'] = ['foreign']
    else:
        value['judgments'][1]['source_refs'] = []
    assert not matches_option_predicates(value, fmt)
    with pytest.raises(ValueError, match='option_predicates_response_invalid'):
        interpret_option_predicates(value, packet, course)


def test_prompt_and_bank_exclude_key_prose_explanations_and_other_choices(case):
    packet, course, fmt, _ = twelve(case)
    first = course['lessons'][0]
    first['content'] = 'PRIVATE LESSON PROSE'
    first['questions'][0]['explanation'] = 'PRIVATE ANSWER EXPLANATION'
    messages = option_predicates_messages(packet, course, 'Original source')
    serialized = json.dumps(messages)
    assert 'PRIVATE LESSON PROSE' not in serialized and 'PRIVATE ANSWER EXPLANATION' not in serialized
    assert 'correct_index' not in serialized
    items = json.loads(messages[1]['content'].split('INDEPENDENT_ITEMS_JSON\n')[1].split('\nFULL_ORIGINAL_SOURCE')[0])
    assert len(items) == 12 and all(set(item) == {'item_id', 'prompt', 'candidate_answer'} for item in items)
    assert option_predicates_format(packet, course) == fmt


def test_unknown_and_unestablished_workflow_do_not_invent_owner_questions(case):
    packet, course, _, value = twelve(case)
    value['judgments'][3].update(status='NOT_ESTABLISHED', compatible_case='')
    value['judgments'][8].update(status='UNDECIDABLE', compatible_case='')
    result = interpret_option_predicates(value, packet, course)
    assert result.question_ids == () and not result.source_uncertain
    assert result.feedback[0]['id'] == 'q3' and result.feedback[0]['evidence']['rule_check_unverified']
    assert all(row['scope'] == 'question' for row in result.feedback)


def test_hidden_unresolved_source_tokens_do_not_break_displayed_bank(case):
    packet, course, fmt, value = twelve(case)
    course['lessons'][0]['content'] = 'Hidden SRC999 prose.'
    course['lessons'][0]['questions'][0]['explanation'] = 'Hidden SRC999 explanation.'
    assert option_predicates_format(packet, course) == fmt
    assert interpret_option_predicates(value, packet, course).question_ids == ('q1',)
    course['lessons'][0]['questions'][0]['prompt'] = 'Visible SRC999 question?'
    with pytest.raises(ValueError):
        option_predicates_format(packet, course)


def test_confirmed_multiple_or_wrong_key_stays_editable_even_with_uncertainty(case):
    packet, course, _, value = twelve(case)
    value['judgments'][0].update(status='UNDECIDABLE', compatible_case='')
    value['judgments'][4].update(status='NOT_SUPPORTED', compatible_case='')
    value['judgments'][5].update(status='SUPPORTED', compatible_case='Actual source case')
    value['judgments'][6].update(status='UNDECIDABLE', compatible_case='')
    result = interpret_option_predicates(value, packet, course)
    assert result.question_ids == ('q1', 'q2')
    assert all(not row['evidence']['rule_check_unverified'] for row in result.feedback)


def test_zero_confirmed_answers_with_undecidable_candidate_is_review_hold(case):
    packet, course, _, value = twelve(case)
    for row in value['judgments'][:4]:
        row.update(status='NOT_SUPPORTED', compatible_case='')
    value['judgments'][1].update(status='UNDECIDABLE')
    decision = interpret_option_predicates(value, packet, course)
    assert not decision.accepted and not decision.source_uncertain
    assert not decision.question_ids
    assert decision.feedback[0]['evidence']['rule_check_unverified']


@pytest.mark.asyncio
async def test_native_contract_checkpoint_reuses_owned_completed_response(case):
    from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_partitioned_extraction import Journal

    packet, course, fmt, value = twelve(case)
    assert response_contract(fmt) == 'practical_option_predicates'
    assert matches_response_contract(value, fmt)
    calls = []

    async def invoke():
        calls.append(True)
        return value

    kwargs = dict(journal=Journal(), stage='review', group_id='practical:review:option-predicates:v33:synthetic',
                  source_sha256=packet.fingerprint, route_fingerprint='b' * 64,
                  messages=option_predicates_messages(packet, course, 'Original source'), response_format=fmt,
                  response_validator=lambda v: interpret_option_predicates(v, packet, course), invoke=invoke)
    assert await stage_once(**kwargs) == value
    assert await stage_once(**kwargs) == value
    assert len(calls) == 1
