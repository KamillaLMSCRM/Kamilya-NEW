import json
import math
from dataclasses import asdict

import pytest

from app.modules.ai.v3.option_repair import repair_length_shortcuts
from tests.unit.test_v3_targeted_distractor_repair import _lesson, _response


@pytest.mark.asyncio
async def test_combined_constraints_measure_actual_affected_variants_and_preserve_content():
    original = _lesson()
    snapshot = asdict(original)
    violations = ['Invariant 4 failed: length bias ratio 1.7',
                  'Invariant 4 (Shortcut Gate) failed: correct answer is longest in 75%']
    async def invoke(messages, _format):
        payload = json.loads(messages[1]['content'])
        assert payload['violations'] == violations
        assert [row['variant_id'] for row in payload['questions']] == ['v0', 'v1', 'v2', 'v3']
        for row in payload['questions']:
            length = len(row['correct_original'])
            assert row['observed_wrong_lengths'] == [len(text) for text in row['old_wrong']]
            assert row['required_at_least_one_wrong_length_gte'] == length
            assert row['required_at_least_one_wrong_length_lte'] == length
            assert row['target_average_wrong_min'] == math.ceil(length / 1.25)
            assert row['target_average_wrong_max'] == math.floor(length / 0.80)
        return _response([row['variant_id'] for row in payload['questions']])
    candidate = await repair_length_shortcuts(original, violations, ['source'], invoke, measured_feedback=True)
    assert asdict(original) == snapshot
    for before, after in zip(original.cases[0].variants, candidate.cases[0].variants, strict=True):
        assert (before.variant_id, before.prompt, before.correct_option, before.explanation, before.source_quote,
                before.scenario_premise) == (after.variant_id, after.prompt, after.correct_option, after.explanation,
                                            after.source_quote, after.scenario_premise)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['missing', 'duplicate_id', 'foreign_id', 'category', 'duplicate_text'])
async def test_invalid_responses_are_rejected_without_retry(fault):
    calls = []
    async def invoke(messages, _format):
        calls.append(1)
        ids = [row['variant_id'] for row in json.loads(messages[1]['content'])['questions']]
        result = _response(ids)
        if fault == 'missing':
            result['repairs'].pop()
        elif fault == 'duplicate_id':
            result['repairs'][1]['variant_id'] = ids[0]
        elif fault == 'foreign_id':
            result['repairs'][0]['variant_id'] = 'foreign'
        elif fault == 'category':
            result['repairs'][0]['distractors'][0]['category'] = 'invalid'
        else:
            result['repairs'][0]['distractors'][1]['text'] = result['repairs'][0]['distractors'][0]['text']
        return result
    original = _lesson()
    snapshot = asdict(original)
    with pytest.raises(ValueError):
        await repair_length_shortcuts(original, ['correct answer is longest'], ['source'], invoke, measured_feedback=True)
    assert calls == [1] and asdict(original) == snapshot
