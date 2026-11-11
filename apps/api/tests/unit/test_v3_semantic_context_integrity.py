import copy
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V6_POLICY
from app.modules.ai.v3.simple_course_editor import SimpleCourseResult
from app.modules.ai.v3.simple_course_editor_v6 import edit_semantic_course, unrepresented_source_images
from app.modules.ai.v3.simple_course_service import simple_course_artifacts
from app.modules.ai.v3.simple_semantic_source_plan import (
    build_semantic_slices,
    semantic_plan_request,
    semantic_unit_request,
)
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course
from tests.unit.test_v3_simple_source_unit import corpus_for


def plan_for(corpus, packet, primary):
    slices = build_semantic_slices(packet, corpus)
    _, fmt = semantic_plan_request(packet, corpus, {})
    remaining = [s['id'] for s in slices if s['text'].strip() and s['id'] not in primary]
    return {'source_fingerprint': packet.fingerprint,
        'slices_fingerprint': fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0],
        'title': 'Course', 'units': [{'id': 'u1', 'title': 'Topic', 'primary_slices': primary,
                                     'supporting_slices': []}],
        'non_teaching': [{'slice_ids': remaining, 'reason': 'Context'}] if remaining else []}


def test_later_table_row_excerpt_retains_exact_parent_and_offsets():
    text = '| Category | Actions |\n| --- | --- |\n| Group Alpha | first action<br>later action<br>final action |\n'
    corpus = corpus_for(text)
    packet = build_practical_source_packet(corpus)
    slices = build_semantic_slices(packet, corpus)
    row = next(s for s in slices if 'later action' in s['text'])
    assert row['structure'] == {'kind': 'table_row', 'row_label': 'Group Alpha',
                                'table_header': '| Category | Actions |\n| --- | --- |\n'}
    block = next(b for b in packet.blocks if b.block_id == row['source_ref'])
    assert corpus.documents[0].source_text[row['start']:row['end']] == row['text']
    assert ''.join(s['text'] for s in slices if s['source_ref'] == block.block_id) == block.text
    messages, _, metadata = semantic_unit_request(packet, corpus, {}, plan_for(corpus, packet, [row['id']]), 'u1')
    selected = json.loads(messages[1]['content'])['primary_slices'][0]
    assert selected['structure'] == row['structure'] and (selected['start'], selected['end']) == (row['start'], row['end'])
    assert metadata['slices'][0] == row


def test_author_parent_context_preserves_unselected_typed_visual_observation():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    slices = build_semantic_slices(packet, corpus)
    primary = next(s for s in slices if 'First topic instructs action.' in s['text'])
    visual = next(s for s in slices if 'Visual OCR sentinel' in s['text'])
    assert primary['source_ref'] == visual['source_ref'] and primary['id'] != visual['id']
    messages, _, _ = semantic_unit_request(packet, corpus, {}, plan_for(corpus, packet, [primary['id']]), 'u1')
    payload = json.loads(messages[1]['content'])
    parent = next(block for block in payload['source_blocks'] if block['id'] == 'SRC1')
    assert 'text' not in parent
    assert any(s['origin'] == 'visual_ocr' and 'Visual OCR sentinel' in s['text'] for s in parent['segments'])
    assert any(s['origin'] == 'visual_description' and 'Visual description sentinel' in s['text'] for s in parent['segments'])
    assert visual['id'] not in [s['id'] for s in payload['primary_slices']]


