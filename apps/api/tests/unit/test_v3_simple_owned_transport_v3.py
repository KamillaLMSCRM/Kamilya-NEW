"""Assembled V3 owned stages with synthetic provider and in-memory journal."""
import copy
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.practical_author_transport import normalize_practical_author
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY, SIMPLE_COURSE_REVIEW_V3_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from app.modules.ai.v3.simple_course_editor_v3 import compile_unit_editor, course_media_safe
from app.modules.ai.v3.simple_source_unit_plan import _plan_format
from app.modules.ai.v3.stage_checkpoint import _digest
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_service import corpus_fixture


def synthetic_corpus(tenant_id, *, mixed_origin=False):
    if mixed_origin:
        from tests.unit.test_v3_simple_source_origin import asset, figure, make_corpus, source_block

        image = asset('a', text='Visual OCR sentinel', description='Visual description sentinel')
        blocks = [source_block(1, 'First topic instructs action.\n' + figure(image), asset_ids=[image.id]),
                  source_block(2, 'Second topic instructs action.'), source_block(3, 'Administrative note.')]
        return replace(make_corpus(blocks, [image]), tenant_id=tenant_id)
    corpus = corpus_fixture()
    doc = corpus.documents[0]
    image = '![Source illustration](source-asset:asset-' + 'a' * 64 + ')'
    text = 'First topic instructs action.\n' + image + '\n\nSecond topic instructs action.\n\nAdministrative note.'
    working, spans = render_text(text, [])
    approval = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approved', text, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    return replace(corpus, tenant_id=tenant_id,
                   documents=(replace(doc, source_text=working, editorial_document=approval),))


def cold_journal(journal, fake):
    cold = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id, fake.sessions,
                               verify_source=journal.verify_source)
    cold.repository = fake
    cold._lock_delivery = fake._lock_delivery
    cold._owned_key = fake._owned_key
    cold.read_owned_value_in_session = fake.read_owned_value_in_session
    cold.review_policy_bound = True
    cold.expected_review_policy = SIMPLE_COURSE_REVIEW_V3_POLICY
    return cold


def unit_course(alias, content):
    return {'title': 'Unit', 'lessons': [{'id': 'lesson', 'title': 'Lesson', 'content': content,
        'questions': [{'id': f'q{i}', 'prompt': f'Question {i}', 'choices': ['A', 'B', 'C'],
                       'correct_index': 0, 'explanation': 'Reason', 'source_refs': [alias]} for i in range(3)]}]}


