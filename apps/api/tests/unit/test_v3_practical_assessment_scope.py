"""Assessment repair permissions preserve reviewed prose and existing questions."""
import copy

import pytest

from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_practical_cycle import case, checked
from tests.unit.test_v3_practical_review import example, finding
from tests.unit.test_v3_practical_source_audit import audit


@pytest.fixture
def proposal():
    from app.modules.ai.v3 import practical_cycle, practical_patch, practical_review, practical_source_audit
    return {m.__name__.rsplit('.',1)[-1]:m for m in (practical_review, practical_patch, practical_source_audit, practical_cycle)}


def test_saved_assessment_finding_grants_only_its_lesson_and_preserves_siblings(proposal):
    packet, course, review, ref = example.__wrapped__()
    sibling = copy.deepcopy(course['lessons'][0])
    sibling['id'] = 'sibling'
    sibling['questions'][0]['id'] = 'sibling-question'
    course['lessons'].append(sibling)
    review['answer_keys']['sibling-question'] = 0
    for key in ('question_rules', 'option_checks'):
        row = copy.deepcopy(review[key][0])
        row['question_id'] = 'sibling-question'
        review[key].append(row)
    review['narrative_sources']['sibling'] = [ref]
    original = copy.deepcopy(course)
    review['findings'] = [finding('assessment', 'lesson', ref)]
    editor, patcher = proposal['practical_review'], proposal['practical_patch']
    decision = editor.interpret_practical_review(review, packet, course)
    assert decision.assessment_lesson_ids == ('lesson',)
    assert not decision.lesson_ids and not decision.question_ids and not decision.allow_new_lessons
    fmt = patcher.practical_patch_format(packet, course, decision)
    assert patcher.is_practical_patch_format(fmt)
    props = fmt['json_schema']['schema']['properties']
    assert set(props['assessment_additions']['properties']) == {'lesson'}
    assert 'lesson_updates' not in props and 'question_updates' not in props
    assert props['new_questions']['maxItems'] == props['new_lessons']['maxItems'] == 0
    new_question = dict(course['lessons'][0]['questions'][0], id='new-question', prompt='New question?')
    patch = {'course_fingerprint': patcher._fingerprint(course), 'new_lessons': [], 'new_questions': [],
             'assessment_additions': {'lesson': [new_question]}}
    assert patcher.matches_practical_patch(patch, fmt)
    merged = patcher.merge_practical_patch(course, packet, decision, patch)
    assert merged['lessons'][0]['questions'] == original['lessons'][0]['questions'] + [new_question]
    assert merged['lessons'][1] == original['lessons'][1]
    assert merged['lessons'][0]['content'] == original['lessons'][0]['content'] and course == original
    foreign = copy.deepcopy(patch)
    foreign['assessment_additions']['other-lesson'] = foreign['assessment_additions'].pop('lesson')
    assert not patcher.matches_practical_patch(foreign, fmt)
    collision = copy.deepcopy(patch)
    collision['assessment_additions']['lesson'][0]['id'] = 'question'
    with pytest.raises(ValueError):
        patcher.merge_practical_patch(course, packet, decision, collision)


def test_ordinary_owned_prose_coverage_never_grants_assessment_addition(proposal):
    packet, course, review, ref = example.__wrapped__()
    review['findings'] = [finding('coverage', ref, ref)]
    decision = proposal['practical_review'].interpret_practical_review(review, packet, course)
    fmt = proposal['practical_patch'].practical_patch_format(packet, course, decision)
    props = fmt['json_schema']['schema']['properties']
    assert decision.lesson_ids == ('lesson',) and not decision.assessment_lesson_ids
    assert 'assessment_additions' not in props and props['new_questions']['maxItems'] == 0


@pytest.mark.parametrize('source', ['review', 'audit'])
def test_assessment_target_must_be_an_existing_lesson(proposal, source):
    packet, course, review, ref = example.__wrapped__()
    if source == 'review':
        module, value = proposal['practical_review'], review
        fmt = module.practical_review_format(packet, course)
        matches = module.matches_practical_review
    else:
        packet, course, value, ref = audit.__wrapped__()
        module = proposal['practical_source_audit']
        fmt = module.source_audit_format(packet, course)
        matches = module.matches_source_audit
    value['findings'] = [finding('assessment', 'lesson', ref)]
    assert matches(value, fmt)
    value['findings'][0]['target_id'] = 'question'
    assert not matches(value, fmt)


