import copy
import hashlib
import json

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet, course_response_format
from app.modules.ai.v3.practical_model_view import PracticalModelView


@pytest.fixture
def fixture():
    source = ''.join(f'Source paragraph {index} includes SRC1.\n\n' for index in range(14))
    rev = 'document:' + hashlib.sha256(source.encode()).hexdigest()
    doc = DirectSourceDocument('doc', 'Title', 'file', 'general', rev, (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    assert len(packet.blocks) == 14
    return packet, PracticalModelView(packet)


def test_round_trip_structured_fields_without_changing_literal_content(fixture):
    packet, view = fixture
    ref = packet.blocks[0].block_id
    data = {'title': ref, 'content': 'SRC1 in original source', 'lessons': [{'id': 'lesson',
        'questions': [{'id': 'question', 'source_refs': [ref], 'explanation': ref}]}],
        'narrative_sources': {'lesson': [ref]},
        'findings': [{'scope': 'coverage', 'target_id': ref, 'source_refs': [ref],
                      'problem': ref, 'correction': 'SRC1'}],
        'lesson_updates': {'lesson': {'replacements': [{'old_text': ref, 'new_text': 'SRC1'}]}}}
    original = copy.deepcopy(data)
    encoded = view.encode(data)
    assert encoded['lessons'][0]['questions'][0]['source_refs'] == ['SRC1']
    assert encoded['narrative_sources']['lesson'] == ['SRC1']
    assert encoded['findings'][0]['target_id'] == 'SRC1'
    assert encoded['title'] == ref and encoded['content'] == data['content']
    assert encoded['lesson_updates'] == data['lesson_updates'] and encoded['findings'][0]['problem'] == ref
    assert view.decode(encoded) == original and data == original


def test_schema_shorter_and_input_not_mutated(fixture):
    packet, view = fixture
    fmt = course_response_format(packet)
    original = copy.deepcopy(fmt)
    alias = view.schema(fmt)
    assert fmt == original
    assert len(json.dumps(alias).encode()) < len(json.dumps(fmt).encode())
    refs = alias['json_schema']['schema']['properties']['lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum']
    assert refs == [f'SRC{index}' for index in range(1, 15)]


@pytest.mark.parametrize('value', [{'source_refs': ['SRC999']}, {'narrative_sources': {'l': ['SRC999']}},
                                    {'scope': 'coverage', 'target_id': 'SRC999'}])
def test_unknown_alias_never_fuzzy_resolved(fixture, value):
    _packet, view = fixture
    with pytest.raises(ValueError, match='practical_model_source_ref_invalid'):
        view.decode(value)


def test_unknown_canonical_and_alias_collisions_rejected(fixture):
    packet, view = fixture
    with pytest.raises(ValueError):
        view.encode({'source_refs': ['foreign']})
    with pytest.raises(ValueError):
        view.assert_course_ids_disjoint({'lessons': [{'id': 'SRC1', 'questions': []}]})
    with pytest.raises(ValueError):
        view.assert_course_ids_disjoint({'lessons': [{'id': 'lesson', 'questions': [{'id': 'SRC2'}]}]})
    view.assert_course_ids_disjoint({'lessons': [{'id': 'lesson', 'questions': [{'id': 'question'}]}]})
    with pytest.raises(TypeError):
        view.canonical_to_alias[packet.blocks[0].block_id] = 'SRC999'
