"""Integration contract for the typed, method-bucketed review transport."""

import json
from copy import deepcopy

import pytest

from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.response_contracts import response_contract, response_contract_hash
from app.modules.ai.v3.typed_review_buckets import BUCKETS, build_typed_review_format


def claim():
    return {"claim": "synthetic claim", "status": "SUPPORTED", "reason": "synthetic reason"}


def lesson_review():
    return {"verdict": "PASS", "factual_score": 4, "alignment_score": 4,
            "didactic_score": 4, "summary": "synthetic lesson", "defects": []}


def answer_review():
    return {"verdict": "SUPPORTED", "claims": [claim()], "summary": "synthetic answer"}


def option_review():
    return {"options": [{"index": 0, "verdict": "SUPPORTED",
                          "omitted_required_elements": [], "claims": [claim()],
                          "summary": "synthetic option"}]}


def completeness_review():
    return {"answers": [{"index": 0, "omissions": []}], "explanation_review": answer_review()}


def review_for(method):
    return {
        "review_lesson": lesson_review,
        "review_answer": answer_review,
        "review_question_options": option_review,
        "review_question_compatibility": option_review,
        "review_answer_completeness": completeness_review,
    }[method]()


class Lesson:
    cases = ()

    def to_dict(self):
        return {"content": "synthetic lesson", "cases": [], "questions": []}


def work_items(options=None):
    options = options or ["yes", "no"]
    return [
        ("review_lesson", (Lesson(), [], ["lesson source"]), {}),
        ("review_answer", ("scenario", "question", "answer", ["answer source"]), {"source_prose": True}),
        ("review_question_options", ("scenario", "question", options, ["option source"]), {}),
        ("review_question_compatibility", ("scenario", "question", options, ["compat source"]), {}),
        ("review_answer_completeness", ("scenario", "question", "answer", ["complete source"]),
         {"explanation": "explanation", "options": options}),
    ]


def bucket_response(payload, *, mutate=None):
    methods_by_bucket = {bucket: method for method, bucket in BUCKETS.items()}
    response = {
        bucket: [{"id": item_id, "review": review_for(methods_by_bucket[bucket])}
                 for item_id in ids]
        for bucket, ids in payload["output_buckets"].items()
    }
    if mutate is not None:
        mutate(response, methods_by_bucket)
    return response


@pytest.mark.asyncio
async def test_typed_buckets_are_two_calls_exactly_bound_and_cached():
    calls = []

    async def invoke(messages, response_format):
        payload = json.loads(messages[1]["content"])
        calls.append((payload, response_format))
        return bucket_response(payload)

    items = work_items()
    cache = await BatchedReview.prime(items, invoke, typed_buckets=True)
    assert len(calls) == 2
    assert all(set(payload["output_buckets"]) == set(BUCKETS.values()) for payload, _ in calls)
    assert all(sum(len(payload["output_buckets"][bucket]) for payload, _ in calls) == 1
               for bucket in BUCKETS.values())
    assert "SECRET_ANSWER" not in json.dumps(calls)
    assert all(response_contract(fmt) == "batch_review_buckets" for _, fmt in calls)
    assert all(response_contract_hash(fmt) for _, fmt in calls)

    fallback_calls = []
    async def fallback(messages, response_format):
        fallback_calls.append((messages, response_format))
        return {"fallback": True}

    proxy = cache.wrap(V3GenerationPipeline(fallback, scoped_revision=True, explanation_consistency=True))
    for method, args, kwargs in items:
        assert await getattr(proxy, method)(*args, **kwargs) == review_for(method)
    assert not fallback_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["swap", "foreign", "duplicate", "missing"])
async def test_typed_bucket_id_and_method_shape_mismatches_fail_closed(mutation):
    items = work_items()

    async def invoke(messages, _response_format):
        payload = json.loads(messages[1]["content"])

        def mutate(response, _methods):
            if mutation == "swap":
                if response["answer_reviews"]:
                    response["answer_reviews"][0]["review"] = lesson_review()
            elif mutation == "foreign":
                if response["lesson_reviews"]:
                    response["lesson_reviews"][0]["id"] = "f" * 64
            elif mutation == "duplicate":
                if response["lesson_reviews"]:
                    response["lesson_reviews"].append(deepcopy(response["lesson_reviews"][0]))
            elif mutation == "missing":
                if response["lesson_reviews"]:
                    response["lesson_reviews"] = []

        return bucket_response(payload, mutate=mutate)

    with pytest.raises(ValueError):
        await BatchedReview.prime(items, invoke, typed_buckets=True)


@pytest.mark.asyncio
async def test_typed_buckets_keep_strict_validation_with_json_object_transport():
    formats = []
    expected_formats = []

    async def invoke(messages, response_format):
        formats.append(response_format)
        payload = json.loads(messages[1]["content"])
        expected_formats.append(build_typed_review_format(
            {method: payload["output_buckets"][bucket] for method, bucket in BUCKETS.items()}))
        return bucket_response(payload)

    cache = await BatchedReview.prime(work_items(), invoke, typed_transport=False, typed_buckets=True)
    assert len(formats) == 2 and formats == expected_formats
    assert all(response_contract(response_format) == "batch_review_buckets" for response_format in formats)
    assert cache is not None


@pytest.mark.asyncio
async def test_option_order_or_text_changes_bound_ids_and_schema_hash():
    async def capture(items):
        seen = []

        async def invoke(messages, response_format):
            payload = json.loads(messages[1]["content"])
            seen.append((payload, response_format))
            return bucket_response(payload)

        await BatchedReview.prime(items, invoke, typed_buckets=True)
        return seen[0][0]["output_buckets"]["option_reviews"], response_contract_hash(seen[0][1])

    first_ids, first_schema = await capture([work_items(["yes", "no"])[2]])
    reversed_ids, reversed_schema = await capture([work_items(["no", "yes"])[2]])
    changed_ids, changed_schema = await capture([work_items(["yes", "maybe"])[2]])
    assert first_ids != reversed_ids and first_ids != changed_ids
    assert first_schema != reversed_schema and first_schema != changed_schema
