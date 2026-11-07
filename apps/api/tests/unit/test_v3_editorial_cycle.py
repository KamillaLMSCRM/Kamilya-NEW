import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_editorial_cycle import run_editorial_cycle
from app.modules.ai.v3.practical_logic import SOURCE_LOGIC_GUIDE
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_editorial_contract import review_value, revision_value
from tests.unit.test_v3_practical_bank_cycle import bank_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
async def test_editor_receives_normalized_author_ids_without_changing_wire_response(case):
    corpus, packet, original = case
    original = copy.deepcopy(original)
    second = copy.deepcopy(original['lessons'][0])
    second['id'] = 'l2'
    original['lessons'].append(second)
    view = PracticalModelView(packet)
    wire = view.encode(original)
    saved = copy.deepcopy(wire)

    async def stage(name, group, messages, fmt, validate):
        if name == 'lesson':
            validate(wire)
            return wire
        content = messages[1]['content']
        received = json.loads(content.split('\nFULL_COURSE_WITH_KEYS_AND_EXPLANATIONS_JSON\n')[1])
        ids = [q['id'] for lesson in received['lessons'] for q in lesson['questions']]
        assert len(ids) == len(set(ids))
        assert wire == saved
        raise RuntimeError('review reached')

    with pytest.raises(RuntimeError, match='review reached'):
        await run_editorial_cycle(packet, corpus, CourseIntent(purpose='Training', audience='Staff'), (), stage)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['clean', 'material', 'source', 'advisory'])
async def test_editorial_role_sees_whole_course_blind_check_stays_blind_and_draft_survives(case, mode):
    corpus, packet, original = case
    original = copy.deepcopy(original)
    original['lessons'][0]['content'] = 'Authored teaching explanation visible to the keyed editor.'
    view = PracticalModelView(packet)
    calls = []
    candidate = copy.deepcopy(original)

    async def stage(name, group, messages, fmt, validate):
        nonlocal candidate
        calls.append((name, group))
        if 'editorial-answer' not in group:
            assert SOURCE_LOGIC_GUIDE in messages[0]['content']
        if name == 'lesson':
            value = original
        elif 'editorial:review' in group:
            assert 'correct_index' in messages[1]['content'] and 'explanation' in messages[1]['content']
            assert original['lessons'][0]['content'] in messages[1]['content']
            value = review_value(packet, original, domain='source' if mode == 'source' else 'assessment',
                severity='advisory' if mode == 'advisory' else 'material')
            if mode == 'clean':
                value['findings'] = []
        elif name == 'repair':
            candidate['lessons'][0]['questions'][0]['prompt'] = 'What two actions are required?'
            value = revision_value(packet, original, candidate)
        else:
            body = messages[1]['content']
            questions = json.loads(body.split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0])
            assert all(set(row) == {'lesson_id', 'id', 'prompt', 'choices'} for row in questions)
            assert 'correct_index' not in body and 'explanation' not in body
            assert original['lessons'][0]['content'] not in body
            value = bank_value(packet, candidate)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_editorial_cycle(packet, corpus, CourseIntent(purpose='Training', audience='Staff'), (), stage)
    assert len(calls) == (4 if mode == 'material' else 3)
    assert result.editorial_review and not result.source_core
    assert len(result.course['lessons'][0]['questions']) == 2
    assert result.history[0]['blind_answer_review'] is True
    if mode in {'material', 'source'}:
        assert not result.decision.accepted and result.decision.feedback
        status = result.decision.feedback[0]['evidence']['status']
        assert status == ('EDITED_UNVERIFIED' if mode == 'material' else 'SOURCE_UNRESOLVED')
    else:
        assert result.decision.accepted
    assert result.course['lessons'][0]['questions'][1] == original['lessons'][0]['questions'][1]


