"""Context supplements retain the original owned prompt and course bytes."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_context import (
    apply_context_supplements,
    context_format,
    context_messages,
    is_context_format,
    matches_context_response,
    retained_context_unresolved,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def response(fmt):
    props = fmt['json_schema']['schema']['properties']
    return {'source_fingerprint': props['source_fingerprint']['enum'][0],
            'course_fingerprint': props['course_fingerprint']['enum'][0],
            'supplements': {qid: '' for qid in props['supplements']['properties']},
            'context_source_refs': [],
            'unresolved_question_ids': []}


def test_add_only_preserves_negation_events_and_logical_connectives(case):
    _, packet, course = case
    course = copy.deepcopy(course)
    q = course['lessons'][0]['questions'][0]
    q['prompt'] = 'After handover, the person did NOT sign AND did not record OR notify. What next?'
    original = copy.deepcopy(course)
    fmt = context_format(packet, course, ['q1', 'q2'])
    value = response(fmt)
    value['supplements']['q1'] = 'The office is outside the locality.'
    value['context_source_refs'] = [{'question_id': 'q1', 'source_refs': [packet.blocks[0].block_id]}]
    value['unresolved_question_ids'] = ['q2']
    updated, unresolved = apply_context_supplements(packet, course, ['q2', 'q1'], value)
    assert unresolved == ('q2',)
    assert updated['lessons'][0]['questions'][0]['prompt'] == 'The office is outside the locality.\n\n' + q['prompt']
    updated['lessons'][0]['questions'][0]['prompt'] = q['prompt']
    assert updated == original and course == original


def test_messages_project_whole_course_without_private_answers(case):
    _, packet, course = case
    course = copy.deepcopy(course)
    course['lessons'][0]['content'] = 'VISIBLE_LESSON_PROSE'
    course['lessons'][0]['questions'][0]['explanation'] = 'HIDDEN_AUTHOR_EXPLANATION'
    view = PracticalModelView(packet)
    messages = context_messages(packet, course, ['q2', 'q1'], model_view=view)
    body = json.loads(messages[1]['content'].split('\nCOURSE_CONTEXT_JSON\n')[1])
    assert body['question_ids'] == ['q1', 'q2']
    assert body['course']['lessons'][0]['content'] == 'VISIBLE_LESSON_PROSE'
    assert 'HIDDEN_AUTHOR_EXPLANATION' not in messages[1]['content']
    for lesson in body['course']['lessons']:
        for q in lesson['questions']:
            assert set(q) == {'id', 'prompt', 'choices'}


def test_format_is_canonical_closed_and_reconstructs(case):
    _, packet, course = case
    first = context_format(packet, course, ['q1', 'q2'])
    assert first == context_format(packet, course, ['q2', 'q1'])
    assert context_messages(packet, course, ['q1', 'q2']) == context_messages(packet, course, ['q2', 'q1'])
    assert is_context_format(first) and matches_context_response(response(first), first)
    tampered = copy.deepcopy(first)
    tampered['json_schema']['schema']['properties']['supplements']['additionalProperties'] = True
    assert not is_context_format(tampered)
    with pytest.raises(ValueError):
        context_format(packet, course, ['q1', 'q1'])
    with pytest.raises(ValueError):
        context_format(packet, course, ['foreign'])
    with pytest.raises(ValueError):
        context_format(packet, course, [])


@pytest.mark.parametrize('defect', ['foreign', 'missing', 'duplicate_unresolved', 'unresolved_with_text',
                                    'wrong_source', 'wrong_course', 'blank', 'extra', 'missing_refs',
                                    'foreign_ref', 'duplicate_ref', 'duplicate_record', 'empty_supplement_ref'])
def test_invalid_response_fails_closed(case, defect):
    _, packet, course = case
    fmt = context_format(packet, course, ['q1', 'q2'])
    value = response(fmt)
    if defect == 'foreign':
        value['unresolved_question_ids'] = ['foreign']
    elif defect == 'missing':
        del value['supplements']['q1']
    elif defect == 'duplicate_unresolved':
        value['unresolved_question_ids'] = ['q1', 'q1']
    elif defect == 'unresolved_with_text':
        value['unresolved_question_ids'], value['supplements']['q1'] = ['q1'], 'text'
    elif defect == 'wrong_source':
        value['source_fingerprint'] = '0' * 64
    elif defect == 'wrong_course':
        value['course_fingerprint'] = '0' * 64
    elif defect == 'blank':
        value['supplements']['q1'] = '  '
    elif defect == 'extra':
        value['supplements']['foreign'] = ''
    elif defect == 'missing_refs':
        value['supplements']['q1'] = 'Context.'
    else:
        value['supplements']['q1'] = 'Context.'
        value['context_source_refs'] = [{'question_id': 'q1', 'source_refs': [packet.blocks[0].block_id]}]
        if defect == 'foreign_ref':
            value['context_source_refs'][0]['source_refs'] = ['foreign']
        elif defect == 'duplicate_ref':
            value['context_source_refs'][0]['source_refs'] *= 2
        elif defect == 'duplicate_record':
            value['context_source_refs'].append(copy.deepcopy(value['context_source_refs'][0]))
        else:
            value['supplements']['q1'] = ''
    assert not matches_context_response(value, fmt)
    with pytest.raises(ValueError, match='practical_context_response_invalid'):
        apply_context_supplements(packet, course, ['q1', 'q2'], value)


def test_stale_course_and_partial_unresolved_retention(case):
    _, packet, course = case
    value = response(context_format(packet, course, ['q1']))
    altered = copy.deepcopy(course)
    altered['lessons'][0]['questions'][0]['prompt'] += ' Changed.'
    with pytest.raises(ValueError, match='practical_context_response_invalid'):
        apply_context_supplements(packet, altered, ['q1'], value)
    assert retained_context_unresolved(('q1', 'q2'), ('q1',), ()) == ('q2',)
    assert retained_context_unresolved(('q1', 'q2'), ('q1',), ('q1',)) == ('q1', 'q2')
    with pytest.raises(ValueError):
        retained_context_unresolved(('q1',), ('q2',), ('q1',))


def test_multidocument_supplement_never_misattributes_b_only_fact_to_a_quote(case):
    from dataclasses import replace
    from hashlib import sha256

    from app.modules.ai.direct_source import DirectSourceCorpus
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    corpus, _, course = case
    source_b = 'Only document B establishes a remote-office condition.'
    other = replace(corpus.documents[0], doc_id='doc-b', title='B', source_text=source_b,
                    source_revision='document:' + sha256(source_b.encode()).hexdigest())
    combined = DirectSourceCorpus(corpus.tenant_id, (*corpus.documents, other),
                                  corpus.total_chars + len(source_b), 0)
    packet = build_practical_source_packet(combined)
    assert len(packet.source_documents) == 2
    # The unchanged question cites only A, but the proposed premise is from B.
    fmt = context_format(packet, course, ['q1'])
    value = response(fmt)
    value['supplements']['q1'] = 'The office has the B-only remote status.'
    block_b = next(block.block_id for block in packet.blocks if block.doc_id == 'doc-b')
    value['context_source_refs'] = [{'question_id': 'q1', 'source_refs': [block_b]}]
    held, unresolved = apply_context_supplements(packet, course, ['q1'], value)
    assert held == course and unresolved == ('q1',)
    assert held['lessons'][0]['questions'][0]['source_refs'] == course['lessons'][0]['questions'][0]['source_refs']
    # No invented single-document provenance and no unnecessary hold for no-op.
    value['supplements']['q1'] = ''
    value['context_source_refs'] = []
    unchanged, unresolved = apply_context_supplements(packet, course, ['q1'], value)
    assert unchanged == course and unresolved == ()


def test_same_document_supplement_extends_source_refs_without_reordering(case):
    _, packet, course = case
    course = copy.deepcopy(course)
    q = course['lessons'][0]['questions'][0]
    assert len(packet.blocks) >= 2
    first, second = (packet.blocks[0].block_id, packet.blocks[1].block_id)
    q['source_refs'] = [first]
    value = response(context_format(packet, course, ['q1']))
    value['supplements']['q1'] = 'Approval has been recorded.'
    value['context_source_refs'] = [{'question_id': 'q1', 'source_refs': [second, first]}]
    result, unresolved = apply_context_supplements(packet, course, ['q1'], value)
    updated = result['lessons'][0]['questions'][0]
    assert unresolved == () and updated['source_refs'] == [first, second]
    assert updated['prompt'] == 'Approval has been recorded.\n\n' + q['prompt']
    assert q['source_refs'] == [first]


def test_aliased_schema_roundtrip_uses_one_shared_source_inventory():
    import hashlib

    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    text = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(1000))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(text.encode()).hexdigest(), (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
                  'correct_index': 0, 'explanation': 'Explanation.', 'source_refs': [packet.blocks[0].block_id]}
                 for i in range(100)]
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text.', 'questions': questions}]}
    fmt = context_format(packet, course, [q['id'] for q in questions])
    view = PracticalModelView(packet)
    wire = view.schema(fmt)
    assert is_context_format(fmt) and is_context_format(wire)
    props = wire['json_schema']['schema']['properties']
    assert len(props['context_source_refs']['items']['properties']['source_refs']['items']['enum']) == 1000
    assert json.dumps(wire).count('SRC1000') == 1
    value = response(wire)
    value['supplements']['q0'] = 'Context.'
    value['context_source_refs'] = [{'question_id': 'q0', 'source_refs': ['SRC2']}]
    assert matches_context_response(value, wire)
    decoded = view.decode(value)
    updated, unresolved = apply_context_supplements(packet, course, ['q' + str(i) for i in range(100)], decoded)
    assert unresolved == () and updated['lessons'][0]['questions'][0]['source_refs'] == [packet.blocks[0].block_id, packet.blocks[1].block_id]
