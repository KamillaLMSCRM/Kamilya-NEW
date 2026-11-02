import base64
from uuid import uuid4

import pytest

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.managed_rejection_quarantine import KEY, private_key
from app.modules.ai.v3.native_profile_binding import KEY as PROFILE_KEY
from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
from app.modules.ai.v3.revision_policy import KEY as REVISION_KEY
from app.modules.ai.v3.revision_policy import POLICY
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_direct_luna_owned_stage import setup


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['validator', 'carrier', 'source', 'success'])
async def test_native_private_custody(mode):
    fake, journal, _, plan, validate = setup()
    fake.job_id = journal.job_id = str(uuid4())
    plan.update(job_id=journal.job_id, route_fingerprint='a' * 64, request_sha256='b' * 64)
    journal.expected_revision_policy = POLICY
    journal.expected_native_profile = {'policy': 'v3-native-profile-binding-v1', 'fingerprint': 'a' * 64}
    fake.job.params['source_analysis'][REVISION_KEY] = POLICY
    fake.job.result[PROFILE_KEY] = journal.expected_native_profile
    calls = []
    async def source(_session, _job, _plan):
        return not (calls and mode == 'source')
    journal.verify_source = source
    async def invoke():
        calls.append(1)
        if mode == 'carrier':
            raise ModelArtifactRejectedError('synthetic').bound(job_id=journal.job_id, route='a' * 64, request='b' * 64)
        return {'rules': ['synthetic']}
    def response(value):
        if mode != 'success':
            raise ValueError('invalid')
        return value
    kwargs = dict(plan=plan, result_key='result', claim_key='claim', validate_value=validate,
                  validate_response=response, invoke=invoke)
    if mode == 'success':
        assert await journal.run_pending(**kwargs) == {'rules': ['synthetic']}
        assert KEY not in fake.job.result
    else:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await journal.run_pending(**kwargs)
        if mode != 'source':
            receipt = fake.values[private_key(_digest(plan))]
            assert receipt['capture_kind'] == 'model_content_text'
            assert receipt['complete_http_response'] is False and receipt['status'] is None
            assert b'synthetic' in base64.b64decode(receipt['raw_base64'])
            assert 'raw_base64' not in str(fake.job.result)
        else:
            assert KEY not in fake.job.result
        with pytest.raises(ExtractionOutcomeUnknownError):
            await journal.run_pending(**kwargs)
    assert len(calls) == 1


def test_carrier_immutable_and_not_rebindable():
    value = ModelArtifactRejectedError('secret').bound(job_id=str(uuid4()), route='a' * 64, request='b' * 64)
    assert 'secret' not in repr(value)
    with pytest.raises(AttributeError):
        value._job = str(uuid4())
    with pytest.raises(TypeError):
        value._metadata['provider'] = 'changed'
    with pytest.raises(ValueError):
        value.bound(job_id=str(uuid4()), route='a' * 64, request='b' * 64)
