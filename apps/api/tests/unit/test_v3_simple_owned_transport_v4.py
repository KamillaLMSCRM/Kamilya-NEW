"""V4 assembled owned stages using real preparation and synthetic responses."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.practical_author_transport import normalize_practical_author
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V4_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from app.modules.ai.v3.simple_source_unit_plan import encode_source_unit_plan
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


class BetweenStagesError(Exception):
    pass


def fresh_journal(journal, fake):
    result = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id, fake.sessions,
                                 verify_source=journal.verify_source)
    result.repository = fake
    result._lock_delivery = fake._lock_delivery
    result._owned_key = fake._owned_key
    result.read_owned_value_in_session = fake.read_owned_value_in_session
    result.review_policy_bound = True
    result.expected_review_policy = SIMPLE_COURSE_REVIEW_V4_POLICY
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(('interrupted', 'fault'), [(False, None), (True, None),
    (False, 'invalid_anchor'), (False, 'foreign_ref'), (False, 'drop_last_image')])
async def test_v4_owned_three_stages_and_cold_replay(monkeypatch, interrupted, fault):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V4_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    client = client_for(journal)
    invoked, captured = [], []
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('v4_owned_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    image = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'

    async def invoke(capability, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        request = json.loads(client._prepared[capability])
        fmt = request['response_format']
        assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
        payload = json.loads(request['messages'][1]['content'])
        name = fmt['json_schema']['name']
        invoked.append(name)
        blocks = payload['source_blocks']
        assert [row['id'] for row in blocks] == ['SRC1', 'SRC2', 'SRC3']
        assert [''.join(segment['text'] for segment in row['segments']) for row in blocks] == [b.text for b in packet.blocks]
        assert sum('First topic instructs action.' in ''.join(segment['text'] for segment in row['segments']) for row in blocks) == 1
        segments = [segment for row in blocks for segment in row['segments']]
        assert any(row['origin'] == 'visual_ocr' and 'Visual OCR sentinel' in row['text'] for row in segments)
        assert any(row['origin'] == 'visual_description' and 'Visual description sentinel' in row['text'] for row in segments)
        assert 'private-storage-path' not in json.dumps(payload)
        if name == 'simple_source_unit_plan_v2':
            plan = {'source_fingerprint': packet.fingerprint, 'title': 'Course',
                'units': [{'id': 'first', 'title': 'First', 'primary_refs': [packet.blocks[0].block_id], 'supporting_refs': []},
                          {'id': 'second', 'title': 'Second', 'primary_refs': [packet.blocks[1].block_id],
                           'supporting_refs': [packet.blocks[0].block_id]}],
                'non_teaching': [{'source_refs': [packet.blocks[2].block_id], 'reason': 'Administrative'}]}
            result = encode_source_unit_plan(plan, PracticalModelView(packet))
        elif name == 'practical_course':
            assert payload['units'][1]['supporting_refs'] == ['SRC1']
            lessons = []
            for i, unit in enumerate(payload['units']):
                body = 'Old intro.\n\n| Group | Limit |\n| A | 10 |\n\nAggregate entries.'
                if i == 0:
                    body += '\n' + image
                lesson = unit_course(unit['primary_refs'][0], body)['lessons'][0]
                lesson['id'] = unit['lesson_id']
                for question in lesson['questions']:
                    question['id'] = unit['lesson_id'] + '-' + question['id']
                lessons.append(lesson)
            raw = {'title': 'Course', 'lessons': lessons, 'extra': None}
            captured.append(json.dumps(raw))
            result = normalize_practical_author(captured[-1], fmt)
        else:
            assert name == 'simple_course_delta_editor_v1'
            assert payload['units'][1]['supporting_refs'] == ['SRC1']
            authored = payload['current_learning_units']
            edit = {'lesson_id': authored['lessons'][0]['id'], 'before': 'Old intro.', 'after': 'Improved intro.'}
            if fault == 'invalid_anchor':
                edit['before'] = 'not in the original'
            elif fault == 'drop_last_image':
                edit.update(before=image, after='')
            refs = ['SRC999'] if fault == 'foreign_ref' else ['SRC1', 'SRC2']
            raw = {'source_fingerprint': payload['source_fingerprint'], 'draft_fingerprint': payload['draft_fingerprint'],
                'body_edits': [edit], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                'lesson_sources': [{'lesson_id': authored['lessons'][0]['id'], 'source_refs': refs},
                                   {'lesson_id': authored['lessons'][1]['id'], 'source_refs': ['SRC2']}],
                'source_questions': [], 'extra': None}
            captured.append(json.dumps(raw))
            result = normalize_practical_author(captured[-1], fmt)
        return SimpleNamespace(content=result, model='gpt-6-luna',
            usage=SimpleNamespace(input_tokens=100, output_tokens=25, cached_input_tokens=0, reasoning_tokens=5))

    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=None, extraction_journal=journal,
        direct_client=client, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_V4_POLICY,
        route_fingerprint='d' * 64)
    events = []

    async def progress(stage, completed, total, provider, attempt):
        events.append((completed, total))
        if interrupted and completed == 2 and len(events) == 2:
            raise BetweenStagesError()

    try:
        if fault:
            with pytest.raises(ExtractionOutcomeUnknownError, match='v3_pending_provider_outcome_unknown') as failure:
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert isinstance(failure.value.__cause__, ValueError)
            assert str(failure.value.__cause__) == {'invalid_anchor': 'simple_delta_anchor_invalid',
                'foreign_ref': 'practical_author_transport_invalid',
                'drop_last_image': 'simple_unit_editor_media_changed'}[fault]
            assert len([key for key in fake.values if key.startswith('v3-stage-result:')]) == 2
            assert len(invoked) == 3
            with pytest.raises(ExtractionOutcomeUnknownError):
                await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
            assert len(invoked) == 3
            return
        if interrupted:
            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert invoked == ['simple_source_unit_plan_v2', 'practical_course']
            args['extraction_journal'] = fresh_journal(journal, fake)
        first = await generate_v3_course_from_corpus(**args, progress_callback=progress)
        cold = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
        assert invoked == ['simple_source_unit_plan_v2', 'practical_course', 'simple_course_delta_editor_v1']
        assert events[-3:] == [(1, 3), (2, 3), (3, 3)]
        assert first.content == cold.content and first.assessment == cold.assessment
        stored = [value for key, value in fake.values.items() if key.startswith('v3-stage-result:')]
        assert len(stored) == 3
        custody = [value['author_custody'] for value in stored if 'author_custody' in value]
        assert len(custody) == 2 and {item['raw_text'] for item in custody} == set(captured)
        diagnostics = first.diagnostics
        lessons = diagnostics['practical_course']['lessons']
        assert lessons[0]['content'] == 'Improved intro.\n\n| Group | Limit |\n| A | 10 |\n\nAggregate entries.\n' + image
        assert lessons[1]['content'] == 'Old intro.\n\n| Group | Limit |\n| A | 10 |\n\nAggregate entries.'
        assert [[q['id'] for q in lesson['questions']] for lesson in lessons] == [
            [f'unit-{i}-lesson-q{j}' for j in range(3)] for i in (1, 2)]
        authored_wire = json.loads(captured[0])
        del authored_wire['extra']
        authored = PracticalModelView(packet).decode(authored_wire)
        assert [lesson['questions'] for lesson in lessons] == [lesson['questions'] for lesson in authored['lessons']]
        assert diagnostics['simple_lesson_sources'] == [
            {'lesson_id': 'unit-1-lesson', 'source_refs': [packet.blocks[0].block_id, packet.blocks[1].block_id]},
            {'lesson_id': 'unit-2-lesson', 'source_refs': [packet.blocks[1].block_id]}]
        assert diagnostics['requires_editorial_review'] and not diagnostics['automated_review_passed']
        receipt = diagnostics['simple_review']['editor_delta_receipt']
        assert receipt['source_fingerprint'] == packet.fingerprint
        assert receipt['draft_fingerprint'] == diagnostics['simple_review']['draft_fingerprint']
    finally:
        client.close()
