"""Behavioral replay and unknown-outcome tests for lesson/review stages."""

import pytest

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_v3_partitioned_extraction import Journal


def args(journal):
    return {"journal": journal, "stage": "lesson", "group_id": "g1", "source_sha256": "a" * 64,
            "route_fingerprint": "b" * 64, "messages": [{"role": "user", "content": "A"}],
            "response_format": {"type": "json_object"}}


@pytest.mark.asyncio
async def test_replay_and_changed_prompt_are_separate_requests():
    journal = Journal()
    calls = []

    async def invoke():
        calls.append(1)
        return {"title": "Урок", "content": "Текст"}

    first = await stage_once(**args(journal), invoke=invoke)
    assert await stage_once(**args(journal), invoke=invoke) == first
    assert len(calls) == 1
    changed = args(journal) | {"messages": [{"role": "user", "content": "B"}]}
    await stage_once(**changed, invoke=invoke)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unknown_stage_outcome_is_never_implicitly_reissued():
    journal = Journal()
    calls = []

    async def timeout():
        calls.append(1)
        raise TimeoutError("outcome unknown")

    with pytest.raises(TimeoutError):
        await stage_once(**args(journal), invoke=timeout)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args(journal), invoke=timeout)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_saved_stage_result_detects_tampering():
    journal = Journal()

    async def invoke():
        return {"title": "original"}

    await stage_once(**args(journal), invoke=invoke)
    key = next(k for k in journal.values if k.startswith("v3-stage-result:"))
    journal.values[key]["response"]["title"] = "changed"
    with pytest.raises(ValueError, match="checkpoint_invalid"):
        await stage_once(**args(journal), invoke=invoke)
