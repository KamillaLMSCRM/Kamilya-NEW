"""Standalone examiner sees the same question that a candidate can see."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    STANDALONE_NAME,
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from tests.unit.test_v3_practical_concise_review import concise_review

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def response(packet, course):
    value = concise_review(packet, course)
    value['question_sources'] = value.pop('narrative_sources')
    return value


def test_standalone_view_omits_lesson_context_even_in_prior(case):
    _, packet, course = case
    course = copy.deepcopy(course)
    lesson = course['lessons'][0]
    course['title'] = 'PRIVATE_COURSE_TITLE'
    lesson['title'] = 'PRIVATE_LESSON_TITLE'
    lesson['content'] = 'PRIVATE_LESSON_BODY'
    lesson['questions'][0]['prompt'] = 'In the stated case, what is required?'
    lesson['questions'][0]['explanation'] = 'PRIVATE_EXPLANATION'
    old = copy.deepcopy(course)
    previous = ({'issue_id': 'issue-one', 'scope': 'question', 'id': 'q1',
                 'evidence': {'problem': 'PRIVATE_LESSON_BODY', 'author_key': 0}},)
    view = PracticalModelView(packet)
    msg = practical_review_messages(packet, course, previous, model_view=view,
                                    concise=True, strict_targets=True, standalone=True)
    content = msg[1]['content']
    candidate, prior = content.split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')
    payload = json.loads(candidate)
    assert payload['lesson_id'] == lesson['id']
    assert payload['questions'][0] == {'id': 'q1', 'prompt': lesson['questions'][0]['prompt'],
                                        'choices': lesson['questions'][0]['choices']}
    assert json.loads(prior) == [{'issue_id': 'issue-one', 'scope': 'question', 'id': 'q1'}]
    assert all(word not in content for word in ('PRIVATE_COURSE_TITLE', 'PRIVATE_LESSON_TITLE',
                                                 'PRIVATE_LESSON_BODY', 'PRIVATE_EXPLANATION',
                                                 'correct_index', 'source_refs', 'author_key'))
    assert course == old
    assert all(block.text in content for block in packet.blocks)


def test_closed_schema_and_question_only_authority(case):
    _, packet, course = case
    fmt = practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True)
    assert fmt['json_schema']['name'] == STANDALONE_NAME and is_practical_review_format(fmt)
    props = fmt['json_schema']['schema']['properties']
    assert 'question_sources' in props and 'narrative_sources' not in props
    value = response(packet, course)
    assert matches_practical_review(value, fmt)
    value['answerability'][0].update(status='DEPENDS', possible_options=[0, 1])
    decision = interpret_practical_review(value, packet, course, concise=True, strict_targets=True, standalone=True)
    assert not decision.accepted and decision.question_ids == ('q1',)
    assert not decision.lesson_ids and not decision.assessment_lesson_ids and not decision.allow_new_lessons
    value['findings'] = [{'scope': 'lesson', 'target_id': 'l1', 'problem': 'x',
                          'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'y', 'correction': 'z'}]
    assert not matches_practical_review(value, fmt)
    for mutate in ('foreign_source', 'extra_scope', 'wrong_name'):
        altered = copy.deepcopy(fmt)
        if mutate == 'foreign_source':
            items = altered['json_schema']['schema']['properties']['question_sources']['properties']['l1']['items']
            items['enum'] = [*items['enum'], 'foreign']
        elif mutate == 'extra_scope':
            altered['json_schema']['schema']['properties']['findings']['items']['anyOf'][0]['properties']['scope']['enum'].append('lesson')
        else:
            altered['json_schema']['name'] = 'unknown'
        assert not is_practical_review_format(altered)


def test_conditional_answer_is_not_reported_as_a_second_unknown_key_error(case):
    _, packet, course = case
    value = response(packet, course)
    value['answer_keys']['q1'] = -1
    value['answerability'][0].update(status='DEPENDS', possible_options=[0])
    decision = interpret_practical_review(value, packet, course, concise=True, strict_targets=True, standalone=True)
    assert [item['evidence']['problem'] for item in decision.feedback] == ['option_answerability_unresolved']
    assert decision.question_ids == ('q1',) and not decision.source_uncertain
    # The old reviewer remains byte/decision compatible for owned historical jobs.
    legacy = copy.deepcopy(value)
    legacy['narrative_sources'] = legacy.pop('question_sources')
    old = interpret_practical_review(legacy, packet, course, concise=True, strict_targets=True)
    assert len(old.feedback) == 2


def test_alias_roundtrip_and_invalid_source_fail_closed(case):
    _, packet, course = case
    view = PracticalModelView(packet)
    fmt = practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True)
    wire = view.encode(response(packet, course))
    assert wire['question_sources']['l1'][0].startswith('SRC')
    assert matches_practical_review(wire, view.schema(fmt))
    assert view.decode(wire) == response(packet, course)
    wire['question_sources']['l1'] = ['SRC999999']
    with pytest.raises(ValueError):
        view.decode(wire)


def test_standalone_retains_owned_question_and_source_issues_only(case):
    _, packet, course = case
    previous = ({'issue_id': 'i1', 'scope': 'question', 'id': 'q1', 'evidence': {'problem': 'Pending'}},
                {'issue_id': 'i2', 'scope': 'source', 'id': packet.blocks[0].block_id,
                 'evidence': {'problem': 'Uncertain'}})
    value = response(packet, course)
    value['issue_checks'] = {row['issue_id']: {'status': 'OPEN', 'reason': 'Not resolved.'} for row in previous}
    decision = interpret_practical_review(value, packet, course, previous,
                                          concise=True, strict_targets=True, standalone=True)
    assert not decision.accepted and decision.source_uncertain and decision.question_ids == ('q1',)
    assert not decision.lesson_ids and not decision.assessment_lesson_ids and not decision.allow_new_lessons
    with pytest.raises(ValueError):
        practical_review_format(packet, course, ({'issue_id': 'bad', 'scope': 'lesson', 'id': 'l1'},),
                                concise=True, strict_targets=True, standalone=True)


@pytest.mark.parametrize(('options', 'expected'), [
    ({}, '9a96f2a9f6ab8709dc3c0c7f3c2b80b7be24095926dfc7039a9f3c32a56604e3'),
    ({'concise': True}, '9f6df8f31ef1a44488582770a401e593769c627d7debba52ba51cbc473741e94'),
    ({'concise': True, 'strict_targets': True}, '28d9c724179a08516298c3e2dd97b796398d2720f3ae8dc767f0d326407c951e'),
])
def test_legacy_format_bytes_match_committed_baseline(case, options, expected):
    _, packet, course = case
    fmt = practical_review_format(packet, course, **options)
    encoded = json.dumps(fmt, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    assert hashlib.sha256(encoded).hexdigest() == expected


def test_standalone_single_lesson_runner_1000_sources():
    source = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(1000))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    assert len(packet.blocks) == 1000
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
        'correct_index': 0, 'explanation': 'Explanation.', 'source_refs': [packet.blocks[i].block_id]} for i in range(4)]
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text.', 'questions': questions}]}
    fmt = PracticalModelView(packet).schema(practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True))
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('standalone_shipped_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(fmt) == fmt['json_schema']['schema']


def test_standalone_requires_concise_strict_single_lesson(case):
    _, packet, course = case
    for options in ({'standalone': True}, {'standalone': True, 'concise': True}):
        with pytest.raises(ValueError):
            practical_review_format(packet, course, **options)
        with pytest.raises(ValueError):
            practical_review_messages(packet, course, **options)
    original = copy.deepcopy(course)
    second = copy.deepcopy(course['lessons'][0])
    second['id'] = 'l2'
    for q in second['questions']:
        q['id'] += '-other'
    original['lessons'].append(second)
    with pytest.raises(ValueError):
        practical_review_format(packet, original, concise=True, strict_targets=True, standalone=True)
