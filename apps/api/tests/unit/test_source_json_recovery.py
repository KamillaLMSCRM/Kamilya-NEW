"""Known completed JSON failures recover once; uncertain requests never repeat."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaCompletedJsonError
from app.modules.source_editorial_review.analysis import _ManagedSourceJsonRecovery, analyze
from app.modules.source_editorial_review.request_custody import RequestOutcomeUnknown, identity, invoke_once


def frozen():
    return json.loads((Path(__file__).resolve().parents[4] / 'docs/testing/fixtures/'
                       'source-autocorrect115-production-luna-20261116.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_saved_production_invalid_json_and_format_reissue_reach_native_review():
    cases = {case['case']: case for case in frozen()['cases']}
    original, corrected = cases['D_FAILED'], cases['E']
    records = [*original['model_records'], *corrected['model_records']]
    count = 0
    retained = {}

    async def save(key, value):
        retained[key] = value

    async def request(messages):
        nonlocal count
        key = identity(tenant='synthetic', document=corrected['native_document_id'],
                       original_sha=corrected['source_sha256'], selected_sha='a' * 64,
                       policy='human-source-editorial-analysis-v5', route='frozen-production-luna', messages=messages)

        async def network():
            nonlocal count
            record = records[count]
            assert messages == record['messages'], 'Do not change the saved source or add semantic hints'
            count += 1
            return record['content'], {'input_tokens': record['input_tokens'], 'output_tokens': record['output_tokens']}

        return await invoke_once(key=key, attempt='initial', retained=retained, save=save,
                                 before_post=lambda: None, invoke=network, usage=lambda *_: None)

    recovery = _ManagedSourceJsonRecovery()
    result = await analyze(corrected['source'], source_id=corrected['native_source_id'],
                           document_id=corrected['native_document_id'],
                           complete_json=lambda messages: recovery.complete(messages, request))
    assert count == 3 and recovery.used
    assert result['original'] == corrected['source'] and result['automatic'] == []
    assert result['issues'] == []
    assert result['rejected_automatic'] == corrected['observed_rejected_automatic']
    assert len([key for key in retained if key.endswith(':completed')]) == 3
    replay_recovery = _ManagedSourceJsonRecovery()
    replay = await analyze(corrected['source'], source_id=corrected['native_source_id'],
                           document_id=corrected['native_document_id'],
                           complete_json=lambda messages: replay_recovery.complete(messages, request))
    assert replay == result and count == 3  # All three completed replies replay; zero fresh requests.


@pytest.mark.asyncio
async def test_raw_json_retry_budget_is_shared_across_later_calls():
    messages = [{'role': 'system', 'content': 'JSON only'}, {'role': 'user', 'content': '{}'}]
    request = AsyncMock(side_effect=['{"bad":}', '{"ok":true}', '{"again":}'])
    recovery = _ManagedSourceJsonRecovery()
    assert await recovery.complete(messages, request) == {'ok': True}
    with pytest.raises(ManagedLunaCompletedJsonError):
        await recovery.complete(messages, request)
    assert request.await_count == 3
    assert request.await_args_list[0].args[0][1:] == request.await_args_list[1].args[0][1:]


@pytest.mark.asyncio
async def test_second_completed_invalid_json_is_terminal():
    request = AsyncMock(return_value='{"bad":}')
    recovery = _ManagedSourceJsonRecovery()
    with pytest.raises(ManagedLunaCompletedJsonError):
        await recovery.complete([{'role': 'system', 'content': 'JSON only'}], request)
    assert request.await_count == 2 and recovery.used


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [TimeoutError(), RequestOutcomeUnknown('a' * 64),
    json.JSONDecodeError('Callback failed before returning a completed reply', '', 0)])
async def test_uncompleted_request_or_callback_parse_error_is_never_retried(error):
    request = AsyncMock(side_effect=error)
    recovery = _ManagedSourceJsonRecovery()
    with pytest.raises(type(error)):
        await recovery.complete([], request)
    assert request.await_count == 1 and not recovery.used
