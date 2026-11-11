import copy
import json
from dataclasses import replace
from hashlib import sha256

import pytest

from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.simple_course_editor_v2 import run_simple_course_editor_v2
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from tests.unit.test_v3_simple_course_editor import course, fixture


@pytest.mark.asyncio
async def test_independent_solver_does_not_receive_author_key_explanation_or_body():
    corpus, packet = fixture()

    class IndependentInputReachedError(Exception):
        pass

    async def stage(name, group, messages, fmt, validator):
        if name == 'lesson':
            value = course(content='HIDDEN_LESSON_BODY')
            value['lessons'][0]['questions'][0]['explanation'] = 'HIDDEN_AUTHOR_EXPLANATION'
            return value
        if ':review-content:' in group:
            value = content_response(fmt, packet)
            value['findings'] = []
            return value
        if ':review-assessment:' in group:
            assert 'HIDDEN_LESSON_BODY' not in messages[1]['content']
            assert 'HIDDEN_AUTHOR_EXPLANATION' not in messages[1]['content']
            assert 'correct_index' not in messages[1]['content']
            raise IndependentInputReachedError()
        pytest.fail('unexpected stage')

    with pytest.raises(IndependentInputReachedError):
        await run_simple_course_editor_v2(packet, corpus, {}, stage)


def approved_fixture():
    corpus, _ = fixture()
    doc = corpus.documents[0]
    original = 'OLD_PRIVATE_WORD and retained condition'
    working, spans = render_text(original, [{'id': 'replace-id', 'start': 0, 'end': 16,
                                             'before': 'OLD_PRIVATE_WORD', 'after': 'CURRENT_WORD'}])
    decisions = (
        {'item_id': 'replace-id', 'decision': 'replace', 'quote': 'OLD_PRIVATE_WORD',
         'reason': 'replacement interpretation reason', 'start': 0, 'end': 16},
        {'item_id': 'keep-id', 'decision': 'keep', 'quote': 'retained condition',
         'reason': 'keep interpretation reason', 'start': 21, 'end': 39},
    )
    approved = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approval', original, working,
        sha256(working.encode()).hexdigest(), tuple(spans), {}, decision_context=decisions)
    assert approved.valid(document_id=doc.doc_id, source_revision=doc.source_revision)
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approved),))
    return corpus, build_practical_source_packet(corpus), approved


def review_response(fmt, packet, target, correction):
    props = fmt['json_schema']['schema']['properties']
    return {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': props['draft_fingerprint']['enum'][0],
            'proposals': [{'target_id': target, 'correction': correction, 'source_refs': ['SRC1']}],
            'source_questions': []}


def content_response(fmt, packet, target='lesson', basis='unverified review basis'):
    props = fmt['json_schema']['schema']['properties']
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': props['course_fingerprint']['enum'][0],
            'summary': 'source review', 'findings': [{'domain': 'content', 'severity': 'material',
                'target': {'kind': 'lesson', 'id': target}, 'problem': 'missing instruction', 'basis': basis,
                'correction': 'content correction', 'source_refs': ['SRC1']}],
            'source_notes': [], 'narrative_sources': {'lesson': ['SRC1']}}


def blind_response(fmt, supported=True):
    props = fmt['json_schema']['schema']['properties']
    ids = props['judgments']['items']['properties']['item_id']['enum']
    return {'source_fingerprint': props['source_fingerprint']['enum'][0],
            'bank_fingerprint': props['bank_fingerprint']['enum'][0],
            'judgments': [{'item_id': item, 'status': 'SUPPORTED' if supported and index == 0 else 'NOT_SUPPORTED',
                           'reason': 'source reason', 'source_refs': ['SRC1'],
                           'compatible_case': 'source' if supported and index == 0 else ''}
                          for index, item in enumerate(ids)]}


