import hashlib
import json
from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.simple_course_editor_v12 import run_simple_course_editor_v12
from app.modules.ai.v3.source_access_contract import inner_format
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from tests.unit.test_v3_simple_owned_transport_v3 import unit_course
from tests.unit.test_v3_simple_source_unit import corpus_for


@pytest.mark.asyncio
@pytest.mark.parametrize('foreign_edit', [False, True])
async def test_v12_large_course_reuses_course_review_and_owns_each_joint_batch(foreign_edit):
    text = '\n\n'.join(f'Approved independent decision {i}.' for i in range(6))
    source = corpus_for(text)
    doc = source.documents[0]
    _, spans = render_text(text, [])
    approval = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approved', text, text,
        hashlib.sha256(text.encode()).hexdigest(), tuple(spans), {})
    corpus = replace(source, documents=(replace(doc, source_text=text, editorial_document=approval),))
    packet = build_practical_source_packet(corpus)
    stored = {}
    calls = []
    jointly_reviewed = []
    findings_seen = []
    progress = []

    async def planned(count):
        progress.append(count)

    async def stage(name, group, messages, fmt, validator):
        payload = json.loads(messages[1]['content'])
        outer = fmt['json_schema']['schema']['properties']
        keys = ('source_fingerprint', 'context_fingerprint', 'base_group')
        response = {key: outer[key]['enum'][0] for key in keys}
        response['lookup_ids'] = []
        base = response['base_group']
        props = inner_format(fmt)['json_schema']['schema']['properties']
        if group in stored:
            return validator(stored[group])

        calls.append(base)
        if ':plan:v11:' in base:
            units = [{'id': f'unit-{i}', 'title': f'Approved decision {i}', 'primary_slices': [row['id']],
                      'supporting_slices': []} for i, row in enumerate(payload['source_slices']) if row['text'].strip()]
            assert len(units) == 6
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': props['slices_fingerprint']['enum'][0],
                     'title': 'Course', 'units': units, 'non_teaching': []}
        elif ':author-unit:' in base:
            ref = payload['primary_slices'][0]['source_ref']
            value = unit_course(ref, 'Unchanged teaching body for ' + ref)
        elif ':editor-joint:' in base:
            lessons = payload['original_course']['lessons']
            assert len(lessons) == 2 and len(payload['course_outline']) == 6
            jointly_reviewed.extend(lesson['id'] for lesson in lessons)
            findings_seen.extend(item['id'] for item in payload['material_findings'])
            block = ('BODY6' if foreign_edit else lessons[0]['body_blocks'][0]['id'])
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                     'body_edits': [{'block_id': block, 'after': 'Scoped model revision.'}],
                     'title_edits': [], 'question_edits': [], 'added_lessons': [],
                     'lesson_sources': [{'lesson_id': lessons[0]['id'],
                                         'source_refs': lessons[0]['questions'][0]['source_refs']}],
                     'source_questions': [], 'finding_dispositions': []}
        elif ':repair-evidence:' in base:
            value = {key: props[key]['enum'][0] for key in
                     ('source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')}
            value['bindings'] = {key: val['enum'][0] for key, val in props['bindings']['properties'].items()}
        else:
            findings = []
            if ':review-content:' in base:
                findings.append({'domain': 'content', 'severity': 'material',
                    'target': {'kind': 'course', 'id': 'course'}, 'problem': 'Missing decision',
                    'basis': 'Approved independent decision 4.', 'correction': 'Teach the approved decision.',
                    'source_refs': ['SRC5']})
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': props['course_fingerprint']['enum'][0],
                     'summary': 'Compared teaching', 'findings': findings, 'source_notes': [],
                     'narrative_sources': {key: [val['items']['enum'][0]]
                                           for key, val in props['narrative_sources']['properties'].items()}}
        response['results'] = [value]
        validator(response)
        stored[group] = response
        return response

    async def run():
        return await run_simple_course_editor_v12(packet, corpus, CourseIntent(), stage,
                                                   literal_budget=10000, lookup_rounds=1, planned_callback=planned)

    if foreign_edit:
        with pytest.raises(ValueError, match='simple_v12_joint_batch_scope_invalid'):
            await run()
        return
    first = await run()
    assert len(set(jointly_reviewed)) == len(jointly_reviewed) == len(first.course['lessons']) == 6
    assert len(set(findings_seen)) == len(findings_seen) == 1
    assert sum(':editor-joint:' in call for call in calls) == 3
    assert sum(':review-content:' in call for call in calls) == 1
    assert len(stored) == progress[-1]
    assert first.course['lessons'][1] == first.draft['lessons'][1]
    assert first.course['lessons'][0]['content'] == 'Scoped model revision.'
    snapshot = list(calls)
    replay = await run()
    assert calls == snapshot
    assert first.course == replay.course
