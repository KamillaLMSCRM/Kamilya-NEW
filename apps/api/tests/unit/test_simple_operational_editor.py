import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_operational_review import operational_review_request
from app.modules.ai.v3.simple_postedit_cards import apply_postedit_cards, prepare_postedit_cards
from tests.unit.test_simple_postedit_cards import example as postedit_fixture


@pytest.fixture
def example():
    return postedit_fixture.__wrapped__()


def test_final_review_exposes_separate_bodies_and_untrusted_complete_cards(example):
    packet, corpus, course, review, *_ = example
    messages, fmt, _ = operational_review_request(packet, corpus, {}, course)
    payload = json.loads(messages[1]['content'])
    assert set(payload['lesson_bodies'][0]) == {'id', 'title', 'content'}
    card = payload['assessment_cards'][0]
    assert set(card) == {'id', 'lesson_id', 'lesson_title', 'prompt', 'choices', 'correct_index', 'explanation', 'source_refs'}
    assert 'UNTRUSTED' in messages[0]['content']
    assert 'ONLY that card' in messages[0]['content']
    assert fmt['json_schema']['name'] == 'v3_practical_editorial_review_v2'


def test_operational_body_edit_is_owned_and_unflagged_cards_are_immutable(example):
    packet, corpus, course, review, *_ = example
    lesson = course['lessons'][0]
    review['findings'] = [{**review['findings'][0], 'domain': 'content',
        'target': {'kind': 'lesson', 'id': lesson['id']}}]
    messages, _, context = prepare_postedit_cards(packet, corpus, {}, course, review, allow_lesson_bodies=True)
    blocks = json.loads(messages[1]['content'])['flagged_body_blocks']
    value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': context['draft_fingerprint'],
        'body_edits': [{'block_id': blocks[0]['id'], 'after': 'Corrected teaching.'}],
        'question_edits': [], 'title_edits': [], 'added_lessons': [], 'source_questions': [],
        'lesson_sources': context['lesson_sources'], 'finding_dispositions': []}
    envelope, _ = apply_postedit_cards(value, packet, course, context)
    assert envelope['course']['lessons'][0]['content'] == 'Corrected teaching.'
    assert envelope['course']['lessons'][0]['questions'] == lesson['questions']
    forbidden = copy.deepcopy(value)
    forbidden['question_edits'] = [lesson['questions'][0]]
    with pytest.raises(ValueError, match='simple_postedit_question_invalid'):
        apply_postedit_cards(forbidden, packet, course, context)


def test_default_card_editor_still_rejects_body_findings(example):
    packet, corpus, course, review, *_ = example
    review['findings'][0].update(domain='content', target={'kind': 'lesson', 'id': course['lessons'][0]['id']})
    with pytest.raises(ValueError, match='simple_postedit_findings_invalid'):
        prepare_postedit_cards(packet, corpus, {}, course, review)


@pytest.mark.parametrize('after', ['Teaching without its illustration.',
    'Teaching. ![Changed caption](source-asset:asset-' + 'a' * 64 + ')'])
def test_duplicate_image_elsewhere_cannot_hide_loss_or_caption_change(example, after):
    packet, corpus, course, review, *_ = example
    image = '![Original caption](source-asset:asset-' + 'a' * 64 + ')'
    course['lessons'][0]['content'] = 'Teaching. ' + image
    peer = copy.deepcopy(course['lessons'][0])
    peer['id'] = 'peer'
    for i, question in enumerate(peer['questions']):
        question['id'] = 'peer-question-' + str(i)
    course['lessons'].append(peer)
    review['course_fingerprint'] = _digest(course)
    review['narrative_sources']['peer'] = review['narrative_sources'][course['lessons'][0]['id']]
    review['findings'] = [{**review['findings'][0], 'domain': 'content',
        'target': {'kind': 'lesson', 'id': course['lessons'][0]['id']}}]
    messages, _, context = prepare_postedit_cards(packet, corpus, {}, course, review, allow_lesson_bodies=True)
    block = json.loads(messages[1]['content'])['flagged_body_blocks'][0]
    value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': context['draft_fingerprint'],
        'body_edits': [{'block_id': block['id'], 'after': after}], 'question_edits': [],
        'title_edits': [], 'added_lessons': [], 'source_questions': [], 'finding_dispositions': [],
        'lesson_sources': context['lesson_sources']}
    with pytest.raises(ValueError, match='simple_postedit_media_changed'):
        apply_postedit_cards(value, packet, course, context)


@pytest.mark.asyncio
async def test_full_final_body_correction_receipt_and_tampered_ancestry():
    from app.modules.ai.v3.simple_course_editor_v10 import complete_card_review_v10, postedit_review_state
    from tests.unit.test_simple_course_editor_v10 import base_case

    corpus, packet, base = base_case.__wrapped__()
    lesson = base.course['lessons'][0]

    async def stage(name, group, messages, fmt, validator):
        payload = json.loads(messages[1]['content'])
        if ':review-bank:' in group:
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(base.course),
                'summary': 'Synthetic body regression.', 'source_notes': [],
                'narrative_sources': {lesson['id']: ['SRC1']},
                'findings': [{'domain': 'content', 'severity': 'material',
                    'target': {'kind': 'lesson', 'id': lesson['id']}, 'problem': 'Missing teaching',
                    'basis': 'Source obligation', 'correction': 'Correct body', 'source_refs': ['SRC1']}]}
        else:
            assert payload['flagged_cards'] == []
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(base.course),
                'body_edits': [{'block_id': payload['flagged_body_blocks'][0]['id'], 'after': 'Corrected teaching.'}],
                'question_edits': [], 'title_edits': [], 'added_lessons': [], 'source_questions': [],
                'lesson_sources': payload['lesson_sources'], 'finding_dispositions': []}
        validator(value)
        return value

    result = await complete_card_review_v10(packet, corpus, {}, base, stage, operational_review=True)
    assert result.course['lessons'][0]['content'].startswith('Corrected teaching.\n\n![Caption a]')
    assert result.course['lessons'][0]['questions'] == lesson['questions']
    issues, _, source_hold = postedit_review_state(result, packet)
    assert len(issues) == 1 and issues[0]['blocking'] and not source_hold
    result.review['postedit_card_review']['before_lesson_bodies'][lesson['id']] += 'tampered'
    with pytest.raises(ValueError, match='simple_v10_postedit_inventory_invalid'):
        postedit_review_state(result, packet)
