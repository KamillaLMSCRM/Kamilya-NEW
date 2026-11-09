"""Owned parent and child edit intents compose; they must not freeze each other."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_editorial_contract import (
    compile_editorial_revision,
    editorial_edit_authority,
)
from tests.unit.test_v3_editorial_contract import revision_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def finding(kind, key):
    return {'domain': 'assessment' if kind == 'question' else 'content',
            'severity': 'material', 'target': {'kind': kind, 'id': key}}


@pytest.mark.parametrize('order', [False, True])
def test_mixed_lesson_and_child_question_preserve_both_edit_rights(case, order):
    _, packet, course = case
    lesson = course['lessons'][0]
    question = lesson['questions'][0]
    rows = [finding('lesson', lesson['id']), finding('question', question['id'])]
    if order:
        rows.reverse()
    before = copy.deepcopy(course)
    authority = editorial_edit_authority(course, rows)
    assert authority == {'course_title_editable': False, 'lessons': [{
        'lesson_id': lesson['id'], 'title_editable': True, 'content_editable': True,
        'editable_question_ids': [q['id'] for q in lesson['questions']],
    }]}
    changed = copy.deepcopy(course)
    changed['lessons'][0]['content'] += '\nCorrected operative explanation.'
    changed['lessons'][0]['questions'][0]['explanation'] = 'Corrected question explanation.'
    from app.modules.ai.v3.practical_contract import _digest
    result, metadata = compile_editorial_revision(revision_value(packet, course, changed), packet, course,
        {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course), 'findings': rows})
    assert result == changed and course == before
    assert metadata['revision_applied'] is True


def test_question_only_grants_no_prose_or_peer_question_authority(case):
    _, _, course = case
    lesson = course['lessons'][0]
    qid = lesson['questions'][0]['id']
    assert editorial_edit_authority(course, [finding('question', qid)]) == {
        'course_title_editable': False, 'lessons': [{
            'lesson_id': lesson['id'], 'title_editable': False, 'content_editable': False,
            'editable_question_ids': [qid],
        }]}


@pytest.mark.parametrize('explicit', [False, True])
def test_actual_writer_payload_resolves_parent_child_precedence_only_for_new_mode(case, explicit):
    from app.modules.ai.v3.practical_autonomous_editorial_cycle import _scoped_edit_messages
    from app.modules.ai.v3.practical_model_view import PracticalModelView

    _, packet, course = case
    lesson = course['lessons'][0]
    rows = [finding('lesson', lesson['id']), finding('question', lesson['questions'][0]['id'])]
    messages = _scoped_edit_messages(course, rows, 'Exact original source.', PracticalModelView(packet), [], '',
                                     explicit_scope=explicit)
    if explicit:
        raw = messages[1]['content'].split('\nEDIT_AUTHORITY_JSON\n')[1].split('\nEDITORIAL_FINDINGS_UNVERIFIED_JSON\n')[0]
        authority = json.loads(raw)
        assert authority['lessons'][0]['content_editable'] is True
        assert authority['lessons'][0]['editable_question_ids'] == [q['id'] for q in lesson['questions']]
        assert 'добавленная цель question не запрещает исправлять этот текст' in messages[0]['content']
        assert 'его прежние title/content оставь без изменений.' not in messages[0]['content']
    else:
        assert 'EDIT_AUTHORITY_JSON' not in messages[1]['content']
        assert 'его прежние title/content оставь без изменений.' in messages[0]['content']


def test_course_target_includes_all_own_lessons_and_questions(case):
    _, _, course = case
    authority = editorial_edit_authority(course, [finding('course', 'course')])
    assert authority['course_title_editable'] is True
    assert [r['lesson_id'] for r in authority['lessons']] == [r['id'] for r in course['lessons']]
    assert all(r['content_editable'] and r['title_editable'] for r in authority['lessons'])


@pytest.mark.parametrize('kind,key', [('source', 'source'), ('lesson', 'foreign'),
    ('question', 'foreign'), ('course', 'foreign'), ('unknown', 'course')])
def test_unknown_or_source_targets_never_grant_course_edit_authority(case, kind, key):
    _, _, course = case
    with pytest.raises(ValueError, match='editorial_edit_authority_invalid'):
        editorial_edit_authority(course, [finding(kind, key)])
