"""Source-row evidence, explicit decisions, and retained-author controls."""
import json

import pytest

from app.modules.source_editorial_review.analysis import _independent_review_reply, _unverified_clues, analyze
from app.modules.source_editorial_review.question_context import POLICY, REQUEST_POLICY, QuestionContextError, contexts

SOURCE = ('| Product | Mass | Description | Attributes |\n| --- | --- | --- | --- |\n'
          '| A | 0 | A has two units. | Units: 1 |\n'
          '| B | 0 | B has one unit. | Units: 1 |\n')


def ref(payload, label):
    context = payload['source_question_context']
    text = payload['original']
    return next(row['id'] for row in context['references']
                if label in text[max(0, row['start']):row['end']])


def test_repeated_evidence_binds_only_to_the_explicit_native_row():
    context, = contexts(SOURCE, [(0, SOURCE)])
    assert context is not None
    refs = {unit.text.split('|')[1].strip(): key for key, unit in context.references.items()
            if unit.kind == 'table_row'}
    span = context.bind('Units: 1', [refs['B']])
    assert SOURCE[span[0]:span[1]] == 'Units: 1'
    assert context.same_row('| B | 0 | B has one unit. | Units: 1 |', span)
    assert not context.same_row('| A | 0 | A has two units. | Units: 1 |', span)
    with pytest.raises(QuestionContextError):
        context.bind('Units: 99', [refs['B']])
    with pytest.raises(QuestionContextError):
        context.bind('Units: 1', ['foreign'])
    assert 'Mass' in context.request()['table_headers'][0]['text']


@pytest.mark.asyncio
async def test_declined_comment_is_audited_and_does_not_hide_a_real_peer_conflict():
    author = {'patches': [], 'unresolved': [
        {'alias': 'possibleA', 'excerpt': '| A | 0 | A has two units. | Units: 1 |',
         'category': 'conflict', 'reason': 'Two or one?'},
        {'alias': 'possibleB', 'excerpt': '| B | 0 | B has one unit. | Units: 1 |',
         'category': 'conflict', 'reason': 'Possible mismatch.'}]}
    calls = []

    async def complete(messages):
        payload = json.loads(messages[1]['content'])
        calls.append(payload)
        if 'proposal_sha256' not in payload:
            # Existing editor requests remain byte compatible with custody.
            assert 'source_question_context' not in payload
            return author
        a, b = ref(payload, '| A |'), ref(payload, '| B |')
        return {'proposal_sha256': payload['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': 'A has two units.', 'category': 'conflict', 'reason': 'One or two units?',
             'disposition': 'needs_human', 'source_refs': [a]},
            {'excerpt': 'B has one unit.', 'category': 'conflict', 'reason': 'There is no conflict.',
             'disposition': 'dismissed', 'source_refs': [b]}], 'source_clue_dispositions': [
            {'clue_id': 0, 'disposition': 'confirmed', 'question_index': 0},
            {'clue_id': 1, 'disposition': 'dismissed', 'evidence_excerpt': 'Units: 1',
             'evidence_source_ref': b, 'reason': 'The same product row consistently specifies one unit.'}]}

    result = await analyze(SOURCE, source_id='synthetic', document_id='owned', complete_json=complete)
    assert len(calls) == 2 and result['original'] == SOURCE and not result['automatic']
    issue, = result['issues']
    assert issue['quote'] == 'A has two units.' and issue['start'] == SOURCE.index(issue['quote'])
    assert issue['source_labels'] == ['A']
    assert len(result['dismissed_questions']) == 1
    assert result['dismissed_questions'][0]['reason'] == 'There is no conflict.'


def test_partial_window_carries_full_literal_row_and_parent_headers_without_rewriting():
    offset = SOURCE.index('B has one unit.') + 4
    text = SOURCE[offset:offset + 8]
    context, = contexts(SOURCE, [(offset, text)])
    assert context is not None
    payload = context.request()
    assert len(payload['references']) == 1
    assert '| B |' in payload['references'][0]['complete_original_context']
    assert 'Mass' in payload['table_headers'][0]['text']
    assert context.original[context.offset:context.end] == text


