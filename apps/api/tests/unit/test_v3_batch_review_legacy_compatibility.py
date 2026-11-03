"""Frozen compatibility boundary for the pre-v2 batched review transport."""

import hashlib
import json

import pytest

from app.modules.ai.v3.batch_review_response_schema import batch_review_response_format
from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.revision_policy import (
    KEY,
    LEGACY_POLICY,
    LEGACY_REVIEW_POLICY,
    POLICY,
    REVIEW_KEY,
    REVIEW_POLICY,
    read_policy,
    read_review_policy,
    stamp_policy,
)

# Derived offline from the immutable 20fa1df89 source implementation using
# these exact synthetic blind/keyed items.  The v1 wire format was JSON object.
LEGACY_BLIND_REQUEST_SHA = "540434bb2f24cf943923773e77113a08d747f9c37c88320989ad2d08977e9cd7"
LEGACY_KEYED_REQUEST_SHA = "38ed50e51dec074b046582896c79bda0a63ba18adc0871bc0e0afb152a938149"
LEGACY_FORMAT_SHA = "376bde7986cc2f8fd182f04e745c607933760bea7c306ea6e8e992b7f70be25a"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def old_items():
    return [
        ("review_question_options", ("s", "q", ["yes", "no"], ["source"]), {}),
        ("review_answer_completeness", ("s", "q", "SECRET_ANSWER", ["source"]),
         {"explanation": "SECRET_EXPLANATION", "options": ["yes", "no"]}),
    ]


def old_response(messages):
    payload = json.loads(messages[1]["content"])
    return {"items": [{"id": item["id"], "review": (
        {"options": []} if item["method"].startswith("review_question")
        else {"answers": [], "explanation_review": {}}
    )} for item in payload["items"]]}


@pytest.mark.asyncio
async def test_legacy_prime_replays_frozen_v1_requests_and_wire_format():
    captured = []

    async def invoke(messages, response_format):
        captured.append((messages, response_format))
        return old_response(messages)

    await BatchedReview.prime(old_items(), invoke, typed_transport=False, strict_contract=False)
    assert [digest({"messages": messages, "format": response_format}) for messages, response_format in captured] == [
        LEGACY_BLIND_REQUEST_SHA, LEGACY_KEYED_REQUEST_SHA,
    ]
    assert all(response_format == {"type": "json_object"} for _, response_format in captured)
    assert digest(captured[0][1]) == LEGACY_FORMAT_SHA
    assert digest(captured[1][1]) == LEGACY_FORMAT_SHA
    assert captured[0][1] != batch_review_response_format()


@pytest.mark.asyncio
async def test_legacy_accepts_old_verdict_only_lesson_but_v2_rejects_it():
    class Lesson:
        cases = ()

        def to_dict(self):
            return {"content": "synthetic lesson", "cases": [], "questions": []}

    item = [("review_lesson", (Lesson(), [], ["source"]), {})]

    async def keyed_old_invoke(messages, _format):
        payload = json.loads(messages[1]["content"])
        return {"items": [{"id": payload["items"][0]["id"], "review": {"verdict": "PASS"}}]}

    # The first call needs the generated item id; return it from the request.
    legacy = await BatchedReview.prime(item, keyed_old_invoke,
                                       typed_transport=False, strict_contract=False)
    proxy = legacy.wrap(V3GenerationPipeline(lambda *_args: {}, scoped_revision=True,
                                              explanation_consistency=True))
    assert (await proxy.review_lesson(item[0][1][0], [], ["source"]))["verdict"] == "PASS"

    with pytest.raises(ValueError, match="batch_output_invalid"):
        await BatchedReview.prime(item, keyed_old_invoke)


def test_revision_markers_accept_legacy_and_stamp_v2():
    stamped = stamp_policy({"source": "synthetic"})
    assert stamped[KEY] == POLICY
    assert stamped[REVIEW_KEY] == REVIEW_POLICY
    assert read_policy({KEY: LEGACY_POLICY}) == LEGACY_POLICY
    assert read_policy({KEY: POLICY}) == POLICY
    assert read_review_policy({REVIEW_KEY: LEGACY_REVIEW_POLICY}) == LEGACY_REVIEW_POLICY
    assert read_review_policy({REVIEW_KEY: REVIEW_POLICY}) == REVIEW_POLICY
    with pytest.raises(ValueError, match="v3_revision_policy_invalid"):
        read_policy({KEY: "v3-scoped-revision-drift"})
    with pytest.raises(ValueError, match="v3_review_policy_invalid"):
        read_review_policy({REVIEW_KEY: "v3-batched-decision-review-drift"})