class BetweenStagesError(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(('interrupted', 'fault', 'combined', 'mixed_origin'), [
    (False, None, False, False), (True, None, False, False), (False, None, True, False),
    (False, 'foreign_ref', False, False), (False, 'empty_course', False, False),
    (False, 'drop_lesson', False, False), (False, 'replace_question', False, False),
    (False, None, False, True),
])
async def test_v3_owned_assembly_and_cold_replay(monkeypatch, interrupted, fault, combined, mixed_origin):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V3_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=mixed_origin)
    original_corpus = copy.deepcopy(corpus)
    packet = build_practical_source_packet(corpus)
    client = client_for(journal)
    invoked = []
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('v3_owned_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    async def invoke(capability, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        request = json.loads(client._prepared[capability])
        fmt = request['response_format']
        assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
        payload = json.loads(request['messages'][1]['content'])
        name = fmt['json_schema']['name']
        invoked.append((name, payload))
        rows = payload['source_blocks']
        assert [row['id'] for row in rows] == ['SRC1', 'SRC2', 'SRC3']
        assert all('text' not in row for row in rows)
        assert [''.join(segment['text'] for segment in row['segments']) for row in rows] == [
            block.text for block in packet.blocks]
        assert 'private-storage-path' not in json.dumps(payload)
        if mixed_origin:
            segments = [segment for row in rows for segment in row['segments']]
            assert any(segment['origin'] == 'document_body' and 'First topic' in segment['text']
                       for segment in segments)
            assert any(segment['origin'] == 'visual_ocr' and 'Visual OCR sentinel' in segment['text']
                       and segment['asset_id'] == 'asset-' + 'a' * 64 for segment in segments)
            assert any(segment['origin'] == 'visual_description' and 'Visual description sentinel' in segment['text']
                       and segment['asset_id'] == 'asset-' + 'a' * 64 for segment in segments)
        if name == 'simple_source_unit_plan_v2':
            from app.modules.ai.v3.simple_source_unit_plan import encode_source_unit_plan

            canonical = {'source_fingerprint': payload['source_fingerprint'], 'title': 'Course',
                'units': [{'id': 'first', 'title': 'First', 'primary_refs': [packet.blocks[0].block_id], 'supporting_refs': []},
                          {'id': 'second', 'title': 'Second', 'primary_refs': [packet.blocks[1].block_id],
                           'supporting_refs': [packet.blocks[0].block_id]}],
                'non_teaching': [{'source_refs': [packet.blocks[2].block_id], 'reason': 'Administrative'}]}
            result = encode_source_unit_plan(canonical, PracticalModelView(packet))
        elif name == 'practical_course':
            assert next(iter(payload)) == 'source_blocks'
            assert [block['id'] for block in payload['source_blocks']] == ['SRC1', 'SRC2', 'SRC3']
            assert sum('First topic instructs action.' in ''.join(segment['text'] for segment in block['segments']) for block in payload['source_blocks']) == 1
            assert len(payload['units']) == 2 and payload['units'][1]['supporting_refs'] == ['SRC1']
            lessons = []
            for unit in payload['units']:
                alias = unit['primary_refs'][0]
                image = '![Source illustration](source-asset:asset-' + 'a' * 64 + ')'
                lesson = unit_course(alias, 'Authored ' + alias + '\n' + image)['lessons'][0]
                lesson['id'] = unit['lesson_id']
                for question in lesson['questions']:
                    question['id'] = unit['lesson_id'] + '-' + question['id']
                lessons.append(lesson)
            # A common rule belonging to another planned unit remains accessible.
            lessons[0]['questions'][0]['source_refs'] = ['SRC2']
            if fault == 'foreign_ref':
                lessons[0]['questions'][0]['source_refs'] = ['SRC999']
            elif fault == 'empty_course':
                lessons.clear()
            if combined:
                lessons = lessons[:1]
            raw = {'title': 'Course', 'lessons': lessons}
            raw['extra'] = None
            result = normalize_practical_author(json.dumps(raw), fmt)
        else:
            assert name == 'simple_course_editor_v1'
            assert next(iter(payload)) == 'source_blocks'
            assert list(payload).index('source_blocks') < list(payload).index('current_learning_units')
            assert [block['id'] for block in payload['source_blocks']] == ['SRC1', 'SRC2', 'SRC3']
            assert sum('First topic instructs action.' in ''.join(segment['text'] for segment in block['segments']) for block in payload['source_blocks']) == 1
            edited = copy.deepcopy(payload['current_learning_units'])
            if combined:
                added = unit_course('SRC2', 'New lesson from approved source')['lessons'][0]
                added['id'] = 'editor-added-lesson'
                for question in added['questions']:
                    question['id'] = 'editor-added-' + question['id']
                edited['lessons'].append(added)
            for lesson, unit in zip(edited['lessons'], payload['units'], strict=True):
                lesson['content'] = 'Edited ' + unit['primary_refs'][0]
            edited['lessons'][1]['content'] += '\n![Moved caption](source-asset:asset-' + 'a' * 64 + ')'
            if fault == 'drop_lesson':
                edited['lessons'].pop(0)
            elif fault == 'replace_question':
                edited['lessons'][0]['questions'][0]['id'] = 'replacement-question'
            raw = {'source_fingerprint': payload['source_fingerprint'], 'draft_fingerprint': payload['draft_fingerprint'],
                   'course': edited, 'lesson_sources': [{'lesson_id': lesson['id'],
                       'source_refs': ['SRC2']} for lesson in edited['lessons']],
                   'source_questions': [], 'extra': None}
            result = normalize_practical_author(json.dumps(raw), fmt)
        return SimpleNamespace(content=result, model='gpt-6-luna',
            usage=SimpleNamespace(input_tokens=100, output_tokens=25, cached_input_tokens=0, reasoning_tokens=5))

    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=None, extraction_journal=journal,
        direct_client=client, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_V3_POLICY,
        route_fingerprint='d' * 64)

    progress_events = []
    async def progress(stage, completed, total, provider, attempt):
        progress_events.append((completed, total))
        if interrupted and completed == 2 and len(progress_events) == 2:
            raise BetweenStagesError()

    try:
        if fault:
            expected = ('practical_author_transport_invalid' if fault in {'foreign_ref', 'empty_course'}
                        else 'simple_unit_editor_identity_changed')
            with pytest.raises(ExtractionOutcomeUnknownError, match='v3_pending_provider_outcome_unknown') as failure:
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert isinstance(failure.value.__cause__, ValueError)
            assert str(failure.value.__cause__) == expected
            assert [item[0] for item in invoked] == (['simple_source_unit_plan_v2', 'practical_course']
                if fault in {'foreign_ref', 'empty_course'} else
                ['simple_source_unit_plan_v2', 'practical_course', 'simple_course_editor_v1'])
            return
        if interrupted:
            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert len(invoked) == 2
            args['extraction_journal'] = cold_journal(journal, fake)
        first = await generate_v3_course_from_corpus(**args, progress_callback=progress)
        second = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': cold_journal(journal, fake)})
        assert [item[0] for item in invoked] == ['simple_source_unit_plan_v2', 'practical_course',
            'simple_course_editor_v1']
        assert first.content == second.content and first.assessment == second.assessment
        assert progress_events[-3:] == [(i, 3) for i in range(1, 4)]
        assert len([key for key in fake.values if key.startswith('v3-stage-result:')]) == 3
        diagnostics = first.diagnostics
        lessons = diagnostics['practical_course']['lessons']
        authored = invoked[2][1]['current_learning_units']
        assert len(authored['lessons']) == (1 if combined else 2)
        assert PracticalModelView(packet).encode(lessons[0]['questions']) == authored['lessons'][0]['questions']
        assert all(3 <= len(lesson['questions']) <= 4 for lesson in lessons)
        second_id = 'editor-added-lesson' if combined else 'unit-2-lesson'
        assert [lesson['id'] for lesson in lessons] == ['unit-1-lesson', second_id]
        assert [[q['id'] for q in lesson['questions']] for lesson in lessons] == [
            ['unit-1-lesson-q0', 'unit-1-lesson-q1', 'unit-1-lesson-q2'],
            ([f'editor-added-q{i}' for i in range(3)] if combined else
             ['unit-2-lesson-q0', 'unit-2-lesson-q1', 'unit-2-lesson-q2'])]
        assert all(lesson['content'].startswith('Edited ') for lesson in lessons)
        assert 'source-asset:' not in lessons[0]['content']
        assert '![Moved caption](source-asset:asset-' + 'a' * 64 + ')' in lessons[1]['content']
        assert lessons[0]['questions'][0]['source_refs'] == [packet.blocks[1].block_id]
        assert diagnostics['simple_lesson_sources'] == [
            {'lesson_id': 'unit-1-lesson', 'source_refs': [packet.blocks[1].block_id]},
            {'lesson_id': second_id, 'source_refs': [packet.blocks[1].block_id]}]
        assert diagnostics['simple_changed_paths'] == (['/lessons'] if combined else
            ['/lessons/0/content', '/lessons/1/content'])
        assert diagnostics['requires_editorial_review'] and not diagnostics['automated_review_passed']
        refs = [lesson.source_references[0] for lesson in first.content.modules[0].lessons]
        assert all(ref['source_revision'] == corpus.documents[0].source_revision for ref in refs)
        assert all((ref['start'], ref['end']) == (packet.blocks[1].start, packet.blocks[1].end) for ref in refs)
        assert corpus == original_corpus
    finally:
        client.close()