def test_unique_original_navigation_requires_one_literal_occurrence_inside_a_native_row():
    source = SOURCE + '\nA unique prose statement.\n'
    context, = contexts(source, [(0, source)])
    assert context is not None
    assert context.unique_literal_row('Units: 1') is None
    assert context.unique_literal_row('A unique prose statement.') is None
    assert context.unique_literal_row('A HAS two units.') is None
    assert context.unique_literal_row('| A | 0 | A has two units. | Units: 1 |\n| B |') is None
    assert context.unique_literal_row('A has two units.') is not None
    assert context.request()['policy'] == REQUEST_POLICY != POLICY


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['unknown_ref', 'multiple_refs', 'dismissed'])
async def test_literal_reference_correction_never_guesses_unknown_multirow_or_dismissed_hints(kind):
    from app.modules.source_editorial_review.question_quotes import repair_question_quotes
    context, = contexts(SOURCE, [(0, SOURCE)])
    assert context is not None
    refs = {u.text.split('|')[1].strip(): k for k, u in context.references.items() if u.kind == 'table_row'}
    reported = {'excerpt': 'A has two units.', 'reason': 'Two or one?', 'category': 'conflict',
                'source_refs': ['foreign'] if kind == 'unknown_ref' else
                    [refs['A'], refs['B']] if kind == 'multiple_refs' else [refs['B']],
                'disposition': 'dismissed' if kind == 'dismissed' else 'needs_human'}
    async def no_repairs(_):
        return {'repairs': []}
    repaired, changes, _ = await repair_question_quotes([reported], context=context,
        proposal_sha256='a' * 64, complete_json=no_repairs, restore=lambda *_: None)
    assert repaired == [reported] and not changes


@pytest.mark.parametrize('bad_evidence', ['foreign', 'A', None])
def test_other_product_or_missing_reference_cannot_dismiss_a_literal_clue(bad_evidence):
    context, = contexts(SOURCE, [(0, SOURCE)])
    assert context is not None
    refs = {unit.text.split('|')[1].strip(): key for key, unit in context.references.items()
            if unit.kind == 'table_row'}
    raw = {'proposal_sha256': 'a' * 64, 'rows': [], 'source_questions': [], 'source_clue_dispositions': [
        {'clue_id': 0, 'disposition': 'dismissed', 'evidence_excerpt': 'Units: 1',
         'evidence_source_ref': refs.get(bad_evidence, bad_evidence), 'reason': 'Consistent within the product.'}]}
    clue = '| B | 0 | B has one unit. | Units: 1 |'
    assert _unverified_clues(_independent_review_reply(raw), {0: clue}, SOURCE, context) == [0]


def test_repeated_clue_can_link_to_an_open_row_question_but_cannot_be_dismissed_on_another_product():
    context, = contexts(SOURCE, [(0, SOURCE)])
    assert context is not None
    a = next(key for key, unit in context.references.items() if '| A |' in unit.text)
    b = next(key for key, unit in context.references.items() if '| B |' in unit.text)
    raw = {'proposal_sha256': 'a' * 64, 'rows': [], 'source_questions': [
        {'excerpt': 'A has two units.', 'category': 'conflict', 'reason': 'Two or one?',
         'disposition': 'needs_human', 'source_refs': [a]}],
        'source_clue_dispositions': [{'clue_id': 0, 'disposition': 'confirmed', 'question_index': 0}]}
    links = []
    assert _unverified_clues(_independent_review_reply(raw), {0: 'Units: 1'}, SOURCE, context, links) == []
    assert links == [{'clue_id': 0, 'question_index': 0, 'source_ref': a,
                      'binding': 'row_local_literal_confirmation', 'reported_clue_occurrences': 2}]
    raw['source_clue_dispositions'] = [{'clue_id': 0, 'disposition': 'dismissed', 'evidence_excerpt': 'B has one unit.',
                                      'evidence_source_ref': b, 'reason': 'The other product agrees.'}]
    assert _unverified_clues(_independent_review_reply(raw), {0: 'Units: 1'}, SOURCE, context) == [0]
    raw['source_clue_dispositions'] = [{'clue_id': 0, 'disposition': 'confirmed', 'question_index': 0}]
    assert _unverified_clues(_independent_review_reply(raw), {0: 'B has one unit.'}, SOURCE, context) == [0]


