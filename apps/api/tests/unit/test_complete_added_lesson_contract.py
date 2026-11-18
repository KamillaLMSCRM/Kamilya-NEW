import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.response_contracts import matches_transport_contract, response_contract
from app.modules.ai.v3.simple_course_block_editor import (
    block_editor_format,
    body_blocks,
    complete_added_lesson_format,
)
from tests.unit.test_simple_course_block_editor import setup_block


def fixture():
    packet, original, proposal = setup_block()
    ids = [packet.blocks[0].block_id]
    fmt = block_editor_format(ids, packet.fingerprint, _digest(original), [b['id'] for b in body_blocks(original)])
    added = copy.deepcopy(original['lessons'][0])
    added['id'], added['questions'][0]['id'] = 'added', 'added-question'
    proposal['body_edits'] = [{'block_id': 'BODY1', 'after': 'Valid independent correction.'}]
    proposal['added_lessons'] = [added]
    proposal['lesson_sources'].append({'lesson_id': 'added', 'source_refs': ids})
    return packet, original, proposal, fmt


def test_saved_failure_shape_rejected_by_actual_emitted_contract_before_application():
    _, _, proposal, legacy = fixture()
    before = copy.deepcopy(legacy)
    assert matches_transport_contract(proposal, legacy)
    complete = complete_added_lesson_format(legacy)
    assert complete['json_schema']['name'] == 'simple_course_block_editor_v3'
    assert response_contract(complete) == 'simple_course_block_editor'
    assert not matches_transport_contract(proposal, complete)
    assert legacy == before


@pytest.mark.parametrize('count', [3, 4, 5])
def test_complete_added_lesson_keeps_existing_edits_and_every_original_card(count):
    packet, original, proposal, fmt = fixture()
    from app.modules.ai.v3.simple_course_block_editor import apply_simple_block_editor

    lesson = proposal['added_lessons'][0]
    lesson['questions'] = [dict(copy.deepcopy(lesson['questions'][0]), id=f'added-{i}') for i in range(count)]
    assert matches_transport_contract(proposal, complete_added_lesson_format(fmt))
    result, _ = apply_simple_block_editor(proposal, original, [packet.blocks[0].block_id], packet.fingerprint, _digest(original))
    assert result['course']['lessons'][0]['content'].startswith('Valid independent correction.')
    assert result['course']['lessons'][0]['questions'] == original['lessons'][0]['questions']
    assert result['course']['lessons'][1] == original['lessons'][1]
    assert result['course']['lessons'][2] == lesson


def test_no_unregistered_structural_variant():
    _, _, _, fmt = fixture()
    changed = complete_added_lesson_format(fmt)
    changed['json_schema']['schema']['properties']['added_lessons']['items']['properties']['questions']['minItems'] = 2
    assert response_contract(changed) is None
