"""Exercise producer grammar and the actual owned-stage acceptance boundary."""
import copy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from app.modules.ai.v3.auxiliary_response_contracts import (
    citation_review_format,
    distractor_feedback_format,
    diversity_review_format,
    explanation_repair_format,
    length_repair_format,
    option_repair_format,
    prose_repair_format,
)
from app.modules.ai.v3.diversity_response_schema import diversity_author_format
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_v3_direct_bucket_checkpoint import direct_setup, response_body


def formats():
    return [explanation_repair_format(['v1']), prose_repair_format(['p1']),
            length_repair_format(['v1']), distractor_feedback_format([0, 2]),
            option_repair_format(['v1']), option_repair_format(['v1'], include_prompt=True),
            citation_review_format(['q1']), diversity_review_format('f' * 64, 3, ['r1']),
            diversity_author_format('v1', 'literal source')]


@pytest.mark.parametrize('fmt', formats())
def test_each_auxiliary_contract_is_accepted_by_the_actual_connector_grammar(fmt):
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('v3_auxiliary_connector_grammar', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._checked_structured_format(fmt)
    assert response_contract(fmt) is not None


@pytest.mark.parametrize('fmt', formats())
def test_auxiliary_names_cannot_authorize_a_weakened_schema(fmt):
    changed = copy.deepcopy(fmt)
    changed['json_schema']['schema']['additionalProperties'] = True
    assert response_contract(changed) is None
    changed = copy.deepcopy(fmt)
    changed['json_schema']['strict'] = False
    assert response_contract(changed) is None


def test_diversity_allows_multiple_omitted_facts_from_one_rule_but_not_foreign_indices():
    fmt = diversity_review_format('f' * 64, 3, ['r1'])
    result = {'fingerprint': 'f' * 64, 'status': 'observed', 'overlaps': [[1, 3]],
              'omissions': [{'rule_id': 'r1', 'exact_quote': 'first condition'},
                            {'rule_id': 'r1', 'exact_quote': 'second condition'}]}
    assert matches_response_contract(result, fmt)
    result['overlaps'] = [[0, 3]]
    assert not matches_response_contract(result, fmt)
    result['overlaps'] = [[True, 3]]
    assert not matches_response_contract(result, fmt)


@pytest.mark.asyncio
@pytest.mark.parametrize('partial', [False, True])
async def test_partial_option_repair_is_checked_before_durable_completion(monkeypatch, partial):
    fake, journal, client, _plan, _validate = direct_setup()
    fmt = option_repair_format(['v1', 'v2'], allow_partial=partial)
    content = {'repairs': [{'variant_id': 'v1', 'correct': 'correct action',
                'distractors': [{'text': f'wrong {i}', 'category': 'role_confusion'} for i in range(3)],
                'explanation': 'source explanation'}]}
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith('input_tokens'):
            return httpx.Response(200, stream=httpx.ByteStream(b'{"object":"response.input_tokens","input_tokens":12}'))
        return httpx.Response(200, stream=httpx.ByteStream(response_body(content)))

    real = httpx.AsyncClient
    monkeypatch.setattr('app.modules.ai.direct_luna_responses_client.httpx.AsyncClient',
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))

    async def forbidden():
        raise AssertionError('unowned invocation')

    kwargs = dict(journal=journal, direct_client=client, stage='repair', group_id='auxiliary:fixture',
                  source_sha256='b' * 64, route_fingerprint=client.cache_fingerprint(),
                  messages=[{'role': 'user', 'content': 'synthetic partial repair'}],
                  response_format=fmt, direct_max_output_tokens=128, invoke=forbidden)
    if partial:
        assert await stage_once(**kwargs) == content
        assert await stage_once(**kwargs) == content
        assert not has_pending(fake.job.result)
    else:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(**kwargs)
        assert has_pending(fake.job.result)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(**kwargs)
    assert len(requests) == 2
    assert json.loads(requests[-1].content)['model'] == 'gpt-6-luna'