@pytest.mark.asyncio
async def test_five_roles_have_isolated_payloads_and_current_approved_meaning():
    corpus, packet, approved = approved_fixture()
    original_approval = copy.deepcopy(approved)
    calls = []

    async def stage(name, group, messages, fmt, validator):
        calls.append((name, group))
        text = messages[1]['content']
        payload = json.loads(text.split('\nFULL_ORIGINAL_SOURCE\n', 1)[1] if ':review-assessment:' in group else text)
        assert 'OLD_PRIVATE_WORD' not in messages[1]['content']
        assert 'CURRENT_WORD' in messages[1]['content']
        assert 'replacement interpretation reason' in messages[1]['content']
        assert 'keep interpretation reason' in messages[1]['content']
        rows = payload['documents'][0]['approved_decisions']
        assert rows[0] == {'item_id': 'replace-id', 'decision': 'replace', 'reason': 'replacement interpretation reason'}
        assert rows[1]['quote'] == 'retained condition'
        assert all('start' not in row and 'end' not in row for row in rows)
        if ':author:' in group:
            assert 'not a condensed source summary' in messages[0]['content']
            assert 'without reopening the source' in messages[0]['content']
            assert 'independently conditioned procedures' in messages[0]['content']
            assert 'plausible common work mistakes' in messages[0]['content']
            assert 'persistently visible as the quiz title' in messages[0]['content']
            value = course(content='LESSON_PRIVATE_SENTINEL')
            value['lessons'][0]['questions'][0]['prompt'] = 'QUESTION_PRIVATE_SENTINEL'
        elif ':review-content:' in group:
            assert 'LESSON_PRIVATE_SENTINEL' in messages[1]['content']
            assert 'QUESTION_PRIVATE_SENTINEL' not in messages[1]['content']
            assert fmt['json_schema']['name'] == 'v3_practical_editorial_review_v1'
            value = content_response(fmt, packet)
        elif ':review-assessment:' in group:
            assert 'LESSON_PRIVATE_SENTINEL' not in messages[1]['content']
            assert 'QUESTION_PRIVATE_SENTINEL' in messages[1]['content']
            items = json.loads(text.split('INDEPENDENT_ITEMS_JSON\n', 1)[1].split('\nFULL_ORIGINAL_SOURCE\n', 1)[0])
            assert all('Visible quiz title: Title' in item['prompt'] for item in items)
            assert all(set(item) == {'item_id', 'prompt', 'candidate_answer'} for item in items)
            assert 'correct_index' not in text and 'explanation' not in text
            value = blind_response(fmt)
        elif ':review-explanations:' in group:
            assert payload['question_explanations'][0]['visible_quiz_title'] == 'Title'
            assert payload['question_explanations'][0]['correct_index'] == 0
            assert fmt['json_schema']['schema']['properties']['proposals']['items']['properties']['target_id']['enum'] == ['question']
            value = review_response(fmt, packet, 'question', 'question correction')
        else:
            assert 'content correction' in messages[1]['content'] and 'question correction' in messages[1]['content']
            props = fmt['json_schema']['schema']['properties']
            unchanged = course(content='LESSON_PRIVATE_SENTINEL')
            unchanged['lessons'][0]['questions'][0]['prompt'] = 'QUESTION_PRIVATE_SENTINEL'
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': props['draft_fingerprint']['enum'][0],
                     'course': unchanged, 'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': ['SRC1']}],
                     'source_questions': [], 'source_question_decisions': []}
        validator(value)
        return value

    result = await run_simple_course_editor_v2(packet, corpus, {'audience': 'staff'}, stage)
    assert [name for name, _ in calls] == ['lesson', 'review', 'review', 'review', 'repair']
    assert [group.split(':')[2] for _, group in calls] == ['author', 'review-content', 'review-assessment', 'review-explanations', 'editor']
    assert [p['target_id'] for p in result.review['proposals']] == ['lesson', 'question']
    assert all(p['source_refs'] == [packet.blocks[0].block_id] for p in result.review['proposals'])
    assert result.course == result.draft and result.changes == []
    assert approved == original_approval


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_target', ['question', 'foreign'])
async def test_content_audit_rejects_wrong_target_without_repeat(bad_target):
    corpus, packet, _ = approved_fixture()
    calls = []

    async def stage(name, group, messages, fmt, validator):
        calls.append(name)
        if name == 'lesson':
            return course()
        return content_response(fmt, packet, bad_target)

    with pytest.raises(ValueError, match='editorial_review_response_invalid'):
        await run_simple_course_editor_v2(packet, corpus, {}, stage)
    assert calls == ['lesson', 'review']