def test_missing_primary_illustration_is_editorial_attention_not_source_hold():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    doc = corpus.documents[0]
    fidelity = replace(doc.conversion_fidelity, metadata_present=True, metadata_verified=True, fallback_used=False)
    corpus = replace(corpus, documents=(replace(doc, conversion_fidelity=fidelity),))
    packet = build_practical_source_packet(corpus)
    slices = build_semantic_slices(packet, corpus)
    visual = next(s for s in slices if 'Visual OCR sentinel' in s['text'])
    plan = plan_for(corpus, packet, [visual['id']])
    course = unit_course(visual['source_ref'], 'A practical lesson.')
    missing = unrepresented_source_images(packet, corpus, plan, course)
    assert len(missing) == 1 and missing[0]['status'] == 'UNVERIFIED'
    def materialize(value, observations):
        result = SimpleCourseResult(copy.deepcopy(value), value, plan, [], [],
            {'proposals': [], 'unverified_illustrations': observations},
            [{'lesson_id': 'lesson', 'source_refs': [visual['source_ref']]}])
        return simple_course_artifacts(result, corpus, packet, 'd' * 64, review_policy=SIMPLE_COURSE_REVIEW_V6_POLICY)
    artifacts = materialize(course, missing)
    diagnostic = artifacts.diagnostics
    issue = next(row for row in diagnostic['draft_review']['issues'] if row['id'].startswith('simple-illustration-'))
    assert issue['kind'] == 'editorial_review' and issue['blocking'] and issue['evidence']['unverified']
    assert diagnostic['draft_review']['self_review_status'] == 'needs_attention'
    assert not diagnostic['requires_source_review'] and not diagnostic['draft_review']['source_clarification_required']
    with_image = copy.deepcopy(course)
    with_image['lessons'][0]['content'] += '\n![Caption a](' + missing[0]['asset_url'] + ')'
    assert unrepresented_source_images(packet, corpus, plan, with_image) == []
    shown = materialize(with_image, [])
    assert not any(row['id'].startswith('simple-illustration-') for row in shown.diagnostics['draft_review']['issues'])
    assert not shown.diagnostics['automated_review_passed'] and shown.diagnostics['draft_review']['human_review_required']


@pytest.mark.asyncio
@pytest.mark.parametrize('restored', [False, True])
async def test_editors_receive_unrepresented_illustration_inventory(restored):
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    visual = next(s for s in build_semantic_slices(packet, corpus) if 'Visual OCR sentinel' in s['text'])
    plan = plan_for(corpus, packet, [visual['id']])
    course = unit_course(visual['source_ref'], 'Practical lesson.')
    received = []

    async def stage(name, group, messages, fmt, validator):
        payload = json.loads(messages[1]['content'])
        received.append(payload['unrepresented_primary_illustrations'])
        value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                 'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                 'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': ['SRC1']}], 'source_questions': []}
        if restored and ':editor-body:' in group:
            url = payload['unrepresented_primary_illustrations'][0]['asset_url']
            value['body_edits'] = [{'lesson_id': 'lesson', 'before': 'Practical lesson.',
                'after': 'Practical lesson.\n![Caption](' + url + ')'}]
        validator(value)
        return value

    await edit_semantic_course(packet, corpus, {}, course, plan, [{'lesson_id': 'lesson', 'unit_id': 'u1'}], stage)
    assert len(received) == 2
    assert len(received[0]) == 1 and received[0][0]['status'] == 'UNVERIFIED'
    assert received[0][0]['source_refs'] == ['SRC1']
    assert len(received[1]) == (0 if restored else 1)


@pytest.mark.asyncio
async def test_thousand_slices_real_prepare_and_producer_guard():
    corpus = corpus_for(''.join(f'Instruction {i}.\n' for i in range(1000)))
    packet = build_practical_source_packet(corpus)
    messages, fmt = semantic_plan_request(packet, corpus, {})
    slices = [s for s in build_semantic_slices(packet, corpus) if s['text'].strip()]
    assert len(slices) == 1000
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('semantic_context_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=uuid4(), user_id=uuid4(), job_id='synthetic', credential_revision='synthetic')
    try:
        cap = await client.prepare(messages, max_output_tokens=8192, ownership_checkpoint=AsyncMock(return_value=True),
                                   response_format=fmt)
        client.discard(cap)
    finally:
        client.close()
