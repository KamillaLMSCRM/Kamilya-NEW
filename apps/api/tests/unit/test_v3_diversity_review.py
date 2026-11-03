import json
from dataclasses import replace

import pytest

from app.modules.ai.v3.diversity_review import review_final_lesson
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.models import V3Lesson, V3Option, V3Question
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_primary_source_manifest import sample


def setup():
    corpus, rule = sample()
    q = V3Question("q", "Scenario", "Warranty?", (V3Option("24", True), V3Option("18", False)),
                   "24", "r1", rule.source_quote)
    lesson = V3Lesson("l", "", "", "", ("r1",), questions=(q, replace(q, question_id="q2")))
    journal = Journal()
    journal.tenant_id = "tenant"
    args = {"lesson": lesson, "corpus": corpus, "rules": (rule,), "expected_tenant_id": "tenant",
            "expected_document_ids": ("d1",), "journal": journal, "group_id": "diversity:g",
            "source_sha256": "a" * 64, "route_fingerprint": "b" * 64}
    return args


@pytest.mark.asyncio
@pytest.mark.parametrize("overlaps", [[[1, 2]], []])
async def test_duplicate_and_distinct_observations_replay(overlaps):
    args = setup()
    calls = []
    async def invoke(messages):
        calls.append(1)
        payload = json.loads(messages[1]["content"])
        return {"fingerprint": payload["fingerprint"], "status": "observed", "overlaps": overlaps, "omissions": []}
    first = await review_final_lesson(**args, invoke=invoke)
    assert first["overlaps"] == overlaps and first["inventory_completeness"] == "unknown"
    assert first["status"] == "review_required"
    assert await review_final_lesson(**args, invoke=invoke) == first
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_malformed_and_stale_response_never_grants_review():
    args = setup()
    async def invoke(messages):
        return {"fingerprint": "stale", "status": "observed", "overlaps": [[1, 1]], "omissions": []}
    assert (await review_final_lesson(**args, invoke=invoke))["status"] == "unknown"


@pytest.mark.asyncio
async def test_missing_source_fails_before_invocation_and_edit_changes_fingerprint():
    args = setup()
    calls = []
    async def invoke(messages):
        calls.append(1)
        data = json.loads(messages[1]["content"])
        return {"fingerprint": data["fingerprint"], "status": "observed", "overlaps": [], "omissions": []}
    assert (await review_final_lesson(**(args | {"expected_document_ids": ("wrong",)}), invoke=invoke))["status"] == "unknown"
    assert not calls
    first = await review_final_lesson(**args, invoke=invoke)
    lesson = args["lesson"]
    changed = replace(lesson, questions=(replace(lesson.questions[0], prompt="Changed"), lesson.questions[1]))
    second = await review_final_lesson(**(args | {"lesson": changed}), invoke=invoke)
    assert first["fingerprint"] != second["fingerprint"] and len(calls) == 2


@pytest.mark.asyncio
async def test_unknown_owned_outcome_is_not_reissued():
    args = setup()
    calls = []
    async def invoke(messages):
        calls.append(1)
        raise TimeoutError("outcome unknown")
    with pytest.raises(TimeoutError):
        await review_final_lesson(**args, invoke=invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await review_final_lesson(**args, invoke=invoke)
    assert len(calls) == 1
