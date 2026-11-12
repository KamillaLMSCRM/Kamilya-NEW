"""V7 assembled owned stages with real client preparation and envelope decoding."""
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
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V7_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


def reading_response(packet):
    def rule(ref, quote, marker):
        return {'source_refs': [ref], 'source_quote': quote, 'actor': 'Employee', 'action': marker,
                'object': 'action', 'conditions': [], 'modality': 'must', 'alternatives': [], 'limits': []}
    return {'source_fingerprint': packet.fingerprint, 'sections': [{'section': 'Rules', 'rules': [
        rule('SRC1', 'First topic instructs action.', 'FIRST_RULE_SENTINEL'),
        rule('SRC2', 'Second topic instructs action.', 'SECOND_RULE_SENTINEL'),
        rule('SRC1', 'not a literal quote', 'UNVERIFIED_RULE_SENTINEL')]}],
        'uncertainties': [{'source_refs': ['SRC1'], 'source_quote': 'First topic instructs action.',
                           'question': 'READING_UNCERTAINTY_SENTINEL'}]}


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
    cold.expected_review_policy = SIMPLE_COURSE_REVIEW_V7_POLICY
    return cold


@pytest.mark.asyncio
@pytest.mark.parametrize(('interrupt_after', 'fault'), [(0, None), (2, None), (3, None), (4, None), (5, None),
    (0, 'required_null'), (0, 'nonnull_extra'), (0, 'bad_echo'),
    (0, 'body_question'), (0, 'cards_body'), (0, 'cards_title'), (0, 'cards_add'),
    (0, 'read_required_null'), (0, 'read_nonnull_extra'), (0, 'read_bad_echo'), (0, 'read_foreign_ref'),
    (0, 'foreign_ref'), (0, 'drop_image')])