@pytest.mark.asyncio
async def test_dismissing_one_clue_cannot_erase_an_independent_question_on_that_same_row():
    async def complete(messages):
        p = json.loads(messages[1]['content'])
        if 'proposal_sha256' not in p:
            return {'patches': [], 'unresolved': [{'alias': 'B', 'excerpt': '| B | 0 | B has one unit. | Units: 1 |',
                                                  'category': 'conflict', 'reason': 'Check units.'}]}
        b = ref(p, '| B |')
        return {'proposal_sha256': p['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': 'B has one unit.', 'category': 'conflict', 'reason': 'The unit count agrees.',
             'disposition': 'dismissed', 'source_refs': [b]},
            {'excerpt': '| B | 0', 'category': 'unclear', 'reason': 'Is zero mass intentionally unspecified?',
             'disposition': 'needs_human', 'source_refs': [b]}], 'source_clue_dispositions': [
            {'clue_id': 0, 'disposition': 'dismissed', 'evidence_excerpt': 'Units: 1',
             'evidence_source_ref': b, 'reason': 'The unit count agrees.'}]}
    r = await analyze(SOURCE, source_id='test', document_id='owned', complete_json=complete)
    issue, = r['issues']
    assert issue['quote'] == '| B | 0' and len(r['dismissed_questions']) == 1


@pytest.mark.asyncio
async def test_invalid_reference_cannot_hide_a_dismissed_question_or_bind_via_global_repair():
    async def complete(messages):
        p = json.loads(messages[1]['content'])
        if 'proposal_sha256' not in p:
            return {'patches': [], 'unresolved': []}
        return {'proposal_sha256': p['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': 'B has one unit.', 'category': 'conflict', 'reason': 'The unit count agrees.',
             'disposition': 'dismissed', 'source_refs': ['foreign']}]}
    r = await analyze(SOURCE, source_id='test', document_id='owned', complete_json=complete)
    issue, = r['issues']
    assert issue['start'] is None and issue['needs_source_verification']
    assert not r['dismissed_questions']


def test_explicit_row_disambiguates_a_quote_repeated_in_other_products():
    context, = contexts(SOURCE, [(0, SOURCE)])
    assert context is not None
    b = next(key for key, unit in context.references.items() if '| B |' in unit.text)
    assert context.bind('Units: 1', [b])[0] == SOURCE.rindex('Units: 1')
    with pytest.raises(QuestionContextError):
        context.bind('Units: 1', [b, b])


def test_spaced_native_table_supplies_bold_real_headers_not_empty_markdown_header():
    source = '| | | |\n\n| --- | --- | --- |\n\n| **SKU** | **Weight** | **Description** |\n\n| A | 0 | Example |'
    offset = source.index('| A |')
    context, = contexts(source, [(offset, source[offset:])])
    assert context is not None
    header, = context.request()['table_headers']
    assert '**Weight**' in header['text'] and header['text'] in source


