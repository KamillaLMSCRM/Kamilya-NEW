import copy
from types import SimpleNamespace

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_draft_review import editorial_manifest
from app.modules.ai.v3.practical_review import PracticalReviewDecision


def finding(problem='Earlier advisory'):
    return {'severity': 'advisory', 'target': {'kind': 'lesson', 'id': 'l1'},
            'problem': problem, 'basis': 'Basis', 'correction': 'Suggestion', 'source_refs': ['s1']}


def make_result(*, initial, current, snapshots=(), original=None, course=None, autonomous=True):
    original = original or {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Old', 'questions': []}]}
    course = course or copy.deepcopy(original)
    history = {'autonomous_editorial': autonomous, 'verified_course_fingerprint': _digest(course),
        'initial_editorial_review': initial, 'editorial_original_course': original,
        'editorial_review': current, 'editorial_observation_history': list(snapshots)}
    return PracticalCycleResult(course, {'source_notes': current.get('source_notes', [])},
        PracticalReviewDecision(True, False, (), (), False, ()), (history,), 'passed')


def manifest(result):
    return editorial_manifest(result, SimpleNamespace(fingerprint='f' * 64, blocks=[]), [])


def test_prior_observations_survive_as_historical_even_when_target_changed():
    before = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Old', 'questions': []}]}
    after = copy.deepcopy(before)
    after['lessons'][0]['content'] = 'Changed'
    initial = {'findings': [finding()], 'source_notes': [{'note': 'Earlier source note', 'source_refs': ['s1']}]}
    result = make_result(initial=initial, current={'findings': [], 'source_notes': []}, original=before, course=after,
        snapshots=[{'course_fingerprint': _digest(before), 'review': initial}])
    output = manifest(result)
    assert output['content_review_required'] is False and not output['issues']
    observations = output['observations']
    assert len(observations) == 2
    assert all(row['evidence']['historical'] and row['evidence']['unverified'] for row in observations)
    assert all(row['evidence']['reviewed_course_fingerprint'] == _digest(before) for row in observations)
    assert all('не подтверждено для текущей версии' in row['message'] for row in observations)
    assert next(row for row in observations if row['kind'] == 'editorial_suggestion')['evidence']['reviewed_target_id'] == 'l1'


def test_current_confirmed_observation_wins_and_intermediate_snapshot_survives():
    current = {'findings': [finding()], 'source_notes': [{'note': 'Same source', 'source_refs': ['s1']}]}
    previous = {'findings': [finding(), finding('Intermediate only')],
                'source_notes': [{'note': 'Same source', 'source_refs': ['s1']}]}
    output = manifest(make_result(initial=previous, current=current,
        snapshots=[{'course_fingerprint': 'a' * 64, 'review': previous}]))
    items = output['observations']
    assert sum(row['message'] == 'Earlier advisory' for row in items) == 1
    assert sum(row['message'] == 'Same source' for row in items) == 1
    assert any(row['evidence'].get('historical') and 'Intermediate only' in row['message'] for row in items)
    assert next(row for row in items if row['message'] == 'Earlier advisory')['evidence']['historical'] is False


def test_legacy_non_autonomous_does_not_import_new_history():
    initial = {'findings': [finding()], 'source_notes': []}
    output = manifest(make_result(initial=initial, current={'findings': [], 'source_notes': []}, autonomous=False))
    assert not output['observations'] and 'content_review_required' not in output


def test_same_issue_target_and_snapshot_keeps_latest_observation():
    first = {**finding('First wording'), 'issue_id': 'issue-one'}
    last = {**finding('Later wording'), 'issue_id': 'issue-one'}
    old = {'findings': [first], 'source_notes': []}
    new = {'findings': [last], 'source_notes': []}
    output = manifest(make_result(initial={'findings': [], 'source_notes': []},
        current={'findings': [], 'source_notes': []}, snapshots=[
            {'course_fingerprint': 'a' * 64, 'review': old},
            {'course_fingerprint': 'a' * 64, 'review': new}]))
    assert len(output['observations']) == 1
    assert 'Later wording' in output['observations'][0]['message']


@pytest.mark.parametrize('binding', ['current', 'stale', 'missing', 'invalid_hash'])
def test_final_blind_note_requires_both_current_course_and_valid_input_hash(binding):
    current = {'findings': [], 'source_notes': []}
    result = make_result(initial=current, current=current)
    history = result.history[0]
    note = {'note': 'Blind note', 'source_refs': ['s1']}
    history['final_blind_review'] = {'source_notes': [note]}
    history['final_blind_input_hash'] = 'c' * 64
    if binding != 'missing':
        history['final_blind_current_course_fingerprint'] = _digest(result.course) if binding != 'stale' else 'a' * 64
    if binding == 'invalid_hash':
        history['final_blind_input_hash'] = 'not-a-hash'
    output = manifest(result)
    assert output['content_review_required'] is False and not output['issues']
    assert len(output['observations']) == 1
    row = output['observations'][0]
    assert row['evidence']['historical'] is (binding != 'current')
    assert row['evidence']['unverified'] is True
    assert row['evidence']['reviewed_course_fingerprint'] == (
        _digest(result.course) if binding in ('current', 'invalid_hash') else 'a' * 64 if binding == 'stale' else None)


def test_current_blind_note_deduplicates_keyed_note():
    note = {'note': 'Same source', 'source_refs': ['s1']}
    review = {'findings': [], 'source_notes': [note]}
    result = make_result(initial=review, current=review)
    result.history[0].update(final_blind_review={'source_notes': [note]},
        final_blind_current_course_fingerprint=_digest(result.course), final_blind_input_hash='a' * 64)
    output = manifest(result)
    assert len(output['observations']) == 1
    assert output['observations'][0]['evidence']['historical'] is False


def test_legacy_blind_note_remains_unchanged():
    result = make_result(initial={'findings': [], 'source_notes': []},
                         current={'findings': [], 'source_notes': []}, autonomous=False)
    result.history[0].update(final_blind_review={'source_notes': [{'note': 'Legacy', 'source_refs': ['s1']}]},
                             final_blind_current_course_fingerprint=_digest(result.course), final_blind_input_hash='a' * 64)
    assert not manifest(result)['observations']
