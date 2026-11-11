"""Raw generic-cloud JSON through V6 owned pending stages; no network."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V6_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course
from tests.unit.test_v3_simple_owned_transport_v6 import fresh_journal


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['none', 'required_null', 'nonnull_extra'])
async def test_v6_cloud_raw_delta_null_custody_and_cold_replay(monkeypatch, fault):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V6_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    calls = []

    class SyntheticCloud:
        async def ainvoke(self, messages, *, response_format):
            payload = json.loads(messages[1]['content'])
            kind = response_format['json_schema']['name']
            role = ('plan' if kind == 'simple_semantic_source_plan_v1' else
                    'author' if kind == 'practical_course' else
                    'body' if 'teaching_units' in payload else 'cards')
            calls.append(role)
            if role == 'plan':
                ids = [s['id'] for s in payload['source_slices'] if s['text'].strip()]
                raw = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                    'title': 'Course', 'units': [{'id': 'unit', 'title': 'Topic', 'primary_slices': ids,
                                                   'supporting_slices': []}], 'non_teaching': []}
            elif role == 'author':
                raw = unit_course('SRC1', 'Original lesson')
                raw['lessons'][0]['questions'][0]['synthetic_null'] = None
            else:
                lessons = payload['teaching_units'] if role == 'body' else payload['current_learning_units']['lessons']
                raw = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                    'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                    'lesson_sources': [{'lesson_id': lessons[0]['id'], 'source_refs': ['SRC1'],
                                        'synthetic_null': None}], 'source_questions': []}
                if fault == 'required_null' and role == 'body':
                    raw['body_edits'] = None
                elif fault == 'nonnull_extra' and role == 'body':
                    raw['lesson_sources'][0]['synthetic_null'] = 'unexpected'
            return SimpleNamespace(content=json.dumps(raw), finish_reason='stop')

    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=SyntheticCloud(), extraction_journal=journal,
                direct_client=None, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_V6_POLICY,
                route_fingerprint='d' * 64)
    if fault != 'none':
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate_v3_course_from_corpus(**args)
        assert calls == ['plan', 'author', 'body']
        return
    first = await generate_v3_course_from_corpus(**args)
    replay = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
    assert calls == ['plan', 'author', 'body', 'cards'] and first.content == replay.content
    results = [value for key, value in fake.values.items() if key.startswith('v3-stage-result:')]
    assert len(results) == 4
    custody = [row['author_custody'] for row in results if 'author_custody' in row]
    assert len(custody) == 3
    assert '/lessons/0/questions/0/synthetic_null' in str(custody)
    assert '/lesson_sources/0/synthetic_null' in str(custody)
