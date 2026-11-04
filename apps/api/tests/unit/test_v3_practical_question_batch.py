"""Whole-course standalone question bank stays blind and keeps owned IDs."""
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
    QUESTION_BATCH_NAME,
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from tests.unit.test_v3_practical_counterexamples import FLAGS, response

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
OPTIONS = {**FLAGS, 'counterexamples': True, 'question_batch': True}


def two_lessons(course):
    course = copy.deepcopy(course)
    course['title'] = 'HIDDEN_COURSE_TITLE'
    first = course['lessons'][0]
    first['title'] = 'HIDDEN_TITLE'
    first['content'] = 'HIDDEN_LESSON_CONTENT'
    first['questions'] = first['questions'][:1]
    first['questions'][0]['explanation'] = 'HIDDEN_EXPLANATION'
    other = copy.deepcopy(first)
    other['id'] = 'l2'
    other['questions'][0]['id'] = 'q2'
    other['questions'][0]['prompt'] = 'Separate question?'
    other['questions'][0]['correct_index'] = 1
    course['lessons'].append(other)
    return course


def test_flat_blind_bank_and_question_ownership(case):
    _, packet, original = case
    course = two_lessons(original)
    fmt = practical_review_format(packet, course, **OPTIONS)
    assert fmt['json_schema']['name'] == QUESTION_BATCH_NAME and is_practical_review_format(fmt)
    props = fmt['json_schema']['schema']['properties']
    assert set(props['question_sources']['properties']) == {'l1', 'l2'}
    assert set(props['answer_keys']['properties']) == {'q1', 'q2'}
    previous = ({'issue_id': 'issue-previous', 'scope': 'question', 'id': 'q2',
                 'evidence': {'review_kind': 'ANSWER_VALIDITY', 'problem': 'HIDDEN_CRITIC_PROSE'}},)
    messages = practical_review_messages(packet, course, previous, **OPTIONS)
    body = messages[1]['content'].split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
    bank = json.loads(body)
    assert [(q['lesson_id'], q['id']) for q in bank] == [('l1', 'q1'), ('l2', 'q2')]
    assert all(set(q) == {'lesson_id', 'id', 'prompt', 'choices'} for q in bank)
    assert 'HIDDEN_' not in messages[1]['content'] and 'correct_index' not in body
    value = response(packet, course)
    assert matches_practical_review(value, fmt)
    assert interpret_practical_review(value, packet, course, **OPTIONS).accepted
    value['answer_keys']['q2'] = 0
    decision = interpret_practical_review(value, packet, course, **OPTIONS)
    assert decision.question_ids == ('q2',) and len(decision.feedback) == 1
    assert decision.feedback[0]['evidence']['review_kind'] == 'ANSWER_VALIDITY'
    value['answerability'][0]['question_id'] = 'foreign'
    assert not matches_practical_review(value, fmt)
    value = response(packet, course)
    value['findings'] = [{'scope': 'question', 'target_id': 'foreign', 'problem': 'Problem',
                          'expected_rule': 'Rule', 'correction': 'Correction',
                          'source_refs': [packet.blocks[0].block_id], 'review_kind': 'ANSWER_VALIDITY'}]
    assert not matches_practical_review(value, fmt)


def test_old_paths_unchanged_and_new_mode_requires_full_contract(case):
    _, packet, course = case
    options = {**FLAGS, 'counterexamples': True}
    assert practical_review_format(packet, course, **options) == practical_review_format(packet, course, **options, question_batch=False)
    assert practical_review_messages(packet, course, **options) == practical_review_messages(packet, course, **options, question_batch=False)
    assert interpret_practical_review(response(packet, course), packet, course, **options) == interpret_practical_review(
        response(packet, course), packet, course, **options, question_batch=False)
    with pytest.raises(ValueError):
        practical_review_format(packet, two_lessons(course), **options)
    with pytest.raises(ValueError):
        practical_review_format(packet, course, question_batch=True)


def test_question_bank_schema_fits_shipped_runner_with_1000_sources():
    source = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(1000))
    document = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (document,), len(source), 0))
    lessons = [{'id': f'l{i}', 'title': 'Title', 'content': 'Text.', 'questions': [
        {'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
         'explanation': 'Explanation.', 'source_refs': [packet.blocks[i].block_id]}]} for i in range(2)]
    course = {'title': 'Course', 'lessons': lessons}
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('question_batch_shipped_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    wire = PracticalModelView(packet).schema(practical_review_format(packet, course, **OPTIONS))
    assert runner._checked_structured_format(wire) == wire['json_schema']['schema']