@pytest.mark.parametrize('defect', ['foreign_source', 'lesson_id', 'source_id', 'reserved_alias'])
def test_assessment_addition_rejects_foreign_source_and_reserved_identities(proposal, defect):
    packet, course, review, ref = example.__wrapped__()
    review['findings'] = [finding('assessment', 'lesson', ref)]
    decision = proposal['practical_review'].interpret_practical_review(review, packet, course)
    patcher = proposal['practical_patch']
    question = dict(course['lessons'][0]['questions'][0], id='fresh')
    if defect == 'foreign_source':
        question['source_refs'] = ['foreign']
    elif defect == 'lesson_id':
        question['id'] = 'lesson'
    elif defect == 'source_id':
        question['id'] = ref
    else:
        question['id'] = 'SRC42'
    patch = {'course_fingerprint': patcher._fingerprint(course), 'new_lessons': [], 'new_questions': [],
             'assessment_additions': {'lesson': [question]}}
    with pytest.raises(ValueError):
        result = patcher.merge_practical_patch(course, packet, decision, patch)
        # The cycle applies this reserved-alias check after merge and before acceptance.
        PracticalModelView(packet).assert_course_ids_disjoint(result)


@pytest.mark.asyncio
async def test_audit_assessment_finding_repairs_only_l2_and_second_review_accepts(proposal):
    _, packet, course = case.__wrapped__()
    sibling = copy.deepcopy(course['lessons'][0])
    sibling['id'] = 'l2'
    for question in sibling['questions']:
        question['id'] += '-l2'
    course['lessons'].append(sibling)
    original = copy.deepcopy(course)
    new_question = dict(sibling['questions'][0], id='new-l2', prompt='Additional question?')
    candidate = copy.deepcopy(course)
    candidate['lessons'][1]['questions'].append(copy.deepcopy(new_question))
    view = PracticalModelView(packet)
    refs = [b.block_id for b in packet.blocks]
    calls = []
    audit_count = 0

    async def invoke(stage, group, _messages, fmt, validator):
        nonlocal audit_count
        calls.append((stage, group))
        if group.startswith('practical:author:'):
            value = course
        elif group.startswith('practical:review:'):
            current = course if audit_count == 0 else candidate
            value = checked(packet, current)
            prior = fmt['json_schema']['schema']['properties'].get('issue_checks', {}).get('properties', {})
            if prior:
                value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Added the question.'} for key in prior}
        elif group.startswith('practical:source-audit:'):
            audit_count += 1
            value = {'source_fingerprint': packet.fingerprint, 'source_units_fingerprint': audit_units(packet).fingerprint,
                'source_review': 'Reviewed source.', 'source_notes': [],
                'source_checks': [{'unit_id': key, 'source_refs': list(blocks), 'status': 'TAUGHT',
                                   'lesson_ids': ['l1', 'l2'], 'reason': 'Taught.'}
                                  for key, blocks in audit_units(packet).groups],
                'narrative_sources': {'l1': refs, 'l2': refs},
                'findings': [finding('assessment', 'l2', refs[0])] if audit_count == 1 else []}
        else:
            assert group.startswith('practical:repair:')
            props = fmt['json_schema']['schema']['properties']
            assert set(props['assessment_additions']['properties']) == {'l2'}
            assert 'lesson_updates' not in props and 'question_updates' not in props
            value = {'course_fingerprint': props['course_fingerprint']['enum'][0],
                     'new_lessons': [], 'new_questions': [], 'assessment_additions': {'l2': [new_question]}}
        wire = view.encode(value)
        validator(wire)
        return wire

    result = await proposal['practical_cycle'].run_practical_cycle(packet, {}, invoke)
    assert result.stop_reason == 'accepted' and result.decision.accepted
    assert len(result.history) == 2 and not result.history[0]['accepted'] and result.history[1]['accepted']
    assert result.history[0]['source_audit']['findings'][0]['scope'] == 'assessment'
    assert result.course == candidate and course == original
    assert result.course['lessons'][0] == original['lessons'][0]
    assert result.course['lessons'][1]['questions'][:-1] == original['lessons'][1]['questions']
    assert [stage for stage, _ in calls] == ['lesson', 'review', 'review', 'repair', 'review', 'review']