@pytest.mark.asyncio
async def test_completed_row_review_checkpoint_replays_with_dismissal_audit_and_zero_calls():
    saved = {}
    calls = []
    async def complete(messages):
        calls.append(messages)
        p = json.loads(messages[1]['content'])
        if 'proposal_sha256' not in p:
            return {'patches': [], 'unresolved': []}
        b = ref(p, '| B |')
        return {'proposal_sha256': p['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': 'B has one unit.', 'category': 'conflict', 'reason': 'Consistent.',
             'disposition': 'dismissed', 'source_refs': [b]}]}
    async def checkpoint(key, value):
        saved[key] = value
    first = await analyze(SOURCE, source_id='test', document_id='owned', complete_json=complete, checkpoint=checkpoint)
    assert len(calls) == 2
    second = await analyze(SOURCE, source_id='test', document_id='owned', complete_json=complete, retained=saved)
    assert len(calls) == 2 and second['model_calls'] == 0
    assert second['dismissed_questions'] == first['dismissed_questions']
    assert second['issues'] == first['issues'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('repair_quote', ['A has two units.', 'B has one unit.'])
async def test_model_repairs_only_nonliteral_quote_and_cannot_borrow_another_product(repair_quote):
    calls = []
    reported = 'A has two units. ... Units: 1'
    async def complete(messages):
        p = json.loads(messages[1]['content'])
        calls.append(p)
        if p.get('task') == 'source-question-evidence-address-v2':
            assert len(p['items']) == 2 and p['items'][0]['question_index'] == 0
            assert len(p['original_rows']) == 2 and p['items'][0]['finding_reason'] == 'One or two units?'
            return {'repairs': [{'question_index': 0, 'source_refs': p['items'][0]['reported_source_refs'], 'excerpt': repair_quote}]}
        if 'proposal_sha256' not in p:
            return {'patches': [], 'unresolved': [{'alias': 'A', 'excerpt': '| A | 0 | A has two units. | Units: 1 |',
                                                  'category': 'conflict', 'reason': 'Two or one?'}]}
        a, b = ref(p, '| A |'), ref(p, '| B |')
        return {'proposal_sha256': p['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': reported, 'category': 'conflict', 'reason': 'One or two units?',
             'disposition': 'needs_human', 'source_refs': [a]},
            {'excerpt': 'B has one unit.', 'category': 'unclear', 'reason': 'Independent peer stays open.',
             'disposition': 'needs_human', 'source_refs': [b]}],
            'source_clue_dispositions': [{'clue_id': 0, 'disposition': 'confirmed', 'question_index': 0}]}
    result = await analyze(SOURCE, source_id='test', document_id='owned', complete_json=complete)
    assert len(calls) == 3 and result['original'] == SOURCE and not result['automatic']
    peer = next(q for q in result['issues'] if q['reason'] == 'Independent peer stays open.')
    assert peer['quote'] == 'B has one unit.' and peer['start'] == SOURCE.index(peer['quote'])
    if repair_quote.startswith('A '):
        assert len(result['issues']) == 2
        repaired = next(q for q in result['issues'] if q['reason'] == 'One or two units?')
        assert repaired['quote'] == repair_quote and repaired['reported_quote'] == reported
        assert repaired['quote_binding'] == 'source-question-evidence-address-v2'
        assert repaired['start'] == SOURCE.index(repair_quote)
    else:
        invalid = next(q for q in result['issues'] if q['quote'] == reported)
        assert invalid['start'] is None and invalid['needs_source_verification']


@pytest.mark.asyncio
async def test_unique_literal_row_overrides_conflicting_known_hint_without_borrowing_shared_text():
    shared = 'A shared collection introduction.'
    source = ('| Product | Description | Attributes |\n| --- | --- | --- |\n'
              '| First | ' + shared + ' | Units: 1 |\n'
              '| Second | ' + shared + ' Two units described. | Units: 1 |\n')
    excerpt = '| Second | ' + shared + ' Two units described. | Units: 1 |'
    calls = []

    async def complete(messages):
        data = json.loads(messages[1]['content'])
        calls.append(data)
        if data.get('task') == 'source-question-evidence-address-v2':
            return {'repairs': [{'question_index': 0, 'excerpt': shared}]}
        if 'proposal_sha256' not in data:
            return {'patches': [], 'unresolved': [
                {'alias': 'second', 'excerpt': excerpt, 'category': 'conflict', 'reason': 'Two or one?'}]}
        wrong = ref(data, '| First |')
        return {'proposal_sha256': data['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': excerpt, 'category': 'conflict', 'reason': 'Two or one?',
             'disposition': 'needs_human', 'source_refs': [wrong]}],
            'source_clue_dispositions': [{'clue_id': 0, 'disposition': 'confirmed', 'question_index': 0}]}

    result = await analyze(source, source_id='synthetic', document_id='owned', complete_json=complete)
    assert len(calls) == 2, 'A fully literal original quote needs no model shortening'
    question, = result['issues']
    assert question['quote'] == excerpt and question['start'] == source.index(excerpt)
    assert question['source_labels'] == ['Second']
    assert question['reported_source_refs'] != question['source_refs']
    assert question['source_ref_binding'] == 'unique_original_literal_v1'
    assert question['reason'] == 'Two or one?' and result['original'] == source and not result['automatic']


