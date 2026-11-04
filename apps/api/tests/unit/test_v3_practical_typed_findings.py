"""P17 finding purpose is explicit and answer disagreements have one owner."""
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_atomic_audit import (
    TYPED_NAME as ATOMIC_TYPED_NAME,
)
from app.modules.ai.v3.practical_atomic_audit import (
    atomic_audit_format,
    atomic_audit_messages,
    compiled_atomic_audit_findings,
    matches_atomic_audit,
)
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    TYPED_CONSOLIDATED_NAME,
    TYPED_STANDALONE_NAME,
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from tests.unit.test_v3_practical_atomic_audit import audit_value
from tests.unit.test_v3_practical_concise_review import concise_review

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def standalone_value(packet, course):
    value = concise_review(packet, course)
    value['question_sources'] = value.pop('narrative_sources')
    return value


@pytest.mark.parametrize(('status', 'options', 'key'), [
    ('UNIQUE', [1], 1), ('UNIQUE', [0], -1), ('UNIQUE', [0], 1), ('DEPENDS', [0, 1], -1),
])
def test_one_unified_answer_issue_preserves_both_reports(case, status, options, key):
    _, packet, course = case
    value = standalone_value(packet, course)
    value['answerability'][0].update(status=status, possible_options=options)
    value['answer_keys']['q1'] = key
    result = interpret_practical_review(value, packet, course, concise=True, strict_targets=True,
                                        standalone=True, typed_findings=True)
    assert len(result.feedback) == 1
    issue = result.feedback[0]
    assert issue['id'] == 'q1' and issue['evidence']['review_kind'] == 'ANSWER_VALIDITY'
    assert issue['evidence']['reviewer_key'] == key and issue['evidence']['possible_options'] == options
    assert issue['evidence']['author_key'] == course['lessons'][0]['questions'][0]['correct_index']


@pytest.mark.parametrize('kind', [None, 'UNKNOWN', 'COURSE_ASSESSMENT'])
def test_standalone_rejects_missing_unknown_and_course_kind(case, kind):
    _, packet, course = case
    value = standalone_value(packet, course)
    finding = {'scope': 'question', 'target_id': 'q1', 'problem': 'Ambiguous.',
               'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Rule.', 'correction': 'Clarify.'}
    if kind is not None:
        finding['review_kind'] = kind
    value['findings'] = [finding]
    fmt = practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True, typed_findings=True)
    assert fmt['json_schema']['name'] == TYPED_STANDALONE_NAME and is_practical_review_format(fmt)
    assert not matches_practical_review(value, fmt)


def test_atomic_typed_question_purpose_is_closed_and_survives_compile(case):
    _, packet, course = case
    value = audit_value(packet, course)
    issue = {'scope': 'question', 'target_id': 'q1', 'problem': 'Duplicate.',
             'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Rule.',
             'correction': 'Change one.', 'review_kind': 'COURSE_ASSESSMENT'}
    value['findings'] = [issue]
    fmt = atomic_audit_format(packet, course, typed_findings=True)
    assert fmt['json_schema']['name'] == ATOMIC_TYPED_NAME
    assert matches_atomic_audit(value, fmt)
    assert compiled_atomic_audit_findings(value, packet, course, typed_findings=True)[0] == issue
    for kind in (None, 'INVALID'):
        bad = copy.deepcopy(value)
        if kind is None:
            del bad['findings'][0]['review_kind']
        else:
            bad['findings'][0]['review_kind'] = kind
        assert not matches_atomic_audit(bad, fmt)
    foreign = copy.deepcopy(value)
    foreign['findings'][0]['source_refs'] = ['foreign']
    assert not matches_atomic_audit(foreign, fmt)
    assert 'COURSE_ASSESSMENT' in atomic_audit_messages(packet, course, typed_findings=True)[0]['content']


def test_typed_consolidation_accepts_both_question_kinds(case):
    _, packet, course = case
    value = concise_review(packet, course)
    value['narrative_sources']['l1'] = []
    value['findings'] = [{'scope': 'question', 'target_id': 'q1', 'problem': 'Duplicate.',
        'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Rule.', 'correction': 'Change.',
        'review_kind': 'COURSE_ASSESSMENT'}]
    fmt = practical_review_format(packet, course, concise=True, allow_empty_narrative=True, typed_findings=True)
    assert fmt['json_schema']['name'] == TYPED_CONSOLIDATED_NAME
    assert is_practical_review_format(fmt) and matches_practical_review(value, fmt)
    result = interpret_practical_review(value, packet, course, concise=True, allow_empty_narrative=True, typed_findings=True)
    assert result.feedback[0]['evidence']['review_kind'] == 'COURSE_ASSESSMENT'


def test_typed_standalone_unwraps_owned_question_hold_without_leaking_evidence(case):
    _, packet, course = case
    original = {'issue_id': 'issue-q', 'scope': 'question', 'id': 'q1',
                'evidence': {'review_kind': 'ANSWER_VALIDITY', 'problem': 'secret context', 'author_key': 0}}
    held = {'issue_id': 'issue-q', 'scope': 'source', 'id': packet.blocks[0].block_id,
            'evidence': {'problem': 'NEEDS_REVIEW', 'original_finding': original}}
    messages = practical_review_messages(packet, course, (held,), concise=True, strict_targets=True,
                                         standalone=True, typed_findings=True)
    assert 'secret context' not in messages[1]['content'] and 'author_key' not in messages[1]['content']
    assert '"scope": "question"' in messages[1]['content']
    wrong = copy.deepcopy(held)
    wrong['evidence']['original_finding']['evidence']['review_kind'] = 'COURSE_ASSESSMENT'
    with pytest.raises(ValueError):
        practical_review_messages(packet, course, (wrong,), concise=True, strict_targets=True,
                                  standalone=True, typed_findings=True)


def test_legacy_defaults_unchanged(case):
    _, packet, course = case
    assert atomic_audit_format(packet, course) == atomic_audit_format(packet, course, typed_findings=False)
    assert atomic_audit_messages(packet, course) == atomic_audit_messages(packet, course, typed_findings=False)
    for flags in ({}, {'concise': True}, {'concise': True, 'strict_targets': True},
                  {'concise': True, 'strict_targets': True, 'standalone': True},
                  {'concise': True, 'allow_empty_narrative': True}):
        assert practical_review_format(packet, course, **flags) == practical_review_format(packet, course, typed_findings=False, **flags)


def test_typed_external_schemas_fit_shipped_runner_with_1000_sources():
    source = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(1000))
    document = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (document,), len(source), 0))
    assert len(packet.blocks) == 1000
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'], 'correct_index': 0,
                  'explanation': 'Explanation.', 'source_refs': [packet.blocks[i].block_id]} for i in range(4)]
    course = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text.', 'questions': questions}]}
    view = PracticalModelView(packet)
    runner_path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('typed_findings_shipped_runner', runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    for fmt in (practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True, typed_findings=True),
                atomic_audit_format(packet, course, typed_findings=True)):
        wire = view.schema(fmt)
        assert runner._checked_structured_format(wire) == wire['json_schema']['schema']
