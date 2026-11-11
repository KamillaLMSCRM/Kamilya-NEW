"""Whitespace source custody is lossless, but has no model reference alias."""
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.simple_course_editor_v6 import run_simple_course_editor_v6
from app.modules.ai.v3.simple_semantic_source_plan import build_semantic_slices
from tests.unit.test_v3_simple_owned_transport_v3 import unit_course
from tests.unit.test_v3_simple_source_unit import corpus_for


@pytest.mark.asyncio
async def test_blank_block_cannot_break_editor_projection_after_authors():
    corpus = corpus_for('First action.\n\n\n\nSecond action.\n\n')
    packet = build_practical_source_packet(corpus)
    assert any(not block.text.strip() for block in packet.blocks)
    catalog = build_semantic_slices(packet, corpus)
    selected = [row['id'] for row in catalog if row['text'].strip()]
    calls = []

    async def stage(name, group, messages, fmt, validate):
        payload = json.loads(messages[1]['content'])
        calls.append(name)
        if name == 'review':
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': _digest(catalog),
                'title': 'Work', 'units': [{'id': 'work', 'title': 'Work',
                    'primary_slices': selected, 'supporting_slices': []}], 'non_teaching': []}
        elif name == 'lesson':
            value = unit_course(payload['primary_slices'][0]['source_ref'], 'Useful authored teaching.')
        else:
            assert all(row['source_ref'] is not None for row in payload['source_slices'])
            assert not any(row['text'].strip() == '' and row['source_ref'] is None
                for row in payload['source_slices'])
            lessons = payload.get('teaching_units', payload.get('current_learning_units', {}).get('lessons'))
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1']} for lesson in lessons],
                'source_questions': []}
        validate(value)
        return value

    result = await run_simple_course_editor_v6(packet, corpus, {}, stage)
    assert calls == ['review', 'lesson', 'repair', 'repair']
    assert result.course['lessons'][0]['content'] == 'Useful authored teaching.'