@pytest.mark.asyncio
@pytest.mark.parametrize('literal', [True, False])
async def test_long_quote_is_not_a_semantic_failure_but_fabricated_evidence_stays_unverified(literal):
    text = 'Source detail. ' * 180
    row = '| A | ' + text + 'Two units. Units: 1 |'
    source = '| Item | Text |\n| --- | --- |\n' + row + '\n'
    excerpt = row if literal else 'Invented assertion. ' * 140
    calls = []
    async def complete(messages):
        data = json.loads(messages[1]['content'])
        calls.append(data)
        if data.get('task'):
            return {'repairs': []}
        if 'proposal_sha256' not in data:
            return {'patches': [], 'unresolved': []}
        return {'proposal_sha256': data['proposal_sha256'], 'rows': [], 'source_questions': [
            {'excerpt': excerpt, 'category': 'conflict', 'reason': 'Two units or one?',
             'source_refs': [ref(data, '| A |')], 'disposition': 'needs_human'}]}
    result = await analyze(source, source_id='synthetic', document_id='owned', complete_json=complete)
    assert result['original'] == source and not result['automatic']
    question, = result['issues']
    if literal:
        assert len(calls) == 2 and question['quote'] == row
        assert question['start'] == source.index(row) and not question.get('needs_source_verification')
    else:
        assert len(calls) == 3 and question['start'] is None and question['needs_source_verification']


@pytest.mark.asyncio
async def test_explicit_recheck_is_revision_guarded_and_cannot_reopen_approved_or_edited_sources(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from app.modules.source_editorial_review.domain import ReviewCommand, ReviewConflictError, ReviewState
    from app.modules.source_editorial_review.service import apply_command, can_recheck_questions

    actor = uuid4()
    analyzed = SimpleNamespace(kind='analyzed', sequence=3, payload={}, request_id=None)
    state = ReviewState(revision=3, status='in_review', original=SOURCE)
    assert can_recheck_questions([analyzed], state)
    analyzed.payload['question_context_policy'] = POLICY
    assert not can_recheck_questions([analyzed], state)
    analyzed.payload.clear()
    for status in ['approved', 'failed', 'running', 'queued']:
        state.status = status
        assert not can_recheck_questions([analyzed], state)
    state.status = 'in_review'
    state.decisions = {'human': {'decision': 'replace'}}
    assert not can_recheck_questions([analyzed], state)
    state.decisions = {'human': {'decision': 'keep'}}
    assert can_recheck_questions([analyzed], state)
    state.disabled_auto.add('held')
    assert not can_recheck_questions([analyzed], state)
    state.disabled_auto.clear()

    # Exercise the ordinary API service, not a new queue or a direct DB write.
    monkeypatch.setattr('app.modules.source_editorial_review.service.history', AsyncMock(return_value=[analyzed]))
    monkeypatch.setattr('app.modules.source_editorial_review.service.read_state', lambda *_: state)
    monkeypatch.setattr('app.modules.source_editorial_review.service.requires_retry_acknowledgement', lambda _: False)
    monkeypatch.setattr('app.modules.source_editorial_review.service.latest_status', lambda _: 'in_review')
    monkeypatch.setattr('app.modules.source_editorial_review.service.continuation_pending', lambda *_: False)
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256='a' * 64)
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    stale = ReviewCommand(expected_revision=2, request_id=uuid4(), action='start')
    with pytest.raises(ReviewConflictError, match='revision_conflict'):
        await apply_command(db, doc, actor, stale)
    command = ReviewCommand(expected_revision=3, request_id=uuid4(), action='start')
    _, _, event, dispatch = await apply_command(db, doc, actor, command)
    assert event.kind == 'queued' and event.payload == {} and dispatch
    assert state.original == SOURCE and state.decisions == {'human': {'decision': 'keep'}}
