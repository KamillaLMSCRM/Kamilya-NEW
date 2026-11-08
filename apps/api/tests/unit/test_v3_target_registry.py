import copy

import pytest

from app.modules.ai.v3.practical_compact_editorial_cycle import (
    _current_prior_target_registry,
    _current_prior_targets,
)


def _expand(findings, registry):
    result = []
    for finding in findings:
        item = copy.deepcopy(finding)
        ref = item.pop('current_target_ref')
        item['current_target_snapshot'] = copy.deepcopy(registry[ref]) if ref is not None else None
        result.append(item)
    return result


def test_registry_expands_exactly_to_current_targets_and_preserves_inputs():
    course = {'lessons': [{'id': 'lesson-1', 'title': 'Current title', 'content': 'Current prose',
                           'questions': [{'id': 'question-1', 'prompt': 'Current question',
                                          'choices': ['Current A', 'Current B'],
                                          'correct_index': 1, 'explanation': 'Current reason',
                                          'source_refs': ['source-1']}]}]}
    prior = [
        {'issue_id': 'l1', 'target': {'kind': 'lesson', 'id': 'lesson-1'}, 'basis': 'earlier A',
         'current_target_snapshot': {'content': 'stale lesson'}},
        {'issue_id': 'l2', 'target': {'kind': 'lesson', 'id': 'lesson-1'}, 'basis': 'earlier B'},
        {'issue_id': 'q1', 'target': {'kind': 'question', 'id': 'question-1'}, 'basis': 'earlier C',
         'current_target_snapshot': {'prompt': 'stale question'}},
        {'issue_id': 'q2', 'target': {'kind': 'question', 'id': 'question-1'}, 'basis': 'earlier D'},
        {'issue_id': 's1', 'target': {'kind': 'source', 'id': 'source-1'}, 'basis': 'source detail'},
        {'issue_id': 'c1', 'target': {'kind': 'course', 'id': 'course-1'}, 'basis': 'course detail'},
    ]
    before = copy.deepcopy((prior, course))
    packed, registry = _current_prior_target_registry(prior, course)
    assert _expand(packed, registry) == _current_prior_targets(prior, course, prose_only=False)
    assert (prior, course) == before
    assert len(registry) == 2
    assert packed[0]['current_target_ref'] == packed[1]['current_target_ref']
    assert packed[2]['current_target_ref'] == packed[3]['current_target_ref']
    assert packed[0]['current_target_ref'] != packed[2]['current_target_ref']
    assert packed[4]['current_target_ref'] is packed[5]['current_target_ref'] is None
    assert registry[packed[0]['current_target_ref']]['content'] == 'Current prose'
    assert registry[packed[2]['current_target_ref']]['prompt'] == 'Current question'
    reversed_packed, _ = _current_prior_target_registry(list(reversed(prior)), course)
    assert [x['current_target_ref'] for x in reversed(reversed_packed)] == [
        x['current_target_ref'] for x in packed]


def test_registry_rejects_reserved_field_instead_of_losing_it():
    prior = [{'target': {'kind': 'course', 'id': 'course-1'}, 'current_target_ref': 'untrusted'}]
    with pytest.raises(ValueError, match='editorial_target_registry_reserved_field'):
        _current_prior_target_registry(prior, {'lessons': []})
