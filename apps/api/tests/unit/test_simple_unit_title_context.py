"""Planned topic must survive both assembly seams before learner-card review."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V10_POLICY, SIMPLE_COURSE_REVIEW_V11_POLICY
from app.modules.ai.v3.simple_course_editor_v10 import run_simple_course_editor_v10
from app.modules.ai.v3.simple_course_editor_v11 import run_simple_course_editor_v11
from app.modules.ai.v3.simple_course_service import simple_course_artifacts, simple_stage_allowed
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


@pytest.mark.asyncio
@pytest.mark.parametrize('preserve,edit_title,accounting,redundant_support', [
    (False, False, False, False), (True, False, False, False), (True, True, False, False),
    (True, False, True, False), (True, False, True, True)])
async def test_full_pipeline_preserves_visible_topic_without_freezing_editorial_title(
    preserve, edit_title, accounting, redundant_support,
):
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    planned = 'Inside the office settlement'
    authored = 'Inspection and approval'
    expected = planned + ' — ' + authored if preserve else authored
    revised = 'Corrected source-grounded topic'
    stages = []
    raw_author = unit_course('SRC1', 'Retained teaching.')
    raw_author['lessons'][0]['title'] = authored
    original_wire = copy.deepcopy(raw_author)

    async def stage(name, group, messages, fmt, validator):
        policy = SIMPLE_COURSE_REVIEW_V11_POLICY if accounting else SIMPLE_COURSE_REVIEW_V10_POLICY
        assert simple_stage_allowed(name, group + ':output=32768', fmt, policy=policy, validator=validator)
        payload = json.loads(messages[1]['content'])
        props = fmt['json_schema']['schema']['properties']
        if ':plan:' in group:
            role = 'plan'
            ids = [s['id'] for s in payload['source_slices'] if s['text'].strip()]
            value = {'source_fingerprint': packet.fingerprint,
                'slices_fingerprint': payload['slices_fingerprint'], 'title': 'Course',
                'units': [{'id': 'one', 'title': planned, 'supporting_slices': ids[:1] if redundant_support else [],
                    'primary_slices': ids[:-1] if accounting else ids}],
                'non_teaching': []}
        elif ':plan-accounting:' in group:
            role = 'accounting'
            value = {'source_fingerprint': packet.fingerprint, 'plan_fingerprint': payload['plan_fingerprint'],
                'assignments': [{'slice_id': payload['missing_slices'][0]['id'], 'role': 'non_teaching',
                    'unit_id': '', 'reason': 'Administrative source context.'}], 'new_units': []}
        elif ':author-unit:' in group:
            role, value = 'author', copy.deepcopy(raw_author)
        elif ':editor-joint:' in group:
            role = 'joint'
            lesson = payload['original_course']['lessons'][0]
            assert lesson['title'] == expected
            value = {'source_fingerprint': packet.fingerprint,
                'draft_fingerprint': payload['draft_fingerprint'], 'body_edits': [],
                'title_edits': [{'lesson_id': lesson['id'], 'title': revised}] if edit_title else [],
                'question_edits': [], 'added_lessons': [], 'source_questions': [],
                'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1']}]}
            if 'finding_dispositions' in props:
                value['finding_dispositions'] = []
        else:
            role = 'bank' if ':review-bank:' in group else 'unit' if ':review-unit:' in group else 'global'
            rows = payload.get('assessment_cards', payload.get('unapproved_question_cards')) if role == 'bank' else payload['lessons']
            title = rows[0]['lesson_title'] if role == 'bank' else rows[0]['title']
            assert title == (revised if role == 'bank' and edit_title else expected)
            value = {'source_fingerprint': packet.fingerprint,
                'course_fingerprint': props['course_fingerprint']['enum'][0],
                'summary': 'Synthetic assembly proof only, not semantic approval.',
                'findings': [], 'source_notes': [],
                'narrative_sources': {row.get('lesson_id', row['id']): ['SRC1'] for row in rows}}
        stages.append(role)
        validator(value)
        return value

    kwargs = {'retain_unit_title_context': True} if preserve else {}
    result = (await run_simple_course_editor_v11(packet, corpus, {}, stage) if accounting
              else await run_simple_course_editor_v10(packet, corpus, {}, stage, **kwargs))
    assert stages == ['plan'] + (['accounting'] if accounting else []) + ['author', 'unit', 'global', 'joint', 'bank']
    assert raw_author == original_wire
    if redundant_support:
        normalization = result.review['source_plan_role_normalization']
        assert normalization['original_plan']['units'][0]['supporting_slices']
        assert normalization['semantic_approval'] is False
        assert not result.plan['units'][0]['supporting_slices']
    assert result.draft['lessons'][0]['title'] == expected
    assert result.course['lessons'][0]['title'] == (revised if edit_title else expected)
    assert result.course['lessons'][0]['content'] == original_wire['lessons'][0]['content']
    assert result.course['lessons'][0]['questions'] == result.draft['lessons'][0]['questions']
    artifacts = simple_course_artifacts(result, corpus, packet, 'a' * 64,
        review_policy=SIMPLE_COURSE_REVIEW_V11_POLICY if accounting else SIMPLE_COURSE_REVIEW_V10_POLICY)
    assert artifacts.assessment.assessments[0].lesson_title == result.course['lessons'][0]['title']
