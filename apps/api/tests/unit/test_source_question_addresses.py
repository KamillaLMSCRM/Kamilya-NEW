"""Citation repair preserves findings and native source ownership."""
import json

import pytest

from app.modules.source_editorial_review.question_context import contexts
from app.modules.source_editorial_review.question_quotes import repair_question_quotes

SOURCE = '| Item | Description |\n| --- | --- |\n| First | Shared text. One drawer. |\n| Second | Shared text. Two drawers. |\n'


@pytest.mark.asyncio
async def test_wrong_hint_and_paraphrased_quote_are_repaired_without_rewriting_good_peer():
    context, = contexts(SOURCE, [(0, SOURCE)])
    first, second = context.references
    questions = [
        {'excerpt': 'Two drawers ...', 'source_refs': [first], 'reason': 'Second: one or two drawers?',
         'category': 'conflict', 'disposition': 'needs_human'},
        {'excerpt': 'Shared text.', 'source_refs': [first], 'reason': 'First remains open.',
         'category': 'unclear', 'disposition': 'needs_human'},
    ]

    async def complete(messages):
        request = json.loads(messages[1]['content'])
        assert request['task'] == 'source-question-evidence-address-v2'
        assert len(request['original_rows']) == 2
        assert request['items'][0]['finding_reason'] == questions[0]['reason']
        return {'repairs': [
            {'question_index': 0, 'source_refs': [second], 'excerpt': 'Two drawers.'},
            {'question_index': 1, 'source_refs': [first], 'excerpt': 'One drawer.'},
        ]}

    result, changes, audit = await repair_question_quotes(
        questions, context=context, proposal_sha256='a' * 64,
        complete_json=complete, restore=lambda *_: None)
    assert result[0] == {**questions[0], 'source_refs': [second], 'excerpt': 'Two drawers.'}
    assert result[1] == questions[1]
    assert changes[0]['reported_source_refs'] == [first]
    assert changes[0]['reported_quote'] == 'Two drawers ...'
    assert audit['accepted'] == [0]


@pytest.mark.asyncio
@pytest.mark.parametrize('repair', [
    {'question_index': 0, 'source_refs': ['foreign'], 'excerpt': 'Two drawers.'},
    {'question_index': 0, 'source_refs': ['S3'], 'excerpt': 'One drawer.'},
    {'question_index': 0, 'source_refs': ['S3', 'S3'], 'excerpt': 'Two drawers.'},
    {'question_index': 0, 'source_refs': ['S3'], 'excerpt': 'Invented value.'},
    {'question_index': 99, 'source_refs': ['S3'], 'excerpt': 'Two drawers.'},
    {'question_index': 0, 'source_refs': ['S3'], 'excerpt': 'Two drawers.', 'reason': 'Source is resolved.'},
])
async def test_rejected_address_never_removes_or_resolves_the_finding(repair):
    context, = contexts(SOURCE, [(0, SOURCE)])
    first = next(iter(context.references))
    original = {'excerpt': 'Missing quote ...', 'source_refs': [first], 'reason': 'Unresolved source question.',
                'category': 'conflict', 'disposition': 'needs_human'}

    async def complete(_):
        return {'repairs': [repair]}

    result, changes, _ = await repair_question_quotes(
        [original], context=context, proposal_sha256='b' * 64,
        complete_json=complete, restore=lambda *_: None)
    assert result == [original] and not changes
