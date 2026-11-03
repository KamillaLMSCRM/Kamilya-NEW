"""Pending direct-client checkpoint integration for typed review buckets."""

import base64
import hashlib
import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
from app.modules.ai.v3.typed_review_buckets import BUCKETS, build_typed_review_format
from tests.unit.test_direct_luna_owned_stage import setup

ANSWER_ID = "a" * 64


def direct_setup():
    fake, journal, _client, plan, validate = setup()
    job_id = str(uuid4())
    fake.job_id = journal.job_id = job_id
    client = DirectLunaResponsesClient(api_key="synthetic", tenant_id=UUID(journal.tenant_id),
                                       user_id=journal.user_id, job_id=job_id)
    return fake, journal, client, plan, validate


def answer_review():
    return {"verdict": "SUPPORTED", "claims": [{"claim": "answer", "status": "SUPPORTED", "reason": "source"}],
            "summary": "answer review"}


def lesson_review():
    return {"verdict": "PASS", "factual_score": 4, "alignment_score": 4,
            "didactic_score": 4, "summary": "lesson review", "defects": []}


def response_format():
    expected = {method: [] for method in BUCKETS}
    expected["review_answer"] = [ANSWER_ID]
    return build_typed_review_format(expected)


def bucket_response(*, review):
    return {bucket: ([{"id": ANSWER_ID, "review": review}] if bucket == "answer_reviews" else [])
            for bucket in BUCKETS.values()}


def response_body(content):
    return json.dumps({"model": "gpt-6-luna", "status": "completed", "output": [{
        "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": json.dumps(content, separators=(",", ":"))}],
    }], "usage": {"input_tokens": 12, "output_tokens": 6,
                   "input_tokens_details": {"cached_tokens": 1},
                   "output_tokens_details": {"reasoning_tokens": 2}}}, separators=(",", ":")).encode()


def stage_kwargs(journal, client, fmt):
    messages = [{"role": "user", "content": "synthetic bucket review"}]
    return dict(journal=journal, direct_client=client, stage="review", group_id="batched-review:synthetic",
                source_sha256="b" * 64, route_fingerprint=client.cache_fingerprint(), messages=messages,
                response_format=fmt, direct_max_output_tokens=128)


def install_transport(monkeypatch, content, requests):
    raw_generation = response_body(content)

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, stream=httpx.ByteStream(b'{"object":"response.input_tokens","input_tokens":12}'),
                                  headers={"content-type": "application/json", "content-encoding": "identity"})
        return httpx.Response(200, stream=httpx.ByteStream(raw_generation),
                              headers={"content-type": "application/json", "content-encoding": "identity"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        "app.modules.ai.direct_luna_responses_client.httpx.AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    return raw_generation


@pytest.mark.asyncio
async def test_wrong_bucket_shape_holds_pending_and_quarantines_complete_http(monkeypatch):
    fake, journal, client, _plan, _validate = direct_setup()
    fake.job.params["generation_reservation_released"] = False
    fmt = response_format()
    requests = []
    raw_generation = install_transport(monkeypatch, bucket_response(review=lesson_review()), requests)
    assert b"synthetic" not in raw_generation
    options = stage_kwargs(journal, client, fmt)

    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(invoke=lambda: {}, **options)
    assert len(requests) == 2
    assert requests[0].url.path.endswith("input_tokens")
    assert requests[1].url.path.endswith("/responses")
    assert json.loads(requests[0].content)["text"]["format"] == {"type": "json_object"}
    assert json.loads(requests[1].content)["text"]["format"] == {"type": "json_object"}
    assert has_pending(fake.job.result)
    assert "result" not in fake.values

    plan = stage_plan(journal, stage=options["stage"], group_id=options["group_id"],
                      source_sha256=options["source_sha256"], route_fingerprint=options["route_fingerprint"],
                      messages=options["messages"], response_format=fmt)
    stage_sha = _digest(plan)
    quarantine = fake.job.result["v3_managed_response_quarantine"]
    receipt_ref = quarantine["entries"][stage_sha]
    assert receipt_ref["configured_model"] == "gpt-6-luna"
    assert len(receipt_ref["body_sha256"]) == 64 and receipt_ref["wire_request_sha256"]
    private_receipts = [value for value in fake.values.values()
                        if isinstance(value, dict) and value.get("configured_model") == "gpt-6-luna"]
    assert len(private_receipts) == 1
    receipt = private_receipts[0]
    assert base64.b64decode(receipt["raw_base64"]) == raw_generation
    assert receipt["body_sha256"] == hashlib.sha256(raw_generation).hexdigest()
    assert receipt["wire_request_sha256"] == receipt_ref["wire_request_sha256"]

    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(invoke=lambda: {}, **options)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_valid_bucket_shape_accepts_and_cold_replays_without_new_http(monkeypatch):
    fake, journal, client, _plan, _validate = direct_setup()
    fmt = response_format()
    requests = []
    install_transport(monkeypatch, bucket_response(review=answer_review()), requests)
    options = stage_kwargs(journal, client, fmt)

    first = await stage_once(invoke=lambda: {}, **options)
    second = await stage_once(invoke=lambda: {}, **options)
    assert first == second == bucket_response(review=answer_review())
    assert len(requests) == 2
    assert json.loads(requests[0].content)["text"]["format"] == {"type": "json_object"}
    assert json.loads(requests[1].content)["text"]["format"] == {"type": "json_object"}
    assert not has_pending(fake.job.result)
    assert "result" in fake.values or any(isinstance(value, dict) and value.get("response") == first
                                           for value in fake.values.values())
