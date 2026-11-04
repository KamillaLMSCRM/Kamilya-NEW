"""Counterexamples are untrusted answer allegations, not source provenance."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    COUNTEREXAMPLE_CONSOLIDATED_NAME,
    COUNTEREXAMPLE_STANDALONE_NAME,
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from tests.unit.test_v3_practical_standalone_cycle import standalone_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
FLAGS = dict(concise=True, strict_targets=True, standalone=True, typed_findings=True)


def counterexample(status='NONE', refs=()):
    return {'status': status, 'unstated_condition': 'Whether approval was recorded' if status == 'FOUND' else '',
            'case_description': 'Signature without a record leaves the procedure incomplete.' if status == 'FOUND' else '',
            'possible_options': [1] if status == 'FOUND' else [], 'source_refs': list(refs)}


def response(packet, course, status='NONE'):
    value = standalone_value(packet, course)
    for row in value['answerability']:
        row['counterexample'] = counterexample()
    value['answerability'][0]['counterexample'] = counterexample(status, [packet.blocks[0].block_id] if status == 'FOUND' else [])
    return value


@pytest.mark.parametrize('status', ['FOUND', 'UNKNOWN'])
def test_counterexample_blocks_matching_unique_key_with_one_unified_allegation(case, status):
    _, packet, course = case
    value = response(packet, course, status)
    result = interpret_practical_review(value, packet, course, **FLAGS, counterexamples=True)
    assert not result.accepted and result.question_ids == ('q1',)
    assert len(result.feedback) == 1
    evidence = result.feedback[0]['evidence']
    assert evidence['review_kind'] == 'ANSWER_VALIDITY'
    assert evidence['counterexample'] == value['answerability'][0]['counterexample']
    assert evidence['possible_options'] == [0]  # Alternative indices are claims, not a replacement answer.
    assert result.lesson_ids == () and not result.allow_new_lessons


def test_none_preserves_existing_key_checks_and_consolidation_does_not_promote_provenance(case):
    _, packet, course = case
    value = response(packet, course)
    assert interpret_practical_review(value, packet, course, **FLAGS, counterexamples=True).accepted
    value['answer_keys']['q1'] = 1
    result = interpret_practical_review(value, packet, course, **FLAGS, counterexamples=True)
    assert len(result.feedback) == 1 and result.feedback[0]['evidence']['reviewer_key'] == 1
    value['answer_keys']['q1'] = 0
    value['narrative_sources'] = {'l1': []}
    del value['question_sources']
    value['answerability'][0]['counterexample'] = counterexample('FOUND', [packet.blocks[0].block_id])
    decision = interpret_practical_review(value, packet, course, concise=True, allow_empty_narrative=True,
                                          typed_findings=True, counterexamples=True)
    assert not decision.accepted and decision.lesson_ids == () and not decision.allow_new_lessons
    assert value['narrative_sources'] == {'l1': []}


@pytest.mark.parametrize('invalid', ['missing', 'foreign', 'duplicate_ref', 'out_of_bounds', 'duplicate_option', 'empty_found', 'nonempty_none'])
def test_counterexample_shape_ownership_and_indices_fail_closed(case, invalid):
    _, packet, course = case
    value = response(packet, course, 'FOUND')
    item = value['answerability'][0]['counterexample']
    if invalid == 'missing':
        del item['status']
    elif invalid == 'foreign':
        item['source_refs'] = ['foreign']
    elif invalid == 'duplicate_ref':
        item['source_refs'] *= 2
    elif invalid == 'out_of_bounds':
        item['possible_options'] = [3]
    elif invalid == 'duplicate_option':
        item['possible_options'] = [1, 1]
    elif invalid == 'empty_found':
        item['case_description'] = '  '
    else:
        item['status'] = 'NONE'
    fmt = practical_review_format(packet, course, **FLAGS, counterexamples=True)
    assert not matches_practical_review(value, fmt)
    with pytest.raises(ValueError, match='practical_review_response_invalid'):
        interpret_practical_review(value, packet, course, **FLAGS, counterexamples=True)


def test_versions_reconstruct_and_legacy_default_is_identical(case):
    _, packet, course = case
    old = practical_review_format(packet, course, **FLAGS)
    assert old == practical_review_format(packet, course, **FLAGS, counterexamples=False)
    assert practical_review_messages(packet, course, **FLAGS) == practical_review_messages(packet, course, **FLAGS, counterexamples=False)
    assert matches_practical_review(standalone_value(packet, course), old)
    new = practical_review_format(packet, course, **FLAGS, counterexamples=True)
    assert new['json_schema']['name'] == COUNTEREXAMPLE_STANDALONE_NAME
    assert is_practical_review_format(new) and matches_practical_review(response(packet, course), new)
    assert not matches_practical_review(standalone_value(packet, course), new)
    internal = practical_review_format(packet, course, concise=True, allow_empty_narrative=True,
                                        typed_findings=True, counterexamples=True)
    assert internal['json_schema']['name'] == COUNTEREXAMPLE_CONSOLIDATED_NAME
    assert is_practical_review_format(internal)
    for kwargs in ({}, {'concise': True, 'strict_targets': True, 'standalone': True}):
        with pytest.raises(ValueError):
            practical_review_format(packet, course, counterexamples=True, **kwargs)
    prompt = practical_review_messages(packet, course, **FLAGS, counterexamples=True)[0]['content']
    assert 'соседних вопросов' in prompt and 'не меняют исход' in prompt


def test_external_counterexample_schema_fits_shipped_runner_with_1000_sources():
    source = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(1000))
    document = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (document,), len(source), 0))
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
                  'explanation': 'Explanation.', 'source_refs': [packet.blocks[i].block_id]} for i in range(4)]
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text.', 'questions': questions}]}
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('counterexample_shipped_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    wire = PracticalModelView(packet).schema(practical_review_format(packet, course, **FLAGS, counterexamples=True))
    assert runner._checked_structured_format(wire) == wire['json_schema']['schema']
