"""V9 registered producer, real decoders and cold owned journal without network."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_author_transport import PracticalAuthorArtifact
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course
from tests.unit.test_v3_simple_owned_transport_v8 import BetweenStagesError, fresh_journal


def cold_journal(journal, fake):
    cold = fresh_journal(journal, fake)
    cold.expected_review_policy = SIMPLE_COURSE_REVIEW_V9_POLICY
    return cold


def response_for(fmt, messages, packet, image, fault):
    payload = json.loads(messages[1]['content'])
    kind = fmt['json_schema']['name']
    role = ('plan' if kind == 'simple_semantic_source_plan_v1' else
            'author' if kind == 'practical_course' else
            'unit-review' if kind == 'v3_practical_editorial_review_v2' and 'primary_slices' in payload else
            'review' if kind == 'v3_practical_editorial_review_v2' else
            'address' if kind == 'simple_course_block_addresses_v1' else 'joint')
    if role == 'plan':
        def ids(ref):
            return [row['id'] for row in payload['source_slices'] if row['source_ref'] == ref and row['text'].strip()]
        raw = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
            'title': 'Course', 'units': [
                {'id': 'one', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                {'id': 'two', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
            'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Context'}]}
    elif role == 'author':
        assert 'independent_source_reading' not in payload
        ref = payload['primary_slices'][0]['source_ref']
        raw = unit_course(ref, 'Old intro.\n\nPreserve body.' + ('\n' + image if ref == 'SRC1' else ''))
        for question in raw['lessons'][0]['questions']:
            question['prompt'] = 'HIDDEN_QUESTION ' + question['id']
            question['extra_null'] = None
    elif role in {'review', 'unit-review'}:
        assert 'HIDDEN_QUESTION' not in messages[1]['content']
        assert 'independent_source_reading' not in payload and 'unit_reviews' not in payload
        props = fmt['json_schema']['schema']['properties']
        target = payload['lessons'][0]['id']
        refs = props['narrative_sources']['properties'][target]['items']['enum']
        raw = {'source_fingerprint': packet.fingerprint,
            'course_fingerprint': props['course_fingerprint']['enum'][0], 'summary': 'Source compared to bodies.',
            'findings': [{'domain': 'content', 'severity': 'advisory',
                'target': {'kind': 'lesson', 'id': target, 'extra_null': None},
                'problem': 'Synthetic observation', 'basis': 'Source passage', 'correction': 'Preserve good teaching',
                'source_refs': [refs[0]], 'extra_null': None}], 'source_notes': [], 'extra_null': None,
            'narrative_sources': {lesson['id']: [props['narrative_sources']['properties'][lesson['id']]['items']['enum'][0]]
                for lesson in payload['lessons']}}
        if (fault == 'review_null' and role == 'review') or (fault == 'unit_null' and role == 'unit-review'):
            raw['summary'] = None
        elif fault == 'target_null' and role == 'unit-review':
            raw['findings'][0]['target']['id'] = None
        elif fault == 'review_nonnull' and role == 'unit-review':
            raw['findings'][0]['target']['extra_null'] = 'not permitted'
        elif fault in {'finding_resolved', 'finding_unresolved'} and role == 'review':
            raw['findings'][0]['severity'] = 'material'
    elif role == 'address':
        assert set(payload) == {'source_fingerprint', 'draft_fingerprint', 'proposal_fingerprint', 'body_blocks', 'edits'}
        raw = {key: payload[key] for key in ('source_fingerprint', 'draft_fingerprint', 'proposal_fingerprint')}
        raw['assignments'] = [{'edit_id': row['edit_id'], 'block_id': payload['body_blocks'][index]['id'],
                               'extra_null': None} for index, row in enumerate(payload['edits'])]
        raw['extra_null'] = None
        if fault == 'address_unresolved':
            raw['assignments'][0]['block_id'] = 'UNRESOLVED'
        elif fault == 'address_stale':
            raw['proposal_fingerprint'] = '0' * 64
        elif fault == 'address_null':
            raw['assignments'] = None
    else:
        assert 'independent_source_reading' not in payload
        assert len(payload['unit_reviews']) == 2
        assert payload['independent_content_review']['summary'] == 'Source compared to bodies.'
        lessons = payload['original_course']['lessons']
        question = copy.deepcopy(lessons[0]['questions'][0])
        question['prompt'] = 'Edited question'
        blocks = lessons[0]['body_blocks']
        raw = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
            'body_edits': [{'block_id': blocks[0]['id'], 'after': 'New intro.'}],
            'title_edits': [], 'question_edits': [question],
            'added_lessons': [], 'lesson_sources': [
                {'lesson_id': lesson['id'], 'source_refs': ['SRC1' if index == 0 else 'SRC2'], 'extra_null': None}
                for index, lesson in enumerate(lessons)], 'source_questions': [], 'extra_null': None}
        if fault == 'joint_null':
            raw['body_edits'] = None
        elif fault == 'nonnull_extra':
            raw['extra_null'] = 'not permitted'
        elif fault == 'foreign_block':
            raw['body_edits'][0]['block_id'] = 'BODY999'
        elif fault == 'drop_image':
            block = next(row for row in blocks if image in row['text'])
            raw['body_edits'] = [{'block_id': block['id'], 'after': 'Preserve body.'}]
        elif fault in {'address_ok', 'address_unresolved', 'address_stale', 'address_null'}:
            raw['body_edits'].append({'block_id': blocks[0]['id'], 'after': blocks[1]['text']})
        if 'finding_dispositions' in fmt['json_schema']['schema']['properties']:
            raw['finding_dispositions'] = []
            if fault == 'finding_resolved':
                raw['finding_dispositions'] = [{'finding_id': payload['material_findings'][0]['id'],
                    'status': 'CORRECTED', 'reason': 'Corrected the requested introduction.', 'source_refs': ['SRC1'],
                    'source_quote': packet.blocks[0].text, 'target': {'kind': 'lesson_content', 'id': lessons[0]['id'],
                        'choice_index': 0, 'extra_null': None}, 'final_quote': 'New intro.', 'extra_null': None}]
    return role, raw


@pytest.mark.asyncio
@pytest.mark.parametrize(('transport', 'interrupt_after', 'fault'), [
    ('managed', 0, None), ('managed', 5, None), ('managed', 6, None),
    ('cloud', 0, None), ('cloud', 5, None), ('cloud', 6, None),
    ('managed', 0, 'joint_null'), ('cloud', 0, 'joint_null'),
    ('managed', 0, 'nonnull_extra'), ('cloud', 0, 'nonnull_extra'),
    ('managed', 0, 'bad_echo'), ('managed', 0, 'review_null'),
    ('cloud', 0, 'review_null'), ('managed', 0, 'unit_null'), ('cloud', 0, 'unit_null'),
    ('managed', 0, 'target_null'), ('cloud', 0, 'review_nonnull'), ('managed', 0, 'foreign_block'),
    ('managed', 0, 'drop_image'), ('cloud', 0, 'drop_image'),
    ('managed', 0, 'address_ok'), ('cloud', 0, 'address_ok'),
    ('managed', 7, 'address_ok'), ('cloud', 8, 'address_ok'),
    ('managed', 0, 'address_unresolved'), ('cloud', 0, 'address_unresolved'),
    ('managed', 0, 'address_stale'), ('cloud', 0, 'address_null'),
    ('managed', 0, 'finding_resolved'), ('cloud', 6, 'finding_resolved'),
    ('managed', 0, 'finding_unresolved'), ('cloud', 0, 'finding_unresolved')])
async def test_v9_real_decoders_and_owned_cold_replay(monkeypatch, transport, interrupt_after, fault):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V9_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    image = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'
    client, calls = client_for(journal), []
    spec = importlib.util.spec_from_file_location('v9_owned_runner', Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    async def invoke(capability, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint()
        request = json.loads(client._prepared[capability])
        fmt = request['response_format']
        assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
        role, raw = response_for(fmt, request['messages'], packet, image, fault)
        calls.append(role)
        envelope = {'model': client.model, 'structured_output_policy': 'typed-json-object-v1',
            'response_format_sha256': '0' * 64 if role == 'joint' and fault == 'bad_echo' else response_contract_hash(fmt),
            'choices': [{'message': {'content': json.dumps(raw)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 25}}
        result, _ = client._decode_response(json.dumps(envelope).encode(), client._prepared[capability])
        if role in {'author', 'unit-review', 'review', 'joint', 'address'}:
            assert isinstance(result.content, PracticalAuthorArtifact)
        return result

    class Cloud:
        async def ainvoke(self, messages, *, response_format):
            assert runner._checked_structured_format(response_format) == response_format['json_schema']['schema']
            role, raw = response_for(response_format, messages, packet, image, fault)
            calls.append(role)
            return SimpleNamespace(content=json.dumps(raw), finish_reason='stop')

    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = {'corpus': corpus, 'intent': CourseIntent(), 'generation_client': Cloud() if transport == 'cloud' else None,
        'extraction_journal': journal, 'direct_client': client if transport == 'managed' else None,
        'revision_policy': POLICY, 'review_policy': SIMPLE_COURSE_REVIEW_V9_POLICY, 'route_fingerprint': 'd' * 64}
    try:
        known_result = fault in {'drop_image', 'address_ok', 'address_unresolved', 'finding_resolved', 'finding_unresolved'}
        if fault and not known_result:
            with pytest.raises(ExtractionOutcomeUnknownError):
                await generate_v3_course_from_corpus(**args)
            assert calls[-1] == ('address' if fault in {'address_stale', 'address_null'} else 'review' if fault == 'review_null' else 'unit-review' if fault in {'unit_null', 'target_null', 'review_nonnull'} else 'joint')
            assert len([key for key in fake.values if key.startswith('v3-stage-result:')]) == (7 if fault in {'address_stale', 'address_null'} else 5 if fault == 'review_null' else 2 if fault in {'unit_null', 'target_null', 'review_nonnull'} else 6)
            return
        if interrupt_after:
            async def progress(_stage, completed, _total, _provider, _attempt):
                if completed == interrupt_after:
                    raise BetweenStagesError()
            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert len(calls) == interrupt_after
            args['extraction_journal'] = cold_journal(journal, fake)
        first = await generate_v3_course_from_corpus(**args)
        replay = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': cold_journal(journal, fake)})
        repaired = fault in {'address_ok', 'address_unresolved'}
        assert calls == ['plan', 'author', 'unit-review', 'author', 'unit-review', 'review', 'joint'] + (['address'] if repaired else [])
        assert first.content == replay.content and first.assessment == replay.assessment
        lessons = first.diagnostics['practical_course']['lessons']
        unapplied = fault in {'drop_image', 'address_unresolved'}
        assert lessons[0]['content'] == ('Old intro.' if unapplied else 'New intro.') + '\n\nPreserve body.\n' + image
        assert lessons[0]['questions'][0]['prompt'].startswith('HIDDEN_QUESTION') if unapplied else lessons[0]['questions'][0]['prompt'] == 'Edited question'
        assert lessons[0]['questions'][1]['prompt'].startswith('HIDDEN_QUESTION')
        records = [value for key, value in fake.values.items() if key.startswith('v3-stage-result:')]
        assert len(records) == 7 + repaired and sum('author_custody' in row for row in records) == 6 + repaired
        review = first.diagnostics['simple_review']
        assert review['editor_delta_receipts']['cards']['no_extra_model_call'] is True
        assert not review['revision_receipt']['unverified_source_questions']
        assert review['editor_delta_receipts']['body']['application_status'] == ('unapplied' if unapplied else 'applied')
        assert bool(review['revision_receipt'].get('unapplied_review_findings')) == (unapplied or fault == 'finding_unresolved')
        if fault in {'finding_resolved', 'finding_unresolved'}:
            row = review['revision_receipt']['review_finding_dispositions'][0]
            assert row['model_resolved'] == (fault == 'finding_resolved')
            assert row['semantic_approval'] is False
            issue = next(issue for issue in first.diagnostics['draft_review']['issues']
                         if issue['message'].startswith('Synthetic observation'))
            assert issue['blocking'] == (fault == 'finding_unresolved')
        assert first.diagnostics['requires_source_review'] == any(
            doc.conversion_fidelity.needs_review or doc.review_only_source_unresolved
            or doc.review_only_source_context for doc in corpus.documents)
    finally:
        client.close()