def test_unit_editor_preserves_existing_image_and_rejects_drop_or_foreign_addition():
    corpus = synthetic_corpus('tenant')
    packet = build_practical_source_packet(corpus)
    ref = packet.blocks[0].block_id
    image = '![diagram](source-asset:asset-' + 'a' * 64 + ')'
    original = unit_course(ref, 'Original ' + image)
    value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
             'course': copy.deepcopy(original), 'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': [ref]}],
             'source_questions': []}
    value['course']['lessons'][0]['content'] = 'Improved ' + image
    assert compile_unit_editor(value, packet, original, (ref,), ())['course']['lessons'][0]['content'] == 'Improved ' + image
    value['course']['lessons'][0]['content'] = 'Image dropped'
    with pytest.raises(ValueError, match='simple_unit_editor_media_changed'):
        compile_unit_editor(value, packet, original, (ref,), ())
    value['course']['lessons'][0]['content'] = 'Improved ' + image + ' ![foreign](source-asset:asset-' + 'b' * 64 + ')'
    with pytest.raises(ValueError, match='simple_unit_editor_media_changed'):
        compile_unit_editor(value, packet, original, (ref,), ())


def test_global_media_relocation_caption_update_and_consolidation_preserve_owned_asset():
    corpus = synthetic_corpus('tenant')
    doc = corpus.documents[0]
    asset = 'source-asset:asset-' + 'a' * 64
    image = f'![Original]({asset})'
    source = doc.source_text + '\n\n' + image
    working, spans = render_text(source, [])
    approval = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approved', source, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approval),))
    snapshot = copy.deepcopy(corpus)
    packet = build_practical_source_packet(corpus)
    before = {'lessons': [{'content': image}, {'content': image}]}
    moved = {'lessons': [{'content': 'Moved away'}, {'content': f'![New caption]({asset})'}]}
    assert course_media_safe(before, moved, packet)
    assert not course_media_safe(before, {'lessons': [{'content': ''}, {'content': ''}]}, packet)
    foreign = 'source-asset:asset-' + 'b' * 64
    assert not course_media_safe(before, {'lessons': [{'content': f'![New]({foreign})'}, moved['lessons'][1]]}, packet)
    assert corpus == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['policy', 'group', 'source', 'source_mismatch', 'format', 'owner', 'request'])
