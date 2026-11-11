"""V5 separate editors through owned stages with synthetic provider responses."""
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
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V5_POLICY
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
    result.expected_review_policy = SIMPLE_COURSE_REVIEW_V5_POLICY
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(('interrupted', 'fault'), [(False, None), (True, None),
    (False, 'body_question_edit'), (False, 'cards_body_edit'), (False, 'cards_title_edit'), (False, 'cards_added_lesson')])
async def test_v5_owned_isolated_editors_and_replay(monkeypatch, interrupted, fault):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V5_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    view = PracticalModelView(packet)
    client = client_for(journal)
    calls, captures = [], []
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('v5_owned_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    image = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'

    async def invoke(capability, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        request = json.loads(client._prepared[capability])
        fmt = request['response_format']
        assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
        payload = json.loads(request['messages'][1]['content'])
        kind = fmt['json_schema']['name']
        role = ('body' if 'teaching_units' in payload else 'cards' if 'current_learning_units' in payload
                else 'plan' if kind == 'simple_source_unit_plan_v2' else 'author')
        calls.append(role)
        blocks = payload['source_blocks']
        assert [''.join(s['text'] for s in block['segments']) for block in blocks] == [b.text for b in packet.blocks]
        assert sum('First topic instructs action.' in ''.join(s['text'] for s in block['segments']) for block in blocks) == 1
        assert any(s['origin'] == 'visual_ocr' for block in blocks for s in block['segments'])
        if role == 'plan':
            plan = {'source_fingerprint': packet.fingerprint, 'title': 'Course',
                'units': [{'id': 'first', 'title': 'First', 'primary_refs': [packet.blocks[0].block_id], 'supporting_refs': []},
                          {'id': 'second', 'title': 'Second', 'primary_refs': [packet.blocks[1].block_id], 'supporting_refs': [packet.blocks[0].block_id]}],
                'non_teaching': [{'source_refs': [packet.blocks[2].block_id], 'reason': 'Administrative'}]}
            result = encode_source_unit_plan(plan, view)
        elif role == 'author':
            assert payload['units'][1]['supporting_refs'] == ['SRC1']
            lessons = []
            for i, unit in enumerate(payload['units']):
                body = 'Old intro.\n\n| Group | Limit |\n| A | 10 |\n\nAggregate entries.' + ('\n' + image if i == 0 else '')
                lesson = unit_course(unit['primary_refs'][0], body)['lessons'][0]
                lesson['id'] = unit['lesson_id']
                for question in lesson['questions']:
                    question['id'] = lesson['id'] + '-' + question['id']
                    question['prompt'] = 'HIDDEN_CARD_SENTINEL ' + question['id']
                    question['explanation'] = 'HIDDEN_EXPLANATION_SENTINEL'
                lessons.append(lesson)
            raw = {'title': 'Course', 'lessons': lessons, 'extra': None}
            captures.append(json.dumps(raw))
            result = normalize_practical_author(captures[-1], fmt)
        else:
            assert kind == 'simple_course_delta_editor_v1'
            raw = {'source_fingerprint': payload['source_fingerprint'], 'draft_fingerprint': payload['draft_fingerprint'],
                   'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                   'lesson_sources': [{'lesson_id': 'unit-1-lesson', 'source_refs': ['SRC1' if role == 'body' else 'SRC2']},
                                      {'lesson_id': 'unit-2-lesson', 'source_refs': ['SRC2']}],
                   'source_questions': [{'question': 'Shared source uncertainty', 'source_refs': ['SRC1']},
                                        {'question': 'Body source uncertainty' if role == 'body' else 'Card source uncertainty',
                                         'source_refs': ['SRC1' if role == 'body' else 'SRC2']}], 'extra': None}
            if role == 'body':
                text = request['messages'][1]['content']
                assert all(s not in text for s in ('HIDDEN_CARD_SENTINEL', 'HIDDEN_EXPLANATION_SENTINEL', 'correct_index', 'current_learning_units'))
                assert all(set(row) == {'id', 'title', 'content'} for row in payload['teaching_units'])
                raw['body_edits'] = [{'lesson_id': 'unit-1-lesson', 'before': 'Old intro.', 'after': 'Improved intro.'}]
                if fault == 'body_question_edit':
                    q = unit_course('SRC1', 'x')['lessons'][0]['questions'][0]
                    q['id'] = 'unit-1-lesson-q0'
                    raw['question_edits'] = [{'lesson_id': 'unit-1-lesson', 'question': q}]
            else:
                intermediate = view.decode(payload['current_learning_units'])
                assert payload['draft_fingerprint'] == _digest(intermediate)
                assert intermediate['lessons'][0]['content'].startswith('Improved intro.')
                q = payload['current_learning_units']['lessons'][0]['questions'][0]
                q['prompt'] = 'Edited card'
                raw['question_edits'] = [{'lesson_id': 'unit-1-lesson', 'question': q}]
                if fault == 'cards_body_edit':
                    raw['body_edits'] = [{'lesson_id': 'unit-1-lesson', 'before': 'Improved intro.', 'after': 'bad'}]
                elif fault == 'cards_title_edit':
                    raw['title_edits'] = [{'lesson_id': 'unit-1-lesson', 'title': 'bad'}]
                elif fault == 'cards_added_lesson':
                    new_lesson = unit_course('SRC1', 'extra')['lessons'][0]
                    new_lesson['id'] = 'new-lesson'
                    for q2 in new_lesson['questions']:
                        q2['id'] += '-new'
                    raw['added_lessons'] = [new_lesson]
                    raw['lesson_sources'].append({'lesson_id': 'new-lesson', 'source_refs': ['SRC1']})
            captures.append(json.dumps(raw))
            result = normalize_practical_author(captures[-1], fmt)
        return SimpleNamespace(content=result, model='gpt-6-luna',
            usage=SimpleNamespace(input_tokens=100, output_tokens=25, cached_input_tokens=0, reasoning_tokens=5))

    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=None, extraction_journal=journal,
        direct_client=client, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_V5_POLICY,
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
            assert str(failure.value.__cause__) == ('simple_v5_body_question_edit_forbidden' if fault == 'body_question_edit'
                                                    else 'simple_v5_cards_body_edit_forbidden')
            assert calls == (['plan', 'author', 'body'] if fault == 'body_question_edit' else ['plan', 'author', 'body', 'cards'])
            return
        if interrupted:
            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert calls == ['plan', 'author']
            args['extraction_journal'] = fresh_journal(journal, fake)
        first = await generate_v3_course_from_corpus(**args, progress_callback=progress)
        replay = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
        assert calls == ['plan', 'author', 'body', 'cards']
        assert events[-4:] == [(i, 4) for i in range(1, 5)]
        assert first.content == replay.content and first.assessment == replay.assessment
        assert len([k for k in fake.values if k.startswith('v3-stage-result:')]) == 4
        diagnostics = first.diagnostics
        lessons = diagnostics['practical_course']['lessons']
        assert lessons[0]['content'] == 'Improved intro.\n\n| Group | Limit |\n| A | 10 |\n\nAggregate entries.\n' + image
        assert lessons[0]['questions'][0]['prompt'] == 'Edited card'
        assert lessons[0]['questions'][1]['prompt'].startswith('HIDDEN_CARD_SENTINEL')
        assert diagnostics['simple_lesson_sources'][0]['source_refs'] == [packet.blocks[0].block_id, packet.blocks[1].block_id]
        review = diagnostics['simple_review']
        assert {q['question'] for q in review['source_questions']} == {'Body source uncertainty', 'Card source uncertainty', 'Shared source uncertainty'}
        assert len(review['source_questions']) == 3
        assert review['editor_delta_receipts']['cards']['draft_fingerprint'] == review['editor_delta_receipts']['body']['result_fingerprint']
        assert diagnostics['requires_source_review'] and diagnostics['requires_editorial_review']
    finally:
        client.close()