@pytest.mark.asyncio
async def test_unknown_review_outcome_propagates_without_repair_or_blind_retry(case):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []

    async def stage(name, group, messages, fmt, validate):
        calls.append(group)
        if name == 'lesson':
            wire = view.encode(course)
            validate(wire)
            return wire
        raise ExtractionOutcomeUnknownError('unknown provider outcome')

    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_editorial_cycle(packet, corpus, CourseIntent(purpose='Training', audience='Staff'), (), stage)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_rewritten_prose_does_not_inherit_original_review_source_ownership(case):
    from app.modules.ai.v3.practical_service import practical_artifacts

    corpus, packet, original = case
    view = PracticalModelView(packet)
    candidate = copy.deepcopy(original)
    candidate['lessons'][0]['content'] = packet.blocks[-1].text

    async def stage(name, group, messages, fmt, validate):
        if name == 'lesson':
            value = original
        elif 'editorial:review' in group:
            value = review_value(packet, original, kind='lesson', target='l1', domain='content')
            value['narrative_sources'] = {'l1': [packet.blocks[0].block_id]}
        elif name == 'repair':
            value = revision_value(packet, original, candidate)
            value['lesson_sources'] = [{'lesson_id': 'l1', 'source_refs': [packet.blocks[-1].block_id]}]
        else:
            value = bank_value(packet, candidate)
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_editorial_cycle(packet, corpus, CourseIntent(purpose='Training', audience='Staff'), (), stage)
    assert result.review['narrative_sources']['l1'] == [packet.blocks[-1].block_id]
    assert result.history[0]['editorial_review']['narrative_sources']['l1'] == [packet.blocks[0].block_id]
    assert result.history[0]['unverified_revised_prose'] == ['l1']
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['practical_unverified_prose_lesson_ids'] == ['l1']


@pytest.mark.asyncio
@pytest.mark.parametrize('roundtrip', [False, True], ids=['historical-v31', 'jsonb-v32'])
async def test_real_stage_journal_recovers_after_received_revision_without_repeating_calls(case, roundtrip):
    from app.modules.ai.v3.practical_service import generate_practical_course
    from app.modules.ai.v3.revision_policy import CANONICAL_EDITORIAL_REVIEW_POLICY, EDITORIAL_PRACTICAL_REVIEW_POLICY
    from tests.unit.test_v3_partitioned_extraction import Journal

    corpus, packet, original = case
    candidate = copy.deepcopy(original)
    candidate['lessons'][0]['questions'][0]['prompt'] = 'Which two actions complete the procedure?'
    view = PracticalModelView(packet)
    calls = []

    class InterruptedJournal(Journal):
        interrupted = False

        async def save_value(self, key, value):
            await super().save_value(key, value)
            received = sum(key.startswith('v3-stage-result:') for key in self.values)
            if received == 3 and not self.interrupted:
                self.interrupted = True
                raise RuntimeError('simulated process interruption after durable revision')

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        if name == 'practical_course':
            value = original
        elif name == 'v3_practical_editorial_review_v1':
            value = review_value(packet, original)
        elif name == 'v3_practical_editorial_revision_v1':
            value = revision_value(packet, original, candidate)
        else:
            value = bank_value(packet, candidate)
        return view.encode(value)

    journal = InterruptedJournal()
    policy = CANONICAL_EDITORIAL_REVIEW_POLICY if roundtrip else EDITORIAL_PRACTICAL_REVIEW_POLICY

    async def generate():
        return await generate_practical_course(corpus, intent=CourseIntent(purpose='Training', audience='Staff'),
            invoke=invoke, source_sha256='a' * 64, journal=journal, route_fingerprint='b' * 64,
            review_policy=policy)

    with pytest.raises(RuntimeError, match='simulated process interruption'):
        await generate()
    assert len(calls) == 3 and sum(key.startswith('v3-stage-result:') for key in journal.values) == 3
    if roundtrip:
        # JSONB does not preserve provider object insertion order; arrays are unchanged.
        def jsonb_order(value):
            if isinstance(value, dict):
                return {k: jsonb_order(value[k]) for k in sorted(value, key=lambda k: (len(k.encode()), k.encode()))}
            if isinstance(value, list):
                return [jsonb_order(item) for item in value]
            return value
        journal.values = jsonb_order(journal.values)
    artifacts = await generate()
    assert len(calls) == 4  # Only the missing final blind check is dispatched.
    assert artifacts.diagnostics['practical_course'] == candidate
    assert artifacts.diagnostics['draft_review']['human_review_required'] is True
    assert artifacts.diagnostics['quality_verdict'] == 'needs_review'
    assert artifacts.diagnostics['v3_review_policy'] == policy
    await generate()
    assert len(calls) == 4
