"""Actual managed client rejection -> owned private receipt -> cold pending hold."""
import asyncio
import base64
import hashlib
import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.schemas import AIJobResponse
from app.modules.ai.v3.author_response_schema import lesson_author_response_format, lesson_author_schema_hash
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.managed_rejection_quarantine import KEY, private_key
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_direct_luna_owned_stage import options, setup


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "shape", "source", "owner", "lost_ack", "cancel", "credential_echo"])
async def test_received_invalid_json_stays_private_and_never_repeats(monkeypatch, caplog, fault):
    fake, journal, _, plan, validate = setup()
    fake.job_id = journal.job_id = str(uuid4())
    plan["job_id"] = journal.job_id
    client = ManagedLunaClient(base_url="http://127.0.0.1:18999/v1", api_key="private-credential",
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id, credential_revision="test")
    plan["route_fingerprint"] = client.cache_fingerprint()
    fake.job.params["generation_reservation_released"] = False
    returned = False
    async def verify(_session, _job, _plan):
        return not (returned and fault == "source")
    journal.verify_source = verify
    raw = json.dumps({"model": "gpt-5.6-luna", "choices": [{"message": {"content": '{"private-source":'}}],
                      "usage": {"prompt_tokens": 12, "completion_tokens": 8}}).encode()
    if fault == "credential_echo":
        raw = raw.replace(b"private-source", b"private-credential")
    if fault == "shape":
        raw = json.dumps({"model": "gpt-5.6-luna", "choices": [{"message": {"content": '{}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            "structured_output_policy": "typed-json-object-v1", "response_format_sha256": lesson_author_schema_hash()}).encode()
    if fault == "cancel":
        from unittest.mock import AsyncMock
        monkeypatch.setattr("app.modules.ai.v3.managed_rejection_quarantine.retain_managed_rejection",
                            AsyncMock(side_effect=asyncio.CancelledError()))
    requests = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
    def handler(request):
        nonlocal returned
        requests.append(request)
        returned = True
        if fault == "owner":
            fake.job.user_id = uuid4()
        if fault == "lost_ack":
            fake.fail_ack = True
        return httpx.Response(200, stream=Stream())
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.managed_luna_client.httpx.AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    kwargs = options(journal, client, plan, validate)
    if fault == "shape":
        kwargs["response_format"] = lesson_author_response_format()
        plan["stage"] = "lesson"
        plan["request_sha256"] = _digest([kwargs["messages"], kwargs["response_format"]])
    with pytest.raises(asyncio.CancelledError if fault == "cancel" else ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**kwargs)
    assert has_pending(fake.job.result) and fake.job.params["generation_reservation_released"] is False
    assert "result" not in fake.values and len(requests) == 1
    if fault in {None, "lost_ack", "shape"}:
        reference = fake.job.result[KEY]["entries"][_digest(plan)]
        assert "raw_base64" not in reference and "private-source" not in json.dumps(fake.job.result)
        receipt = fake.values[private_key(_digest(plan))]
        assert reference["checkpoint_key"] == private_key(_digest(plan))
        assert base64.b64decode(receipt["raw_base64"], validate=True) == raw
        assert receipt["body_sha256"] == hashlib.sha256(raw).hexdigest()
        assert receipt["accepted"] is False and receipt["phase"] == ("structured_shape" if fault == "shape" else "content_json")
        assert (fault == "shape" or receipt["subtype"] == "syntax") and receipt["route_fingerprint"] == client.cache_fingerprint()
    else:
        assert KEY not in fake.job.result
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**kwargs)
    assert len(requests) == 1
    assert "private-source" not in caplog.text and "private-credential" not in caplog.text
    assert "result" not in AIJobResponse.model_fields
