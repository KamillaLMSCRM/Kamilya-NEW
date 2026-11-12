"""V8 cloud raw JSON through owned pending journal, without a provider."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V8_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course
from tests.unit.test_v3_simple_owned_transport_v8 import BetweenStagesError, fresh_journal, unit_reading


@pytest.mark.asyncio
@pytest.mark.parametrize(('fault', 'interrupt_after'), [('none', 0), ('none', 2), ('none', 3), ('none', 4),
    ('required_null', 0), ('nonnull_extra', 0), ('outside_unit', 0)])
async def test_v8_cloud_owned_pending_and_replay(monkeypatch, fault, interrupt_after):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V8_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    calls = []

    class SyntheticCloud:
        async def ainvoke(self, messages, *, response_format):
            payload = json.loads(messages[1]['content'])
            kind = response_format['json_schema']['name']
            role = ('plan' if kind == 'simple_semantic_source_plan_v1' else
                    'read' if kind == 'v3_practical_source_semantics_v1' else
                    'author' if kind == 'practical_course' else 'body' if 'teaching_units' in payload else 'cards')
            calls.append(role)
            if role == 'plan':
                def ids(ref):
                    return [s['id'] for s in payload['source_slices'] if s['source_ref'] == ref and s['text'].strip()]
                raw = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                    'title': 'Course', 'units': [{'id': 'one', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                        {'id': 'two', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
                    'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Context'}]}
            elif role == 'read':
                ref = payload['primary_slices'][0]['source_ref']
                raw = unit_reading(packet, ref)
                if fault == 'outside_unit':
                    raw['sections'][0]['rules'][0]['source_refs'] = ['SRC2' if ref == 'SRC1' else 'SRC1']
            elif role == 'author':
                ref = payload['primary_slices'][0]['source_ref']
                raw = unit_course(ref, 'Original lesson')
                raw['lessons'][0]['questions'][0]['synthetic_null'] = None
            else:
                lessons = payload['teaching_units'] if role == 'body' else payload['current_learning_units']['lessons']
                raw = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                    'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                    'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1' if i == 0 else 'SRC2'],
                                        'synthetic_null': None} for i, lesson in enumerate(lessons)], 'source_questions': []}
                if fault == 'required_null' and role == 'body':
                    raw['body_edits'] = None
                elif fault == 'nonnull_extra' and role == 'body':
                    raw['lesson_sources'][0]['synthetic_null'] = 'unexpected'
            return SimpleNamespace(content=json.dumps(raw), finish_reason='stop')

    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = {'corpus': corpus, 'intent': CourseIntent(), 'generation_client': SyntheticCloud(), 'extraction_journal': journal,
            'direct_client': None, 'revision_policy': POLICY, 'review_policy': SIMPLE_COURSE_REVIEW_V8_POLICY,
            'route_fingerprint': 'd' * 64}
    if fault != 'none':
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate_v3_course_from_corpus(**args)
        assert calls[-1] == ('read' if fault == 'outside_unit' else 'body')
        return
    if interrupt_after:
        async def progress(_stage, completed, _total, _provider, _attempt):
            if completed == interrupt_after:
                raise BetweenStagesError()
        with pytest.raises(BetweenStagesError):
            await generate_v3_course_from_corpus(**args, progress_callback=progress)
        assert len(calls) == interrupt_after
        args['extraction_journal'] = fresh_journal(journal, fake)
    first = await generate_v3_course_from_corpus(**args)
    replay = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
    assert calls == ['plan', 'read', 'author', 'read', 'author', 'body', 'cards']
    assert first.content == replay.content and first.assessment == replay.assessment
    results = [value for key, value in fake.values.items() if key.startswith('v3-stage-result:')]
    assert len(results) == 7
    custody = [row['author_custody'] for row in results if 'author_custody' in row]
    assert len(custody) == 4
    assert '/lessons/0/questions/0/synthetic_null' in str(custody)
    assert '/lesson_sources/0/synthetic_null' in str(custody)
