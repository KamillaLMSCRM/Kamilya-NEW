import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_option_predicates import option_predicates_format
from app.modules.ai.v3.simple_blind_question_review import blind_question_request, compile_blind_question_review
from tests.unit.test_v3_simple_course_editor import course, fixture


def setup_review():
    corpus, packet = fixture()
    original = course(ref=packet.blocks[0].block_id, content='PROSE_PRIVATE_SENTINEL')
    original['lessons'][0]['title'] = 'VISIBLE_QUIZ_TITLE'
    original['lessons'][0]['questions'][0]['explanation'] = 'EXPLANATION_PRIVATE_SENTINEL'
    original['lessons'][0]['questions'][0]['correct_index'] = 1
    view = PracticalModelView(packet)
    before = copy.deepcopy(original)
    messages, wire, visible = blind_question_request(packet, original, 'APPROVED_SOURCE_CONTEXT', view)
    assert original == before
    fmt = option_predicates_format(packet, visible)
    props = fmt['json_schema']['schema']['properties']
    item_ids = props['judgments']['items']['properties']['item_id']['enum']
    return packet, original, messages, wire, visible, fmt, item_ids


def response(packet, fmt, ids, statuses):
    props = fmt['json_schema']['schema']['properties']
    return {'source_fingerprint': packet.fingerprint, 'bank_fingerprint': props['bank_fingerprint']['enum'][0],
        'judgments': [{'item_id': item, 'status': status, 'reason': 'reason',
                       'source_refs': [packet.blocks[0].block_id], 'compatible_case': 'case' if status == 'SUPPORTED' else ''}
                      for item, status in zip(ids, statuses, strict=True)]}


def test_payload_has_only_visible_card_and_no_author_key_or_evidence():
    packet, original, messages, wire, visible, fmt, ids = setup_review()
    original_copy = copy.deepcopy(original)
    text = messages[1]['content']
    items = json.loads(text.split('INDEPENDENT_ITEMS_JSON\n', 1)[1].split('\nFULL_ORIGINAL_SOURCE\n', 1)[0])
    assert len(items) == 3 and all(set(row) == {'item_id', 'prompt', 'candidate_answer'} for row in items)
    assert all('VISIBLE_QUIZ_TITLE' in row['prompt'] for row in items)
    assert 'PROSE_PRIVATE_SENTINEL' not in text and 'EXPLANATION_PRIVATE_SENTINEL' not in text
    assert 'correct_index' not in text and 'source_refs' not in text and packet.blocks[0].block_id not in text
    assert 'APPROVED_SOURCE_CONTEXT' in text
    assert visible['lessons'][0]['questions'][0]['prompt'].startswith('Visible quiz title: VISIBLE_QUIZ_TITLE')
    assert wire['json_schema']['name'] == fmt['json_schema']['name'] == 'v3_practical_option_predicates_v1'
    assert original == original_copy and len(ids) == 3


@pytest.mark.parametrize(('statuses', 'expected_proposals', 'expected_unknown'), [
    (['NOT_SUPPORTED', 'SUPPORTED', 'NOT_SUPPORTED'], 0, 0),
    (['SUPPORTED', 'NOT_SUPPORTED', 'NOT_SUPPORTED'], 1, 0),
    (['SUPPORTED', 'SUPPORTED', 'NOT_SUPPORTED'], 1, 0),
    (['UNDECIDABLE', 'NOT_SUPPORTED', 'NOT_SUPPORTED'], 0, 1),
    (['SUPPORTED', 'SUPPORTED', 'UNDECIDABLE'], 1, 1),
])
def test_existing_interpretation_handles_keys_multiple_and_unknown(statuses, expected_proposals, expected_unknown):
    packet, original, _, _, visible, fmt, ids = setup_review()
    value = response(packet, fmt, ids, statuses)
    review, evidence = compile_blind_question_review(value, packet, original, visible)
    assert len(review['proposals']) == expected_proposals and review['source_questions'] == []
    assert len(evidence['unverified_observations']) == expected_unknown
    assert evidence['draft_fingerprint'] == review['draft_fingerprint'] == _digest(original)
    assert [row['option_index'] for row in evidence['judgments']] == [0, 1, 2]
    assert all('source_blocks' not in row for row in evidence['judgments'])
    if expected_proposals:
        assert review['proposals'][0]['target_id'] == 'question'
        assert review['proposals'][0]['source_refs'] == [packet.blocks[0].block_id]


@pytest.mark.parametrize('fault', ['stale_bank', 'foreign_source', 'foreign_item', 'stale_visible'])
def test_rejects_foreign_and_stale_bindings(fault):
    packet, original, _, _, visible, fmt, ids = setup_review()
    value = response(packet, fmt, ids, ['NOT_SUPPORTED', 'SUPPORTED', 'NOT_SUPPORTED'])
    if fault == 'stale_bank':
        value['bank_fingerprint'] = '0' * 64
    elif fault == 'foreign_source':
        value['judgments'][0]['source_refs'] = ['foreign']
    elif fault == 'foreign_item':
        value['judgments'][0]['item_id'] = 'foreign'
    else:
        visible['lessons'][0]['title'] = 'foreign title'
    with pytest.raises(ValueError):
        compile_blind_question_review(value, packet, original, visible)