async def test_v3_owned_plan_rejects_forgery_before_provider(monkeypatch, fault):
    _, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V3_POLICY
    client = client_for(journal)
    messages = [{'role': 'user', 'content': 'approved source'}]
    fmt = _plan_format(['SRC1'], 'a' * 64)
    plan = {'schema': 'v3-stage-checkpoint-v1', 'tenant_id': journal.tenant_id, 'job_id': journal.job_id,
        'stage': 'review', 'group_id': 'practical:simple:plan:v3:' + 'a' * 64 + ':output=32768',
        'source_sha256': 'c' * 64, 'route_fingerprint': 'd' * 64, 'request_sha256': _digest([messages, fmt])}
    if fault == 'policy':
        journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V2_POLICY
    elif fault == 'group':
        plan['group_id'] = plan['group_id'].replace('plan:v3', 'plan:v2')
    elif fault == 'source':
        plan['source_sha256'] = 'invalid'
    elif fault == 'source_mismatch':
        plan['group_id'] = 'practical:simple:plan:v3:' + 'b' * 64 + ':output=32768'
    elif fault == 'format':
        fmt = None
    elif fault == 'owner':
        plan['job_id'] = 'foreign'
    else:
        plan['request_sha256'] = 'e' * 64
    inspection = AsyncMock()
    monkeypatch.setattr('app.modules.ai.v3.direct_luna_owned_stage.inspect_owned_stage', inspection)
    try:
        with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
            await run_direct_owned_stage(journal=journal, client=client, plan=plan, result_key='result', claim_key='claim',
                validate_value=lambda value: value, validate_response=lambda value: value, messages=messages,
                max_output_tokens=32768, response_format=fmt)
        inspection.assert_not_awaited()
    finally:
        client.close()


def test_v1_v2_current_source_payload_remains_literal_with_preparation():
    from app.modules.ai.v3.simple_course_editor import _source_context
    from app.modules.ai.v3.simple_course_editor_v2 import _current_context

    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    _, v1 = _source_context(packet, corpus, {})
    _, v2 = _current_context(packet, corpus, {})
    expected = [{'id': f'SRC{i}', 'document_id': block.doc_id, 'text': block.text}
                for i, block in enumerate(packet.blocks, 1)]
    assert v1['source_blocks'] == expected == v2['source_blocks']
    assert 'private-storage-path' not in json.dumps(v1)
    assert 'private-storage-path' not in json.dumps(v2)
