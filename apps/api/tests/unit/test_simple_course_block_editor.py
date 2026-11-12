import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_block_editor import (
    apply_simple_block_editor,
    block_editor_format,
    body_blocks,
    is_simple_block_editor_format,
    matches_simple_block_editor,
)
from tests.unit.test_v3_simple_course_editor import course, fixture


def setup_block():
    _, packet = fixture()
    ref = packet.blocks[0].block_id
    original = course(ref=ref, content='Repeated.\r\n\r\nRepeated.\r\n \t\r\nТаблица\n| A | Б |')
    second = copy.deepcopy(original['lessons'][0])
    second['id'] = 'other'
    second['content'] = 'Repeated.\n\nSeparate.'
    second['questions'][0]['id'] = 'other-question'
    original['lessons'].append(second)
    value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
             'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
             'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': [ref]},
                                {'lesson_id': 'other', 'source_refs': [ref]}], 'source_questions': []}
    return packet, original, value


def apply(packet, original, value):
    return apply_simple_block_editor(value, original, [packet.blocks[0].block_id], packet.fingerprint, _digest(original))


def test_repeated_paragraphs_have_distinct_stable_physical_owners_and_crlf_offsets():
    packet, original, value = setup_block()
    before, wire_before = copy.deepcopy(original), copy.deepcopy(value)
    blocks = body_blocks(original)
    assert [row['id'] for row in blocks] == ['BODY1', 'BODY2', 'BODY3', 'BODY4', 'BODY5']
    assert [row['text'] for row in blocks] == ['Repeated.', 'Repeated.', 'Таблица\n| A | Б |', 'Repeated.', 'Separate.']
    for row in blocks:
        body = next(lesson['content'] for lesson in original['lessons'] if lesson['id'] == row['lesson_id'])
        assert body[row['start']:row['end']] == row['text']
    value['body_edits'] = [{'block_id': 'BODY2', 'after': 'Второй.\n\nMore detail.'},
                           {'block_id': 'BODY4', 'after': 'Other lesson.'}]
    fmt = block_editor_format([packet.blocks[0].block_id], packet.fingerprint, _digest(original), [row['id'] for row in blocks])
    assert is_simple_block_editor_format(fmt) and matches_simple_block_editor(value, fmt)
    envelope, receipt = apply(packet, original, value)
    assert envelope['course']['lessons'][0]['content'] == 'Repeated.\r\n\r\nВторой.\n\nMore detail.\r\n \t\r\nТаблица\n| A | Б |'
    assert envelope['course']['lessons'][1]['content'] == 'Other lesson.\n\nSeparate.'
    assert [row['block_id'] for row in receipt['body_spans']] == ['BODY2', 'BODY4']
    assert receipt['semantic_approval'] is False and receipt['result_fingerprint'] == _digest(envelope['course'])
    assert original == before and wire_before['body_edits'] == []


def test_combined_question_owner_title_and_added_lesson_are_scoped():
    packet, original, value = setup_block()
    question = copy.deepcopy(original['lessons'][1]['questions'][0])
    question['prompt'] = 'Edited question'
    added = copy.deepcopy(original['lessons'][0])
    added['id'], added['questions'][0]['id'] = 'new-lesson', 'new-question'
    value['question_edits'] = [question]
    value['title_edits'] = [{'lesson_id': 'lesson', 'title': 'Revised title'}]
    value['body_edits'] = [{'block_id': 'BODY1', 'after': 'Revised.'}]
    value['added_lessons'] = [added]
    value['lesson_sources'].append({'lesson_id': 'new-lesson', 'source_refs': [packet.blocks[0].block_id]})
    result, receipt = apply(packet, original, value)
    lessons = result['course']['lessons']
    assert lessons[0]['title'] == 'Revised title' and lessons[0]['content'].startswith('Revised.')
    assert lessons[0]['questions'] == original['lessons'][0]['questions']
    assert lessons[1]['questions'][0]['prompt'] == 'Edited question' and lessons[2] == added
    assert receipt['question_ids'] == ['other-question'] and receipt['added_lesson_ids'] == ['new-lesson']


def test_single_crlf_is_not_a_blank_separator():
    _, original, _ = setup_block()
    original['lessons'][0]['content'] = 'First\r\nSecond\r\n| A | Б |\r\n\r\nNext'
    blocks = [row['text'] for row in body_blocks(original) if row['lesson_id'] == 'lesson']
    assert blocks == ['First\r\nSecond\r\n| A | Б |', 'Next']


@pytest.mark.parametrize('fault', ['unknown_block', 'duplicate_block', 'unknown_question', 'duplicate_question',
                                   'foreign_ref', 'missing_provenance', 'stale_source', 'stale_draft'])
def test_invalid_block_scope_or_fingerprint_fails_without_mutation(fault):
    packet, original, value = setup_block()
    if fault == 'unknown_block':
        value['body_edits'] = [{'block_id': 'BODY99', 'after': 'x'}]
    elif fault == 'duplicate_block':
        value['body_edits'] = [{'block_id': 'BODY1', 'after': 'x'}] * 2
    elif fault == 'unknown_question':
        question = copy.deepcopy(original['lessons'][0]['questions'][0])
        question['id'] = 'foreign'
        value['question_edits'] = [question]
    elif fault == 'duplicate_question':
        value['question_edits'] = [copy.deepcopy(original['lessons'][0]['questions'][0])] * 2
    elif fault == 'foreign_ref':
        value['lesson_sources'][0]['source_refs'] = ['foreign']
    elif fault == 'missing_provenance':
        value['lesson_sources'] = []
    elif fault == 'stale_source':
        value['source_fingerprint'] = '0' * 64
    else:
        value['draft_fingerprint'] = '0' * 64
    before, wire = copy.deepcopy(original), copy.deepcopy(value)
    with pytest.raises(ValueError):
        apply(packet, original, value)
    assert original == before and value == wire


def test_stale_course_and_invalid_deletion_fail_closed():
    packet, original, value = setup_block()
    changed = copy.deepcopy(original)
    changed['lessons'][0]['content'] += ' stale'
    with pytest.raises(ValueError, match='draft_stale'):
        apply_simple_block_editor(value, changed, [packet.blocks[0].block_id], packet.fingerprint, _digest(original))
    value['body_edits'] = [{'block_id': 'BODY4', 'after': ''}, {'block_id': 'BODY5', 'after': ''}]
    with pytest.raises(ValueError):
        apply(packet, original, value)
