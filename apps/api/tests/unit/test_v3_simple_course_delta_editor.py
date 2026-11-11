import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_delta_editor import (
    apply_simple_delta_editor,
    delta_editor_format,
    is_simple_delta_editor_format,
    matches_simple_delta_editor,
)
from tests.unit.test_v3_simple_course_editor import course, fixture


def setup_delta():
    _, packet = fixture()
    ref = packet.blocks[0].block_id
    original = course(ref=ref, content='Opening.\n\n| Group | Limit |\n| A | 10 |\n\nAdd all same-day entries.')
    original['lessons'][0]['questions'].append({**copy.deepcopy(original['lessons'][0]['questions'][0]), 'id': 'peer'})
    value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
             'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
             'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': [ref]}], 'source_questions': []}
    return packet, original, value


def apply(packet, original, value):
    return apply_simple_delta_editor(value, original, [packet.blocks[0].block_id], packet.fingerprint, _digest(original))


def test_partial_intro_edit_preserves_unaddressed_table_and_aggregation():
    packet, original, value = setup_delta()
    before, wire = copy.deepcopy(original), copy.deepcopy(value)
    value['body_edits'] = [{'lesson_id': 'lesson', 'before': 'Opening.', 'after': 'Improved opening.'}]
    fmt = delta_editor_format([packet.blocks[0].block_id], packet.fingerprint, _digest(original))
    assert is_simple_delta_editor_format(fmt) and matches_simple_delta_editor(value, fmt)
    envelope, receipt = apply(packet, original, value)
    assert envelope['course']['lessons'][0]['content'] == 'Improved opening.' + before['lessons'][0]['content'][len('Opening.'):]
    assert '| A | 10 |' in envelope['course']['lessons'][0]['content'] and 'Add all same-day entries.' in envelope['course']['lessons'][0]['content']
    assert original == before and wire['body_edits'] == []
    assert receipt['body_spans'][0]['start'] == 0 and receipt['semantic_approval'] is False


@pytest.mark.parametrize('fault', ['unknown_lesson', 'stale_anchor', 'ambiguous_anchor', 'overlap', 'blank_anchor'])
def test_invalid_anchors_reject_atomically_without_mutating_inputs(fault):
    packet, original, value = setup_delta()
    if fault == 'ambiguous_anchor':
        original['lessons'][0]['content'] = 'aaaa'
        value['draft_fingerprint'] = _digest(original)
        value['body_edits'] = [{'lesson_id': 'lesson', 'before': 'aa', 'after': 'x'}]
    elif fault == 'overlap':
        value['body_edits'] = [{'lesson_id': 'lesson', 'before': 'Opening.', 'after': 'A'},
                               {'lesson_id': 'lesson', 'before': 'ing.\n\n|', 'after': 'B'}]
    else:
        value['body_edits'] = [{'lesson_id': 'foreign' if fault == 'unknown_lesson' else 'lesson',
            'before': '' if fault == 'blank_anchor' else 'not present', 'after': 'x'}]
    original_before, value_before = copy.deepcopy(original), copy.deepcopy(value)
    with pytest.raises(ValueError):
        apply(packet, original, value)
    assert original == original_before and value == value_before


def test_question_title_addition_and_boundary_insertion_are_scoped():
    packet, original, value = setup_delta()
    question = copy.deepcopy(original['lessons'][0]['questions'][0])
    question['prompt'] = 'Target revised'
    added = copy.deepcopy(original['lessons'][0])
    added['id'] = 'new-lesson'
    for index, row in enumerate(added['questions']):
        row['id'] = f'new-question-{index}'
    value['body_edits'] = [{'lesson_id': 'lesson', 'before': 'Opening.', 'after': 'Opening.\nAdded detail.'}]
    value['title_edits'] = [{'lesson_id': 'lesson', 'title': 'New title'}]
    value['question_edits'] = [{'lesson_id': 'lesson', 'question': question}]
    value['added_lessons'] = [added]
    value['lesson_sources'].append({'lesson_id': 'new-lesson', 'source_refs': [packet.blocks[0].block_id]})
    envelope, receipt = apply(packet, original, value)
    result = envelope['course']
    assert result['title'] == original['title'] and result['lessons'][0]['title'] == 'New title'
    assert result['lessons'][0]['questions'][0]['prompt'] == 'Target revised'
    assert result['lessons'][0]['questions'][1] == original['lessons'][0]['questions'][1]
    assert result['lessons'][1] == added and receipt['added_lesson_ids'] == ['new-lesson']
    assert result['lessons'][0]['content'].endswith('Add all same-day entries.')


@pytest.mark.parametrize('fault', ['wrong_owner', 'unknown_question', 'duplicate_question', 'duplicate_title',
                                   'duplicate_lesson', 'missing_provenance', 'foreign_ref', 'stale_source', 'stale_draft'])
def test_invalid_identity_provenance_or_fingerprint_rejected(fault):
    packet, original, value = setup_delta()
    question = copy.deepcopy(original['lessons'][0]['questions'][0])
    if fault == 'wrong_owner':
        value['question_edits'] = [{'lesson_id': 'foreign', 'question': question}]
    elif fault == 'unknown_question':
        question['id'] = 'foreign'
        value['question_edits'] = [{'lesson_id': 'lesson', 'question': question}]
    elif fault == 'duplicate_question':
        value['question_edits'] = [{'lesson_id': 'lesson', 'question': question}] * 2
    elif fault == 'duplicate_title':
        value['title_edits'] = [{'lesson_id': 'lesson', 'title': 'A'}, {'lesson_id': 'lesson', 'title': 'B'}]
    elif fault == 'duplicate_lesson':
        value['added_lessons'] = [copy.deepcopy(original['lessons'][0])]
    elif fault == 'missing_provenance':
        value['lesson_sources'] = []
    elif fault == 'foreign_ref':
        value['lesson_sources'][0]['source_refs'] = ['foreign']
    elif fault == 'stale_source':
        value['source_fingerprint'] = '0' * 64
    else:
        value['draft_fingerprint'] = '0' * 64
    before = copy.deepcopy(value)
    with pytest.raises(ValueError):
        apply(packet, original, value)
    assert value == before


def test_exact_deletion_is_allowed_if_lesson_remains_valid():
    packet, original, value = setup_delta()
    value['body_edits'] = [{'lesson_id': 'lesson', 'before': 'Opening.\n\n', 'after': ''}]
    envelope, _ = apply(packet, original, value)
    assert envelope['course']['lessons'][0]['content'].startswith('| Group | Limit |')
