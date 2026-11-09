import copy

import pytest

from app.modules.ai.v3 import practical_compact_editorial_cycle as cycle


def groups(prior, course):
    build = getattr(cycle, '_current_target_review_groups', None)
    assert callable(build), 'Current target text must be adjacent to its grouped observations'
    return build(prior, course)


def test_groups_keep_all_observations_adjacent_to_exact_owned_current_text():
    text = 'Current beginning. ' + ('Full current prose. ' * 800) + 'Current ending.'
    question = {'id': 'q1', 'prompt': 'Current question', 'choices': ['Current A', 'Current B'],
                'correct_index': 1, 'explanation': 'Current reason', 'source_refs': ['s1']}
    lesson = {'id': 'l1', 'title': 'Current title', 'content': text, 'questions': [question]}
    course = {'lessons': [lesson]}
    prior = [{'issue_id': key, 'target': {'kind': kind, 'id': target}, 'problem': 'Historical allegation',
              'current_target_snapshot': {'content': 'Stale and untrusted'}}
             for key, kind, target in [('a', 'lesson', 'l1'), ('b', 'question', 'q1'),
                                      ('c', 'lesson', 'l1'), ('d', 'source', 's1'),
                                      ('e', 'source', 's2'), ('f', 'course', 'course')]]
    before = copy.deepcopy((prior, course))
    result = groups(prior, course)
    assert len(result) == 5
    assert [x['issue_id'] for x in result[0]['observations']] == ['a', 'c']
    assert result[0]['current_target_snapshot'] == lesson
    assert result[1]['current_target_snapshot'] == question
    assert all(row['current_target_snapshot'] is None for row in result[2:])
    assert {x['issue_id'] for row in result for x in row['observations']} == set('abcdef')
    assert all('current_target_ref' not in x and 'current_target_snapshot' not in x
               for row in result for x in row['observations'])
    assert (prior, course) == before
    result[0]['current_target_snapshot']['content'] = 'Changed copy'
    result[0]['observations'][0]['problem'] = 'Changed copy'
    assert (prior, course) == before


def test_grouping_preserves_reserved_field_rejection_and_empty_input():
    assert groups([], {'lessons': []}) == []
    with pytest.raises(ValueError, match='editorial_target_registry_reserved_field'):
        groups([{'target': {'kind': 'course', 'id': 'course'}, 'current_target_ref': 'untrusted'}],
               {'lessons': []})


def test_model_projection_preserves_literal_multiline_prose_and_every_observation():
    render = getattr(cycle, '_render_current_target_reviews', None)
    assert callable(render), 'The model must read literal current prose without nested JSON escaping'

    class View:
        def encode(self, value):
            return copy.deepcopy(value)

    prose = 'Первая строка: "текущий текст".\n\nУже есть действие и условие. \\ literal slash'
    lesson = {'id': 'l1', 'title': 'Current', 'content': prose, 'questions': [
        {'id': 'q1', 'prompt': 'Actual question?', 'choices': ['A', 'B'], 'correct_index': 1,
         'explanation': 'Actual reason', 'source_refs': ['s1']}]}
    prior = [{'issue_id': key, 'target': {'kind': 'lesson', 'id': 'l1'}, 'problem': 'Historical absence'}
             for key in ('a', 'b')]
    rendered = render(groups(prior, {'lessons': [lesson]}), View())
    assert prose in rendered and rendered.count(prose) == 1
    assert 'UNVERIFIED_OBSERVATIONS_JSON' in rendered
    assert 'Actual question?' in rendered and 'correct_index' in rendered
    assert '"issue_id": "a"' in rendered and '"issue_id": "b"' in rendered
