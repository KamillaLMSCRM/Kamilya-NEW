import copy

import pytest

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import (
    compile_editorial_review,
    compile_editorial_revision,
    editorial_review_format,
    editorial_revision_format,
    is_editorial_review_format,
    is_editorial_revision_format,
    matches_editorial_review,
    matches_editorial_revision,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def review_value(packet, course, *, kind='question', target='q1', domain='assessment', severity='material'):
    refs = [b.block_id for b in packet.blocks]
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
        'summary': 'Editorial review; observations remain unverified.',
        'findings': [{'domain': domain, 'severity': severity, 'target': {'kind': kind, 'id': target},
            'problem': 'Check the applicable approval condition.', 'basis': 'The source requires both actions.',
            'correction': 'State the complete condition, preserving checked peers.', 'source_refs': refs}],
        'source_notes': [], 'narrative_sources': {row['id']: refs for row in course['lessons']}}


@pytest.mark.parametrize('kind,target', [('course', 'course'), ('lesson', 'l1'), ('question', 'q1')])
@pytest.mark.parametrize('domain', ['content', 'assessment', 'source'])
def test_domains_and_typed_targets_agree_at_producer_and_consumer(case, kind, target, domain):
    _, packet, course = case
    value = review_value(packet, course, kind=kind, target=target, domain=domain)
    fmt = editorial_review_format(packet, course)
    assert is_editorial_review_format(fmt) and _matches(value, fmt['json_schema']['schema'])
    assert matches_editorial_review(value, fmt)
    result = compile_editorial_review(value, packet, course)
    assert result['findings'][0]['target'] == {'kind': kind, 'id': target}
    assert 'issue_id' not in value['findings'][0]


@pytest.mark.parametrize('change', ['foreign_id', 'wrong_kind', 'foreign_ref', 'wrong_course', 'duplicate_refs'])
def test_bad_identity_never_becomes_edit_authority(case, change):
    _, packet, course = case
    value = review_value(packet, course)
    if change == 'foreign_id':
        value['findings'][0]['target']['id'] = 'foreign'
    elif change == 'wrong_kind':
        value['findings'][0]['target']['kind'] = 'lesson'
    elif change == 'foreign_ref':
        value['findings'][0]['source_refs'] = ['foreign']
    elif change == 'wrong_course':
        value['course_fingerprint'] = 'f' * 64
    else:
        value['findings'][0]['source_refs'] *= 2
    with pytest.raises(ValueError, match='editorial_review_response_invalid'):
        compile_editorial_review(value, packet, course)


def test_duplicate_same_finding_has_one_server_identity(case):
    _, packet, course = case
    raw = review_value(packet, course)
    raw['findings'] *= 2
    result = compile_editorial_review(raw, packet, course)
    assert len(result['findings']) == 1


def revision_value(packet, course, proposed):
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course), 'course': proposed,
        'lesson_sources': [{'lesson_id': row['id'], 'source_refs': [b.block_id for b in packet.blocks]}
                              for row in proposed['lessons']]}


def test_question_revision_retains_unrequested_content_and_siblings(case):
    _, packet, course = case
    review = compile_editorial_review(review_value(packet, course), packet, course)
    proposed = copy.deepcopy(course)
    proposed['lessons'][0]['content'] = 'Unrequested rewrite'
    proposed['lessons'][0]['questions'][0]['prompt'] = 'Which two actions complete approval?'
    proposed['lessons'][0]['questions'][1]['correct_index'] = 1
    value = revision_value(packet, course, proposed)
    fmt = editorial_revision_format(packet, course)
    assert is_editorial_revision_format(fmt) and matches_editorial_revision(value, fmt)
    updated, meta = compile_editorial_revision(value, packet, course, review)
    assert updated['lessons'][0]['content'] == course['lessons'][0]['content']
    assert updated['lessons'][0]['questions'][1] == course['lessons'][0]['questions'][1]
    assert updated['lessons'][0]['questions'][0]['prompt'] == proposed['lessons'][0]['questions'][0]['prompt']
    assert meta['ignored_unrequested_changes'] == ['l1']
    assert meta['semantic_resolution'] == 'REQUIRES_HUMAN_REVIEW'


def test_lesson_revision_cannot_lose_original_questions(case):
    _, packet, course = case
    review = compile_editorial_review(review_value(packet, course, kind='lesson', target='l1', domain='content'), packet, course)
    proposed = copy.deepcopy(course)
    proposed['lessons'][0]['content'] = 'A concise explanation of both required actions.'
    proposed['lessons'][0]['questions'].pop()
    updated, meta = compile_editorial_revision(revision_value(packet, course, proposed), packet, course, review)
    assert updated['lessons'][0]['content'] == proposed['lessons'][0]['content']
    assert updated['lessons'][0]['questions'] == course['lessons'][0]['questions']
    assert meta['retained_missing_targets'] == ['q2']


@pytest.mark.parametrize('domain,severity', [('source', 'material'), ('assessment', 'advisory')])
def test_source_and_advisory_alone_do_not_authorize_automatic_rewrite(case, domain, severity):
    _, packet, course = case
    review = compile_editorial_review(review_value(packet, course, domain=domain, severity=severity), packet, course)
    proposed = copy.deepcopy(course)
    proposed['lessons'][0]['questions'][0]['correct_index'] = 1
    updated, _ = compile_editorial_revision(revision_value(packet, course, proposed), packet, course, review)
    assert updated == course


def test_stale_review_and_foreign_revision_refs_reject(case):
    _, packet, course = case
    review = compile_editorial_review(review_value(packet, course), packet, course)
    value = revision_value(packet, course, course)
    review['course_fingerprint'] = 'f' * 64
    with pytest.raises(ValueError, match='review_identity'):
        compile_editorial_revision(value, packet, course, review)
    review['course_fingerprint'] = _digest(course)
    value = copy.deepcopy(value)
    value['course']['lessons'][0]['questions'][0]['source_refs'] = ['foreign']
    with pytest.raises(ValueError, match='revision_response_invalid'):
        compile_editorial_revision(value, packet, course, review)


def test_typed_source_target_and_updated_lesson_links_roundtrip_through_real_codec(case):
    from app.modules.ai.v3.practical_model_view import PracticalModelView

    _, packet, course = case
    view = PracticalModelView(packet)
    raw = review_value(packet, course, kind='source', target=packet.blocks[0].block_id, domain='source')
    wire = view.encode(raw)
    assert wire['findings'][0]['target']['id'] == 'SRC1'
    assert view.decode(wire) == raw
    value = revision_value(packet, course, course)
    assert view.decode(view.encode(value)) == value
