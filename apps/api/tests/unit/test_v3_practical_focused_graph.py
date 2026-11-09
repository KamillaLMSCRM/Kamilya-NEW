import copy
import json
import sys
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3 import practical_action_object_graph as graph
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_focused_graph import action_query, focused_editor_request, graph_records, noun_query
from app.modules.ai.v3.practical_model_view import PracticalModelView


@pytest.fixture
def focused_case():
    text = 'Не касаться поверхности.'
    doc = DirectSourceDocument('doc', 'Source', 'file', 'other', 'r', (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(text), 0))
    view = PracticalModelView(packet)
    question = {'id': 'q', 'prompt': 'QUESTION_PRIVATE_SENTINEL', 'choices': ['a', 'b', 'c'],
                'correct_index': 0, 'explanation': 'Reason', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'lesson', 'title': 'Title',
              'content': 'Не касаться ограждения.', 'questions': [question]}]}
    return packet, view, course


def make_graph(role, records, object_quote):
    _, _, local = graph.request(role, records)
    rows = [{'token_id': t['token_id'], 'classification': 'OPERATIVE', 'object_kind': 'OBJECT',
             'object_quote': object_quote, 'negation_quote': 'Не касаться', 'note': ''} for t in local['candidates']]
    value = {'role': role, 'input_fingerprint': local['input_fingerprint'], 'decisions': rows}
    return graph.compile_response(value, role, records)


def test_separate_graphs_retrieve_only_unverified_exact_context(focused_case):
    packet, view, course = focused_case
    source, learner, _ = graph_records(packet, course, view)
    sg, lg = make_graph('source', source, 'поверхности'), make_graph('learner', learner, 'ограждения')
    query = action_query(packet, course, course, view, sg, lg)
    assert len(query['pairs']) == 1 and not query['semantic_acceptance']
    messages, fmt, allowed = focused_editor_request(packet, course, view, query, 'action')
    assert allowed == ['lesson'] and fmt['json_schema']['strict']
    assert 'QUESTION_PRIVATE_SENTINEL' not in str(messages)
    assert 'поверхности' in messages[1]['content'] and 'ограждения' in messages[1]['content']
    stale = copy.deepcopy(course)
    stale['lessons'][0]['content'] = 'Different text.'
    stale_query = action_query(packet, course, stale, view, sg, lg)
    assert not stale_query['pairs'] and stale_query['current_unknown_observations']
    assert focused_editor_request(packet, stale, view, stale_query, 'action') == (None, None, [])
    altered = copy.deepcopy(sg)
    altered['records'][0]['text'] = 'forged'
    with pytest.raises(ValueError, match='custody'):
        action_query(packet, course, course, view, altered, lg)


def test_noun_head_rebind_uses_exact_current_context_and_preserves_unknown(focused_case, monkeypatch):
    packet, view, original = focused_case
    source_text = packet.blocks[0].text
    learner_text = original['lessons'][0]['content']
    def wid(text, word):
        start = text.index(word)
        return f'W{start}_{start + len(word)}'
    source_mod, learner_mod = wid(source_text, 'касаться'), wid(learner_text, 'касаться')
    pair = {'source_task_id': 'SRC1:' + source_mod, 'learner_task_id': 'lesson:' + learner_mod,
            'source_selected_head_id': wid(source_text, 'поверхности'),
            'learner_selected_head_id': wid(learner_text, 'ограждения'), 'status': 'FLAGGED_UNVERIFIED',
            'origins': [{'source_segment': [0, len(source_text)], 'learner_segment': [0, len(learner_text)],
                         'selected_instance_relation': 'DIFFERENT_ALIGNED_POSITION_UNVERIFIED'}]}
    fake = SimpleNamespace(compile_choices=lambda *_args: {'pairs': [pair], 'semantic_acceptance': False})
    monkeypatch.setitem(sys.modules, 'app.modules.ai.v3.practical_attachment_planner', fake)
    query = noun_query(packet, original, original, view, {}, [], [])
    assert query['noun_observations'][0]['current']['status'] == 'UNVERIFIED'
    _, _, allowed = focused_editor_request(packet, original, view, query, 'noun')
    assert allowed == ['lesson']
    pair['origins'][0]['selected_instance_relation'] = 'SAME_ALIGNED_POSITION_UNVERIFIED'
    aligned = noun_query(packet, original, original, view, {}, [], [])
    assert not aligned['noun_observations'] and aligned['aligned_selections_unknown'] == 1
    assert focused_editor_request(packet, original, view, aligned, 'noun') == (None, None, [])
    aligned_origin = copy.deepcopy(pair['origins'][0])
    differing_origin = {**aligned_origin, 'selected_instance_relation': 'DIFFERENT_ALIGNED_POSITION_UNVERIFIED'}
    for origins in ([aligned_origin, differing_origin], [differing_origin, aligned_origin]):
        pair['origins'] = origins
        mixed = noun_query(packet, original, original, view, {}, [], [])
        assert not mixed['noun_observations'] and mixed['aligned_selections_unknown'] == 1
        assert focused_editor_request(packet, original, view, mixed, 'noun') == (None, None, [])
    pair['origins'] = [aligned_origin]
    pair['origins'][0]['selected_instance_relation'] = 'UNKNOWN'
    unresolved = noun_query(packet, original, original, view, {}, [], [])
    note = unresolved['noun_observations'][0]
    assert note['source']['status'] == note['current']['status'] == 'UNKNOWN'
    assert 'exact_owned_context' not in note['source'] and 'exact_owned_context' not in note['current']
    assert focused_editor_request(packet, original, view, unresolved, 'noun') == (None, None, [])
    pair['origins'][0]['selected_instance_relation'] = 'DIFFERENT_ALIGNED_POSITION_UNVERIFIED'
    altered = copy.deepcopy(original)
    altered['lessons'][0]['content'] = 'Changed text.'
    query = noun_query(packet, original, altered, view, {}, [], [])
    assert query['noun_observations'][0]['current']['status'] == 'UNKNOWN'
    assert focused_editor_request(packet, altered, view, query, 'noun') == (None, None, [])
    changed_questions = copy.deepcopy(original)
    changed_questions['lessons'][0]['questions'][0]['prompt'] = 'changed'
    with pytest.raises(ValueError, match='protected_fields'):
        noun_query(packet, original, changed_questions, view, {}, [], [])