async def test_v7_real_decode_owned_path_and_cold_replay(monkeypatch, interrupt_after, fault):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V7_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    view = PracticalModelView(packet)
    client = client_for(journal)
    calls, artifacts, events = [], [], []
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('v7_owned_runner', path)
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
                'author' if kind == 'practical_course' else
                'body' if 'teaching_units' in payload else 'cards')
        calls.append(role)
        if role == 'plan':
            slices = payload['source_slices']
            assert any(o['origin'] == 'visual_ocr' for s in slices for o in s['origins'])
            def ids(ref):
                return [s['id'] for s in slices if s['source_ref'] == ref and s['text'].strip()]
            raw = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                   'title': 'Course', 'units': [
                       {'id': 'first', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                       {'id': 'second', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
                   'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Administrative'}]}
        elif role == 'read':
            assert all(s not in request['messages'][1]['content'] for s in
                       ('HIDDEN_CARD_SENTINEL', 'HIDDEN_EXPLANATION_SENTINEL', 'correct_index', 'teaching_units', 'current_learning_units'))
            assert payload['source_blocks'] and all('segments' in block for block in payload['source_blocks'])
            raw = reading_response(packet)
            if fault == 'read_required_null':
                raw['sections'] = None
            elif fault == 'read_nonnull_extra':
                raw['extra'] = 'unexpected'
            elif fault == 'read_foreign_ref':
                raw['sections'][0]['rules'][0]['source_refs'] = ['SRC999']
        elif role == 'author':
            primary = payload['primary_slices']
            ref = primary[0]['source_ref']
            assert all(s['source_ref'] == ref for s in primary)
            assert any(s['text'] for s in primary)
            reading = payload['independent_source_reading']
            encoded = json.dumps(reading)
            assert ('FIRST_RULE_SENTINEL' in encoded) == (ref == 'SRC1')
            assert ('SECOND_RULE_SENTINEL' in encoded) == (ref == 'SRC2')
            assert 'uncertainties' not in reading
            rules = [rule for section in reading['sections'] for rule in section['rules']]
            assert all(rule['custody_valid'] is (rule['action'] != 'UNVERIFIED_RULE_SENTINEL') for rule in rules)
            lesson = unit_course(ref, 'Old intro.\n\nPreserve body.' + ('\n' + image if ref == 'SRC1' else ''))
            for question in lesson['lessons'][0]['questions']:
                question['prompt'] = 'HIDDEN_CARD_SENTINEL ' + question['id']
                question['explanation'] = 'HIDDEN_EXPLANATION_SENTINEL'
            if fault == 'foreign_ref':
                lesson['lessons'][0]['questions'][0]['source_refs'] = ['SRC999']
            raw = {**lesson, 'extra': None}
        else:
            assert kind == 'simple_course_delta_editor_v1'
            assert 'FIRST_RULE_SENTINEL' in json.dumps(payload['independent_source_reading'])
            assert 'SECOND_RULE_SENTINEL' in json.dumps(payload['independent_source_reading'])
            assert 'READING_UNCERTAINTY_SENTINEL' in json.dumps(payload['independent_source_reading'])
            assert payload['source_blocks'] and 'source_slices' not in payload
            if role == 'body':
                assert all(s not in request['messages'][1]['content'] for s in
                           ('HIDDEN_CARD_SENTINEL', 'HIDDEN_EXPLANATION_SENTINEL', 'correct_index', 'current_learning_units'))
                lessons = payload['teaching_units']
                assert all(set(item) == {'id', 'title', 'content'} for item in lessons)
            else:
                lessons = payload['current_learning_units']['lessons']
                assert payload['draft_fingerprint'] == _digest(view.decode(payload['current_learning_units']))
                assert lessons[0]['content'].startswith('New intro.')
            raw = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                   'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                   'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1' if i == 0 else 'SRC2']}
                                      for i, lesson in enumerate(lessons)],
                   'source_questions': [{'question': 'Shared uncertainty', 'source_refs': ['SRC1']},
                                        {'question': role + ' uncertainty', 'source_refs': ['SRC2']}], 'extra': None}
            if role == 'body':
                raw['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': 'Old intro.', 'after': 'New intro.'}]
                if fault == 'drop_image':
                    raw['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': image, 'after': ''}]
                if fault == 'body_question':
                    q = unit_course('SRC1', 'x')['lessons'][0]['questions'][0]
                    raw['question_edits'] = [{'lesson_id': lessons[0]['id'], 'question': q}]
            else:
                question = lessons[0]['questions'][0]
                question['prompt'] = 'Edited question'
                raw['question_edits'] = [{'lesson_id': lessons[0]['id'], 'question': question}]
                if fault == 'cards_body':
                    raw['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': 'New intro.', 'after': 'bad'}]
                elif fault == 'cards_title':
                    raw['title_edits'] = [{'lesson_id': lessons[0]['id'], 'title': 'bad'}]
                elif fault == 'cards_add':
                    raw['added_lessons'] = [unit_course('SRC1', 'extra')['lessons'][0]]
        if role == 'author' and fault == 'required_null':
            raw['lessons'] = None
        if role == 'author' and fault == 'nonnull_extra':
            raw['extra'] = 'foreign'
        envelope = {'model': client.model, 'structured_output_policy': 'typed-json-object-v1',
            'response_format_sha256': '0' * 64 if (role == 'author' and fault == 'bad_echo') or (role == 'read' and fault == 'read_bad_echo') else response_contract_hash(fmt),
            'choices': [{'message': {'content': json.dumps(raw)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 25}}
        result, _ = client._decode_response(json.dumps(envelope).encode(), client._prepared[capability])
        if role not in {'plan', 'read'}:
            assert isinstance(result.content, PracticalAuthorArtifact)
            assert '/extra' in result.content.receipt.removed_paths
            artifacts.append(result.content)
        return result

    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=None, extraction_journal=journal,
                direct_client=client, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_V7_POLICY,
                route_fingerprint='d' * 64)

    async def progress(stage, completed, total, provider, attempt):
        events.append((completed, total))
        if interrupt_after and completed == interrupt_after and len(events) == interrupt_after:
            raise BetweenStagesError()

    try:
        if fault:
            with pytest.raises(ExtractionOutcomeUnknownError) as failure:
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert calls[-1] == ('read' if fault.startswith('read_') else
                                  'author' if fault in ('required_null', 'nonnull_extra', 'bad_echo', 'foreign_ref') else
                                  'body' if fault in ('body_question', 'drop_image') else 'cards')
            if fault == 'body_question':
                assert str(failure.value.__cause__) == 'simple_v6_body_question_edit_forbidden'
            elif fault == 'drop_image':
                assert str(failure.value.__cause__) == 'simple_v6_editor_media_changed'
            elif fault == 'foreign_ref':
                assert getattr(failure.value.__cause__, 'phase', None) == 'structured_shape'
            elif fault.startswith('cards_'):
                assert str(failure.value.__cause__) == 'simple_v6_cards_body_edit_forbidden'
            else:
                assert getattr(failure.value.__cause__, 'phase', None) == (
                    'structured_mode' if fault in ('bad_echo', 'read_bad_echo') else 'structured_shape')
            completed = len([key for key in fake.values if key.startswith('v3-stage-result:')])
            assert completed == (1 if calls[-1] == 'read' else 2 if calls[-1] == 'author' else 4 if calls[-1] == 'body' else 5)
            return
        if interrupt_after:
            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert len(calls) == interrupt_after
            args['extraction_journal'] = fresh_journal(journal, fake)
        first = await generate_v3_course_from_corpus(**args, progress_callback=progress)
        replay = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': fresh_journal(journal, fake)})
        assert calls == ['plan', 'read', 'author', 'author', 'body', 'cards']
        assert first.content == replay.content and first.assessment == replay.assessment
        assert len([key for key in fake.values if key.startswith('v3-stage-result:')]) == 6
        lessons = first.diagnostics['practical_course']['lessons']
        assert lessons[0]['content'] == 'New intro.\n\nPreserve body.\n' + image
        assert lessons[0]['questions'][0]['prompt'] == 'Edited question'
        assert len({q['id'] for lesson in lessons for q in lesson['questions']}) == 6
        review = first.diagnostics['simple_review']
        assert {row['question'] for row in review['source_questions']} == {'Shared uncertainty', 'body uncertainty', 'cards uncertainty'}
        assert review['editor_delta_receipts']['cards']['draft_fingerprint'] == review['editor_delta_receipts']['body']['result_fingerprint']
        assert all(row['slices'] for row in review['unit_editor_records'])
        assert review['source_only_reading']['uncertainties'][0]['question'] == 'READING_UNCERTAINTY_SENTINEL'
        assert 'READING_UNCERTAINTY_SENTINEL' not in {row['question'] for row in review['source_questions']}
    finally:
        client.close()

