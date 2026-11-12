"""V8 assembled stages through actual managed prepare/decode and owned journal."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.practical_author_transport import PracticalAuthorArtifact
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V8_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


class BetweenStagesError(Exception):
    pass


def fresh_journal(journal, fake):
    cold = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id, fake.sessions,
                               verify_source=journal.verify_source)
    cold.repository = fake
    cold._lock_delivery = fake._lock_delivery
    cold._owned_key = fake._owned_key
    cold.read_owned_value_in_session = fake.read_owned_value_in_session
    cold.review_policy_bound = True
    cold.expected_review_policy = SIMPLE_COURSE_REVIEW_V8_POLICY
    return cold


def unit_reading(packet, ref):
    return {'source_fingerprint': packet.fingerprint, 'sections': [{'section': 'Task', 'rules': [{
        'source_refs': [ref], 'source_quote': 'First topic instructs action.' if ref == 'SRC1' else 'not literal',
        'actor': 'Employee', 'action': 'DO_' + ref, 'object': 'Work', 'conditions': [], 'modality': 'must',
        'alternatives': [], 'limits': []}]}], 'uncertainties': [
            {'source_refs': [ref], 'source_quote': '', 'question': 'READER_ONLY_' + ref}]}


@pytest.mark.asyncio
@pytest.mark.parametrize(('interrupt_after', 'fault'), [(0, None), (2, None), (3, None), (4, None), (5, None),
    (0, 'required_null'), (0, 'nonnull_extra'), (0, 'bad_echo'), (0, 'read_required_null'),
    (0, 'read_nonnull_extra'), (0, 'read_bad_echo'), (0, 'outside_unit'), (0, 'drop_image'),
    (0, 'body_question'), (0, 'cards_body')])
async def test_v8_real_managed_owned_replay(monkeypatch, interrupt_after, fault):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V8_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    view = PracticalModelView(packet)
    client = client_for(journal)
    calls, events, plan_fingerprints = [], [], []
    spec = importlib.util.spec_from_file_location('v8_owned_runner', Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py')
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
        role = ('plan' if kind == 'simple_semantic_source_plan_v1' else
                'read' if kind == 'v3_practical_source_semantics_v1' else
                'author' if kind == 'practical_course' else 'body' if 'teaching_units' in payload else 'cards')
        calls.append(role)
        if role == 'plan':
            def ids(ref):
                return [row['id'] for row in payload['source_slices'] if row['source_ref'] == ref and row['text'].strip()]
            raw = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                'title': 'Course', 'units': [{'id': 'one', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                    {'id': 'two', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
                'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Context'}]}
            plan_fingerprints.append(_digest(raw))
        elif role == 'read':
            ref = payload['primary_slices'][0]['source_ref']
            enum = fmt['json_schema']['schema']['properties']['uncertainties']['items']['properties']['source_refs']['items']['enum']
            assert ref in enum and 'SRC3' not in enum
            assert 'HIDDEN_QUESTION' not in request['messages'][1]['content']
            raw = unit_reading(packet, ref)
            if fault == 'outside_unit':
                raw['sections'][0]['rules'][0]['source_refs'] = ['SRC2' if ref == 'SRC1' else 'SRC1']
            elif fault == 'read_required_null':
                raw['sections'] = None
            elif fault == 'read_nonnull_extra':
                raw['extra'] = 'unexpected'
        elif role == 'author':
            ref = payload['primary_slices'][0]['source_ref']
            reading = payload['independent_source_reading']
            rules = [rule for section in reading['sections'] for rule in section['rules']]
            assert len(rules) == 1 and rules[0]['source_refs'] == [ref] and 'uncertainties' not in reading
            raw = unit_course(ref, 'Old intro.\n\nPreserve body.' + ('\n' + image if ref == 'SRC1' else ''))
            for question in raw['lessons'][0]['questions']:
                question['prompt'] = 'HIDDEN_QUESTION ' + question['id']
            raw['extra'] = None
            if fault == 'required_null':
                raw['lessons'] = None
            elif fault == 'nonnull_extra':
                raw['extra'] = 'unexpected'
        else:
            assert len(payload['independent_source_reading']['sections']) == 2
            if role == 'body':
                assert 'HIDDEN_QUESTION' not in request['messages'][1]['content']
                lessons = payload['teaching_units']
            else:
                lessons = payload['current_learning_units']['lessons']
                assert payload['draft_fingerprint'] == _digest(view.decode(payload['current_learning_units']))
            raw = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1' if i == 0 else 'SRC2']}
                                   for i, lesson in enumerate(lessons)], 'source_questions': [], 'extra': None}
            if role == 'body':
                raw['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': 'Old intro.', 'after': 'New intro.'}]
                if fault == 'drop_image':
                    raw['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': image, 'after': ''}]
                if fault == 'body_question':
                    raw['question_edits'] = [{'lesson_id': lessons[0]['id'], 'question': unit_course('SRC1', 'x')['lessons'][0]['questions'][0]}]
            else:
                question = lessons[0]['questions'][0]
                question['prompt'] = 'Edited question'
                raw['question_edits'] = [{'lesson_id': lessons[0]['id'], 'question': question}]
                if fault == 'cards_body':
                    raw['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': 'New intro.', 'after': 'bad'}]
        envelope = {'model': client.model, 'structured_output_policy': 'typed-json-object-v1',
            'response_format_sha256': '0' * 64 if (role == 'author' and fault == 'bad_echo') or
                (role == 'read' and fault == 'read_bad_echo') else response_contract_hash(fmt),
            'choices': [{'message': {'content': json.dumps(raw)}}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 25}}
        result, _ = client._decode_response(json.dumps(envelope).encode(), client._prepared[capability])
        if role not in {'plan', 'read'}:
            assert isinstance(result.content, PracticalAuthorArtifact) and '/extra' in result.content.receipt.removed_paths
        return result

    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = {'corpus': corpus, 'intent': CourseIntent(), 'generation_client': None, 'extraction_journal': journal,
            'direct_client': client, 'revision_policy': POLICY, 'review_policy': SIMPLE_COURSE_REVIEW_V8_POLICY,
            'route_fingerprint': 'd' * 64}
    async def progress(_stage, completed, total, _provider, _attempt):
        events.append((completed, total))
        if interrupt_after and completed == interrupt_after and len(events) == interrupt_after:
            raise BetweenStagesError()
    try:
        if fault:
            with pytest.raises(ExtractionOutcomeUnknownError) as failure:
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert calls[-1] == ('read' if fault.startswith('read_') or fault == 'outside_unit' else
                                 'author' if fault in ('required_null', 'nonnull_extra', 'bad_echo') else
                                 'body' if fault in ('drop_image', 'body_question') else 'cards')
            if fault == 'drop_image':
                assert str(failure.value.__cause__) == 'simple_v6_editor_media_changed'
            elif fault == 'body_question':
                assert str(failure.value.__cause__) == 'simple_v6_body_question_edit_forbidden'
            elif fault == 'cards_body':
                assert str(failure.value.__cause__) == 'simple_v6_cards_body_edit_forbidden'
            else:
                assert getattr(failure.value.__cause__, 'phase', None) == (
                    'structured_mode' if fault in ('bad_echo', 'read_bad_echo') else 'structured_shape')
            assert len([key for key in fake.values if key.startswith('v3-stage-result:')]) == (
                1 if calls[-1] == 'read' else 2 if calls[-1] == 'author' else 5 if calls[-1] == 'body' else 6)
            return
        if interrupt_after:
            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert len(calls) == interrupt_after
            args['extraction_journal'] = fresh_journal(journal, fake)
        first = await generate_v3_course_from_corpus(**args, progress_callback=progress)
        replay = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
        assert calls == ['plan', 'read', 'author', 'read', 'author', 'body', 'cards']
        assert events[-6:] == [(index, 7) for index in range(2, 8)]
        assert first.content == replay.content and first.assessment == replay.assessment
        assert len([k for k in fake.values if k.startswith('v3-stage-result:')]) == 7
        plans = [plan for key, plan in fake.plans.items() if key.startswith('v3-stage-result:')]
        assert len(plans) == 7
        groups = [plan['group_id'] for plan in plans]
        reads = [group for group in groups if ':source-read:' in group]
        authors = [group for group in groups if ':author-unit:' in group]
        assert len(reads) == len(authors) == 2
        assert all(':v8:' + packet.fingerprint + ':plan=' + plan_fingerprints[0] + ':unit=' in group
                   for group in reads + authors)
        assert {group.split(':unit=')[1] for group in reads} == {group.split(':unit=')[1] for group in authors}
        lessons = first.diagnostics['practical_course']['lessons']
        assert lessons[0]['content'] == 'New intro.\n\nPreserve body.\n' + image
        assert lessons[0]['questions'][0]['prompt'] == 'Edited question'
        assert lessons[0]['questions'][1]['prompt'].startswith('HIDDEN_QUESTION')
        assert len({q['id'] for lesson in lessons for q in lesson['questions']}) == 6
        review = first.diagnostics['simple_review']
        assert len(review['unit_source_readings']) == 2 and not review['source_questions']
        assert len(review['source_only_reading']['uncertainties']) == 2
    finally:
        client.close()
