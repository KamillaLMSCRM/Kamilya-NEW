"""Multi-finding metadata crosses real custody/finalize/cold-replay contracts."""
import json

import pytest

from app.modules.ai.v3.practical_author_transport import normalize_practical_author
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V11_POLICY
from app.modules.ai.v3.simple_finding_evidence import evidence_format, matches_evidence
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v8 import fresh_journal


@pytest.mark.parametrize('phase', [
    'envelope', 'model', 'choices', 'message', 'content_limit', 'content_json', 'usage',
    'structured_mode', 'structured_shape', 'stage_validation', 'stage_metadata', 'stage_finalize',
])
def test_historical_http_capture_phases_are_retained_without_authorizing_replay(phase):
    from app.modules.ai.v3.managed_rejection_quarantine import _valid_reference, private_key
    from app.modules.ai.v3.retained_author_replay import retained_phase_allowed
    digest = 'a' * 64
    reference = {'stage_sha256': digest, 'checkpoint_key': private_key(digest),
        'accepted': False, 'phase': phase, 'byte_count': 10, 'body_sha256': 'b' * 64,
        'route_fingerprint': 'c' * 64, 'complete_http_response': True, 'status': 200,
        'wire_request_sha256': 'd' * 64}
    assert _valid_reference(digest, reference)
    plan = {'stage': 'repair', 'group_id': 'practical:simple:repair-evidence:v11:'+'a'*64
        +':unit='+'b'*64+':proposal='+'c'*64+':output=32768'}
    assert retained_phase_allowed(plan, phase) == (phase == 'stage_finalize')


@pytest.mark.parametrize('field,value', [
    ('phase', None), ('phase', []), ('phase', 'foreign'), ('body_sha256', None),
    ('wire_request_sha256', []), ('status', True), ('complete_http_response', 'true'),
])
def test_malformed_history_cannot_be_a_valid_reference(field, value):
    from app.modules.ai.v3.managed_rejection_quarantine import _valid_reference, private_key
    digest = 'a' * 64
    reference = {'stage_sha256': digest, 'checkpoint_key': private_key(digest),
        'accepted': False, 'phase': 'stage_finalize', 'byte_count': 10, 'body_sha256': 'b' * 64,
        'route_fingerprint': 'c' * 64, 'complete_http_response': True, 'status': 200,
        'wire_request_sha256': 'd' * 64, field: value}
    assert not _valid_reference(digest, reference)


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['managed', 'cloud'])
async def test_two_bindings_finalize_and_cold_replay_after_jsonb_reorders_objects(monkeypatch, transport):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V11_POLICY
    client = client_for(journal)
    fingerprints = {key: 'a' * 64 for key in (
        'source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')}
    fingerprints.update(result_fingerprint='b' * 64, inventory_fingerprint='c' * 64)
    fmt = evidence_format(fingerprints, {'finding-z': ['SRC2', 'SRC1'], 'finding-a': ['SRC1']})
    answer = {**fingerprints, 'bindings': {'finding-z': 'SRC2', 'finding-a': 'UNRESOLVED'}}
    calls = []

    async def managed(capability, *, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        calls.append('managed')
        request = client._prepared[capability]
        envelope = {'model': client.model, 'structured_output_policy': 'typed-json-object-v1',
            'response_format_sha256': response_contract_hash(fmt),
            'choices': [{'message': {'content': json.dumps(answer)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 25}}
        return client._decode_response(json.dumps(envelope).encode(), request)[0]

    async def cloud():
        calls.append('cloud')
        return normalize_practical_author(json.dumps(answer), fmt)

    def validate(value):
        assert matches_evidence(value, fmt)

    monkeypatch.setattr(client, 'invoke', managed)
    arguments = dict(stage='repair',
        group_id='practical:simple:repair-evidence:v11:'+'a'*64+':unit='+'b'*64+':proposal='+'c'*64+':output=32768',
        source_sha256='e'*64, route_fingerprint=client.cache_fingerprint(),
        messages=[{'role': 'user', 'content': 'Synthetic owned metadata only'}], response_format=fmt,
        invoke=cloud, direct_client=client if transport == 'managed' else None,
        direct_max_output_tokens=32768, response_validator=validate)
    try:
        first = await stage_once(journal, **arguments)
        assert first == answer and calls == [transport]
        cold = fresh_journal(journal, fake)
        cold.expected_review_policy = SIMPLE_COURSE_REVIEW_V11_POLICY
        assert await stage_once(cold, **arguments) == answer
        assert calls == [transport]
        assert 'v3_pending_stages' not in fake.job.result
    finally:
        client.close()