def test_noun_editor_receives_owned_bodies_and_protects_unrelated_lessons(focused_case):
    packet, view, course = focused_case
    unrelated = copy.deepcopy(course['lessons'][0])
    unrelated['id'] = 'unrelated'
    unrelated['content'] = 'UNRELATED_BODY_PRIVATE_SENTINEL'
    unrelated['questions'][0]['id'] = 'unrelated-q'
    course['lessons'].append(unrelated)
    query = {'noun_observations': [{'source_unit_id': view.canonical_to_alias[packet.blocks[0].block_id],
        'lesson_id': 'lesson', 'source': {'status': 'UNVERIFIED'}, 'current': {'status': 'UNVERIFIED'}}]}
    messages, schema, allowed = focused_editor_request(packet, course, view, query, 'noun')
    data = json.loads(messages[1]['content'])
    assert allowed == ['lesson']
    assert [row['id'] for row in data['CURRENT_LESSONS']] == ['lesson']
    assert [row['id'] for row in data['PROTECTED_COURSE_OUTLINE']] == ['lesson', 'unrelated']
    assert 'UNRELATED_BODY_PRIVATE_SENTINEL' not in str(messages)
    assert 'QUESTION_PRIVATE_SENTINEL' not in str(messages)
    assert schema['json_schema']['schema']['properties']['updates']['items']['properties']['lesson_id']['enum'] == allowed


@pytest.mark.parametrize(('source_text', 'lesson_text', 'source_object', 'lesson_object', 'source_negative',
                          'lesson_negative', 'expected_pairs'), [
    ('Автор не проверяет запись.', 'Можно проверять запись.', 'запись', 'запись', 'не проверяет', '', 0),
    ('Автор не проверяет запись.', 'Читатель не проверяет запись.', 'запись', 'запись', 'не проверяет', 'не проверяет', 0),
    ('Автор не проверяет запись.', 'Автор не проверяет бланк.', 'запись', 'бланк', 'не проверяет', 'не проверяет', 1),
    ('Автор не проверяет запись и сохраняет копию.', 'Автор не проверяет запись.', 'запись', 'запись',
     'не проверяет', 'не проверяет', 0),
    ('Автор не проверяет запись.', 'Автор не осуществляет проверку записи.', 'запись', 'записи',
     'не проверяет', 'не осуществляет', 0),
])
def test_narrow_retrieval_never_converts_absence_to_coverage(source_text, lesson_text, source_object,
                                                              lesson_object, source_negative, lesson_negative,
                                                              expected_pairs):
    doc = DirectSourceDocument('doc', 'Source', 'file', 'other', 'r', (), source_text=source_text)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source_text), 0))
    view = PracticalModelView(packet)
    question = {'id': 'q', 'prompt': 'Question?', 'choices': ['a', 'b', 'c'], 'correct_index': 0,
                'explanation': 'Reason', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'lesson', 'title': 'Title', 'content': lesson_text,
                                               'questions': [question]}]}
    source, learner, _ = graph_records(packet, course, view)
    def model_reading(role, records, obj, negative):
        _, _, local = graph.request(role, records)
        value = {'role': role, 'input_fingerprint': local['input_fingerprint'], 'decisions': [
            {'token_id': t['token_id'], 'classification': 'OPERATIVE', 'object_kind': 'OBJECT',
             'object_quote': obj, 'negation_quote': negative, 'note': ''} for t in local['candidates']]}
        return graph.compile_response(value, role, records)
    result = action_query(packet, course, course, view, model_reading('source', source, source_object, source_negative),
                          model_reading('learner', learner, lesson_object, lesson_negative))
    assert len(result['pairs']) == expected_pairs and not result['semantic_acceptance']
    assert 'UNKNOWN' in result['coverage_limits']
