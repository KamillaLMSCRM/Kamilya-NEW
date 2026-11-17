"""A bad model edit must not hide real source ambiguities or become executable."""
import json
from dataclasses import replace

import pytest

from app.modules.ai.source_editorial_model import (
    compile_editorial_author_response,
    prepare_source_working_edition,
    source_editorial_result_valid,
)
from app.modules.source_editorial_review.analysis import analyze


def oversized_case():
    before = '| SKU-TEST | ' + 'Catalogue fact. ' * 1600
    conflict = 'Width: 60 cm. Description: width 90 cm.'
    source = before + '\n\n' + conflict
    patch = {'alias': 'large_edit', 'before': before, 'after': 'Catalogue facts.',
             'category': 'grammar', 'reason': 'Correct grammar',
             'supporting_original_context_quotes': ['Catalogue fact.']}
    return source, before, conflict, {'patches': [patch], 'unresolved': []}


@pytest.mark.asyncio
@pytest.mark.parametrize('replacement', ['Catalogue facts.', 'Rewritten text. ' * 300])
async def test_guarded_large_before_is_audited_without_applying_or_guessing_span(replacement):
    source, before, _, wire = oversized_case()
    wire['patches'][0]['after'] = replacement
    calls = []

    async def complete(messages):
        calls.append(messages)
        assert len(calls) == 1, 'No reviewer is needed for zero executable patches'
        return wire

    result = await prepare_source_working_edition(source, source_id='synthetic', chunk_id='one',
                                                  complete_json=complete)
    assert result.edition.working_text == source and result.author_wire == wire
    assert not result.proposal.patches and not result.edition.applied_patch_aliases
    assert len(result.unbound_diagnostics) == 1
    diagnostic = result.unbound_diagnostics[0]
    assert diagnostic.not_a_source_span and len(diagnostic.reported_excerpt) <= 2000
    assert diagnostic.reported_excerpt not in source and str(len(before)) in diagnostic.reported_excerpt
    assert source_editorial_result_valid(result, source_text=source, source_id='synthetic', chunk_id='one')
    assert not source_editorial_result_valid(replace(result, unbound_diagnostics=()),
                                            source_text=source, source_id='synthetic', chunk_id='one')
    with pytest.raises(ValueError, match='source_editorial_author_quote_shape'):
        compile_editorial_author_response(source, source_id='synthetic', chunk_id='one', wire=wire)


@pytest.mark.asyncio
async def test_real_source_conflict_survives_oversized_cosmetic_and_checkpoint_replay():
    source, _, conflict, wire = oversized_case()
    saved = {}
    calls = []

    async def complete(messages):
        payload = json.loads(messages[1]['content'])
        calls.append(payload)
        if 'proposal_sha256' not in payload:
            return wire
        assert payload['patches'] == []
        return {'proposal_sha256': payload['proposal_sha256'], 'rows': [],
                'source_questions': [{'excerpt': conflict, 'category': 'conflict',
                                      'reason': 'Is the width 60 cm or 90 cm?'}]}

    async def checkpoint(key, value):
        saved[key] = value

    result = await analyze(source, source_id='synthetic', document_id='owned', complete_json=complete,
                           checkpoint=checkpoint)
    assert len(calls) == 2 and result['original'] == source
    assert not result['automatic'] and len(result['issues']) == 1
    assert result['issues'][0]['quote'] == conflict
    rejected = result['rejected_automatic']
    assert len(rejected) == 1 and rejected[0]['applied'] is False
    assert rejected[0]['requires_human_decision'] is False and rejected[0]['start'] is None

    async def no_new_call(messages):
        raise AssertionError('Completed source block must replay without inference')

    resumed = await analyze(source, source_id='synthetic', document_id='owned',
                            complete_json=no_new_call, retained=saved)
    assert resumed['model_calls'] == 0
    assert {key: value for key, value in resumed.items() if key != 'model_calls'} == {
        key: value for key, value in result.items() if key != 'model_calls'}


@pytest.mark.asyncio
@pytest.mark.parametrize('override', [{'before': ''}, {'before': None}, {'after': None},
                                      {'after': ''}, {'category': 'invented'}, {'alias': ''}])
async def test_malformed_row_is_not_laundered_into_an_accepted_edit(override):
    source, _, _, wire = oversized_case()
    wire['patches'][0].update(override)

    async def complete(messages):
        return wire

    with pytest.raises(ValueError):
        await prepare_source_working_edition(source, source_id='synthetic', chunk_id='one', complete_json=complete)