@pytest.mark.asyncio
async def test_rejects_unapproved_source_before_any_stage():
    corpus, packet, _ = approved_fixture()
    altered = replace(corpus, documents=(replace(corpus.documents[0], source_text='tampered'),))

    async def stage(*args):
        pytest.fail('stage should not run')

    with pytest.raises(ValueError, match='simple_source_custody_invalid'):
        await run_simple_course_editor_v2(packet, altered, {}, stage)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['lesson_target', 'draft_fingerprint', 'foreign_source'])
async def test_assessment_audit_rejects_wrong_scope_and_binding(fault):
    corpus, packet, _ = approved_fixture()
    calls = []

    async def stage(name, group, messages, fmt, validator):
        calls.append(group)
        if name == 'lesson':
            return course()
        if ':review-content:' in group:
            return content_response(fmt, packet)
        if ':review-assessment:' in group:
            return blind_response(fmt, supported=False)
        value = review_response(fmt, packet, 'question', 'assessment')
        if fault == 'lesson_target':
            value['proposals'][0]['target_id'] = 'lesson'
        elif fault == 'draft_fingerprint':
            value['draft_fingerprint'] = '0' * 64
        else:
            value['proposals'][0]['source_refs'] = ['SRC99']
        return value

    with pytest.raises(ValueError):
        await run_simple_course_editor_v2(packet, corpus, {}, stage)
    assert len(calls) == 4



@pytest.mark.asyncio
async def test_review_basis_is_retained_as_unverified_observation():
    corpus, packet, _ = approved_fixture()
    calls = []

    async def stage(name, group, messages, fmt, validator):
        calls.append(name)
        if name == 'lesson':
            return course()
        if ':review-content:' in group:
            return content_response(fmt, packet, basis='unverified source and lesson basis')
        if ':review-assessment:' in group:
            return blind_response(fmt, supported=False)
        if ':review-explanations:' in group:
            return review_response(fmt, packet, 'question', 'question correction')
        props = fmt['json_schema']['schema']['properties']
        return {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': props['draft_fingerprint']['enum'][0],
                'course': course(), 'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': ['SRC1']}],
                'source_questions': [], 'source_question_decisions': []}

    result = await run_simple_course_editor_v2(packet, corpus, {}, stage)
    assert result.review['content_review']['findings'][0]['basis'] == 'unverified source and lesson basis'
    assert result.review['revision_receipt']['semantic_approval'] is False
    assert len(result.review['assessment_review']['proposals']) == 2
    assert result.review['independent_option_review']['judgments'][0]['status'] == 'NOT_SUPPORTED'
    assert calls == ['lesson', 'review', 'review', 'review', 'repair']


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['source_fingerprint', 'bank_fingerprint', 'foreign_source'])
async def test_independent_review_rejects_invalid_source_or_bank(fault):
    corpus, packet, _ = approved_fixture()
    calls = []

    async def stage(name, group, messages, fmt, validator):
        calls.append(group)
        if name == 'lesson':
            return course()
        if ':review-content:' in group:
            return content_response(fmt, packet)
        value = blind_response(fmt)
        if fault == 'foreign_source':
            value['judgments'][0]['source_refs'] = ['SRC999']
        else:
            value[fault] = '0' * 64
        return value

    with pytest.raises(ValueError):
        await run_simple_course_editor_v2(packet, corpus, {}, stage)
    assert len(calls) == 3
