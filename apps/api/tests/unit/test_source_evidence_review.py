"""Bounded pending-only source review preserves good work and refuses foreign proof."""
from unittest.mock import AsyncMock

import pytest

from app.modules.source_editorial_review.evidence_review import repair_pending_evidence
from app.modules.source_editorial_review.question_context import contexts

SOURCE = '| Item | Text |\n| --- | --- |\n| A | Two doors. Two doors. Units: 3 |\n| B | One door. |\n'


@pytest.mark.asyncio
async def test_pending_repair_keeps_good_peer_and_all_repeated_proof():
    context, = contexts(SOURCE, [(0, SOURCE)])
    a, b = context.references
    good = {'id': 'good', 'quote': 'One door.', 'reason': 'Existing good finding.', 'source_refs': [b]}
    pending = {'id': 'pending', 'quote': 'Two doors...', 'reason': 'Two or three?', 'needs_source_verification': True}
    pending['author_candidate'] = {'alias': 'original-object-A', 'excerpt': 'Two doors...',
                                   'category': 'conflict', 'reason': 'Original clue for A.'}
    complete = AsyncMock(return_value={'decisions': [{'id': 'pending', 'disposition': 'needs_human',
        'reason': 'How many doors does A have?', 'evidence': [{'source_ref': a, 'excerpt': 'Two doors.'},
                                                           {'source_ref': a, 'excerpt': 'Units: 3'}]}]})
    questions, dismissed, audit = await repair_pending_evidence([good, pending], context=context,
        proposal_sha256='a'*64, complete_json=complete)
    assert questions[0] == good and not dismissed and audit['status'] == 'complete'
    fixed = questions[1]
    assert len(fixed['source_evidence']) == 3 and fixed['source_refs'] == [a]
    assert fixed['start'] is None and not fixed.get('needs_source_verification')
    assert fixed['source_scopes'][0]['text'] == context.references[a].text
    complete.assert_awaited_once()
    import json
    request = json.loads(complete.await_args.args[0][1]['content'])
    assert request['findings'][1]['author_candidate'] == pending['author_candidate']


@pytest.mark.asyncio
async def test_cross_product_coverage_cannot_hide_the_original_material_warning():
    context, = contexts(SOURCE, [(0, SOURCE)])
    a, b = context.references
    pending = {'id': 'a', 'quote': context.references[a].text, 'reason': 'A needs confirmation.',
               'needs_source_verification': True}
    good = {'id': 'b', 'quote': 'One door.', 'reason': 'B is independent.', 'source_refs': [b]}
    complete = AsyncMock(return_value={'decisions': [{'id': 'a', 'disposition': 'covered', 'covered_by': 'b',
        'reason': 'Wrong peer.', 'evidence': [{'source_ref': b, 'excerpt': 'One door.'}]}]})
    questions, dismissed, audit = await repair_pending_evidence([pending, good], context=context,
        proposal_sha256='b'*64, complete_json=complete)
    assert pending in questions and good in questions and not dismissed
    assert audit['status'] == 'partial_or_unverified'


@pytest.mark.asyncio
async def test_missing_or_bad_decision_preserves_other_valid_decisions():
    context, = contexts(SOURCE, [(0, SOURCE)])
    a = next(iter(context.references))
    items = [{'id': item, 'quote': 'Reported...', 'reason': 'Needs verification.',
              'needs_source_verification': True} for item in ['one', 'two']]
    complete = AsyncMock(return_value={'decisions': [
        {'id': 'one', 'disposition': 'needs_human', 'reason': 'Confirm A count.',
         'evidence': [{'source_ref': a, 'excerpt': 'Units: 3'}]},
        {'id': 'two', 'disposition': 'dismissed', 'reason': 'No proof.', 'evidence': []}]})
    questions, _, audit = await repair_pending_evidence(items, context=context,
        proposal_sha256='c'*64, complete_json=complete)
    assert any(q['id'] == 'one' and not q.get('needs_source_verification') for q in questions)
    assert items[1] in questions and len(audit['rejected']) == 1


@pytest.mark.asyncio
async def test_ready_findings_never_invoke_another_model():
    context, = contexts(SOURCE, [(0, SOURCE)])
    complete = AsyncMock()
    findings = [{'id': 'ready', 'quote': 'One door.', 'reason': 'Ready.'}]
    assert await repair_pending_evidence(findings, context=context, proposal_sha256='d'*64,
                                         complete_json=complete) == (findings, [], {})
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_known_bad_evidence_gets_one_corrective_input_without_repeating_good_decisions():
    import json
    context, = contexts(SOURCE, [(0, SOURCE)])
    a = next(iter(context.references))
    pending = [{'id': item, 'quote': 'Reported...', 'reason': 'Needs verification.',
                'needs_source_verification': True} for item in ['good', 'bad']]
    def verdict(item, quote):
        return {'id': item, 'disposition': 'needs_human', 'reason': 'Confirm A door count.',
                'evidence': [{'source_ref': a, 'excerpt': quote}]}
    first = {'decisions': [verdict('good', 'Two doors.'), verdict('bad', 'Invented wording')]}
    complete = AsyncMock(side_effect=[first, {'decisions': [verdict('bad', 'Units: 3')]}])
    result, _, audit = await repair_pending_evidence(pending, context=context,
        proposal_sha256='e'*64, complete_json=complete)
    assert len(result) == 2 and all(not q.get('needs_source_verification') for q in result)
    assert complete.await_count == 2 and audit['status'] == 'complete'
    correction = complete.await_args_list[1].args[0]
    assert correction[:2] == complete.await_args_list[0].args[0]
    assert json.loads(correction[2]['content']) == first
    assert json.loads(correction[3]['content'])['pending_ids'] == ['bad']


@pytest.mark.asyncio
async def test_unknown_outcome_is_never_retried_or_turned_into_a_human_question():
    context, = contexts(SOURCE, [(0, SOURCE)])
    pending = {'id': 'unknown', 'quote': 'Reported...', 'reason': 'Not verified.', 'needs_source_verification': True}
    complete = AsyncMock(side_effect=TimeoutError('unknown outcome'))
    with pytest.raises(TimeoutError):
        await repair_pending_evidence([pending], context=context, proposal_sha256='f'*64, complete_json=complete)
    complete.assert_awaited_once()
    assert pending['needs_source_verification'] is True
