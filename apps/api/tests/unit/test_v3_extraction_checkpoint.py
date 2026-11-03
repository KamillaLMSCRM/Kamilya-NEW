"""Replay, isolation and unknown-outcome contracts for V3 extraction."""

import asyncio

import pytest

from app.modules.ai.v3.extraction_checkpoint import (
    ExtractionOutcomeUnknownError,
    build_extraction_identity,
    extract_once,
)
from app.modules.ai.v3.source_units import SourceUnit


class Journal:
    tenant_id = "tenant-1"
    job_id = "job-1"

    def __init__(self):
        self.plans = {}
        self.values = {}

    async def prepare(self, key, plan):
        if key in self.plans and self.plans[key] != plan:
            raise ValueError("plan conflict")
        self.plans[key] = plan
        return self.values.get(key)

    async def save_value(self, key, value):
        if key in self.values and self.values[key] != value:
            raise ValueError("checkpoint conflict")
        self.values[key] = value

    async def read_owned_value(self, key, plan):
        return self.values.get(key) if self.plans.get(key) == plan else None


def identity(**overrides):
    data = {"tenant_id": "tenant-1", "job_id": "job-1", "document_id": "doc-1",
            "source_revision": "rev-1", "source_sha256": "a" * 64,
            "unit_sha256": "b" * 64, "context_sha256": "c" * 64,
            "prompt_sha256": "d" * 64, "route_fingerprint": "e" * 64,
            "unit_start": "0", "unit_end": "10"}
    return data | overrides


def test_identity_binds_exact_source_span_context_and_actual_messages():
    source = "Первое. Второе."
    unit = SourceUnit(start=8, end=len(source), text="Второе.", kind="prose")
    args = {"tenant_id": "tenant-1", "job_id": "job-1", "document_id": "doc-1",
            "source_revision": "rev-1", "source_text": source, "unit": unit,
            "context": "Первое.", "messages": [{"role": "user", "content": "Второе."}],
            "route_fingerprint": "e" * 64}
    result = build_extraction_identity(**args)
    assert result["unit_start"] == "8" and result["unit_end"] == str(len(source))
    changed = build_extraction_identity(**(args | {"messages": [{"role": "user", "content": "Другое."}]}))
    assert changed["prompt_sha256"] != result["prompt_sha256"]
    with pytest.raises(ValueError, match="source_span"):
        build_extraction_identity(**(args | {"unit": SourceUnit(0, 7, "Второе.", "prose")}))


@pytest.mark.asyncio
async def test_completed_unit_is_reused_without_call_and_source_change_is_not():
    journal = Journal()
    calls = []

    async def invoke():
        calls.append(1)
        return {"rules": [{"rule_id": "r1", "statement": "Действие", "source_quote": "Действие"}]}

    first = await extract_once(journal, identity(), invoke)
    assert await extract_once(journal, identity(), invoke) == first
    assert len(calls) == 1
    await extract_once(journal, identity(unit_sha256="f" * 64), invoke)
    assert len(calls) == 2
    # Identical text at another location is a distinct source occurrence.
    await extract_once(journal, identity(unit_start="20", unit_end="30"), invoke)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_unknown_call_outcome_does_not_silently_retry():
    journal = Journal()
    calls = []

    async def failing():
        calls.append(1)
        raise TimeoutError("provider result unknown")

    with pytest.raises(TimeoutError):
        await extract_once(journal, identity(), failing)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await extract_once(journal, identity(), failing)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_concurrent_claims_do_not_start_two_calls():
    journal = Journal()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def invoke():
        calls.append(1)
        started.set()
        await release.wait()
        return {"rules": [{"rule_id": "r", "statement": "x", "source_quote": "x"}]}

    first = asyncio.create_task(extract_once(journal, identity(), invoke))
    await started.wait()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await extract_once(journal, identity(), invoke)
    release.set()
    await first
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_foreign_job_and_corrupted_checkpoint_fail_closed():
    journal = Journal()

    async def invoke():
        return {"rules": []}

    with pytest.raises(ValueError):
        await extract_once(journal, identity(job_id="other"), invoke)
    await extract_once(journal, identity(), invoke)
    key = next(key for key in journal.values if key.startswith("v3-result:"))
    journal.values[key]["identity"] = "forged"
    with pytest.raises(ValueError):
        await extract_once(journal, identity(), invoke)


@pytest.mark.asyncio
async def test_lost_claim_write_response_never_starts_or_repeats_provider_call():
    class LostAckJournal(Journal):
        async def save_value(self, key, value):
            await super().save_value(key, value)
            if key.startswith("v3-claim:"):
                raise TimeoutError("commit acknowledgement lost")

    journal = LostAckJournal()
    calls = []

    async def invoke():
        calls.append(1)
        return {"rules": []}

    with pytest.raises(TimeoutError):
        await extract_once(journal, identity(), invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await extract_once(journal, identity(), invoke)
    assert not calls


@pytest.mark.asyncio
async def test_cached_result_requires_independent_readback():
    class HiddenReadJournal(Journal):
        hide = False

        async def read_owned_value(self, key, plan):
            if self.hide and key.startswith("v3-result:"):
                return None
            return await super().read_owned_value(key, plan)

    journal = HiddenReadJournal()
    calls = []

    async def invoke():
        calls.append(1)
        return {"rules": []}

    await extract_once(journal, identity(), invoke)
    journal.hide = True
    with pytest.raises(ValueError, match="result_unverified"):
        await extract_once(journal, identity(), invoke)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simultaneous_empty_claim_reads_allow_only_one_compare_and_set():
    class RaceJournal(Journal):
        def __init__(self):
            super().__init__()
            self.claim_readers = 0
            self.both = asyncio.Event()

        async def prepare(self, key, plan):
            value = await super().prepare(key, plan)
            if key.startswith("v3-claim:"):
                self.claim_readers += 1
                if self.claim_readers == 2:
                    self.both.set()
                await self.both.wait()
            return value

    journal = RaceJournal()
    calls = []

    async def invoke():
        calls.append(1)
        return {"rules": []}

    results = await asyncio.gather(
        extract_once(journal, identity(), invoke), extract_once(journal, identity(), invoke),
        return_exceptions=True,
    )
    assert len(calls) == 1
    assert sum(isinstance(item, Exception) for item in results) == 1


@pytest.mark.asyncio
async def test_lost_result_write_response_replays_durable_result_without_call():
    class LostResultAckJournal(Journal):
        async def save_value(self, key, value):
            await super().save_value(key, value)
            if key.startswith("v3-result:"):
                raise TimeoutError("result commit acknowledgement lost")

    journal = LostResultAckJournal()
    calls = []

    async def invoke():
        calls.append(1)
        return {"rules": []}

    with pytest.raises(TimeoutError):
        await extract_once(journal, identity(), invoke)
    assert await extract_once(journal, identity(), invoke) == {"rules": []}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_wrong_rule_field_shape_is_not_saved_as_a_valid_checkpoint():
    journal = Journal()

    async def invoke():
        return {"rules": [{"rule_id": "r", "statement": "x", "source_quote": "x", "conditions": "if x"}]}

    with pytest.raises(ValueError, match="rule_invalid"):
        await extract_once(journal, identity(), invoke)
    assert not any(key.startswith("v3-result:") for key in journal.values)


@pytest.mark.asyncio
async def test_missing_quote_is_retained_for_later_source_review():
    journal = Journal()

    async def invoke():
        return {"rules": [{"rule_id": "r", "statement": "x"}]}

    assert (await extract_once(journal, identity(), invoke))["rules"][0]["statement"] == "x"


@pytest.mark.asyncio
async def test_null_optional_fields_are_preserved_as_unspecified_without_rejection():
    journal = Journal()

    async def invoke():
        return {"rules": [{"rule_id": "r", "statement": "x", "source_quote": "x",
                           "conditions": None, "consequences": None}]}

    response = await extract_once(journal, identity(), invoke)
    assert response["rules"][0]["conditions"] == []
    assert response["rules"][0]["consequences"] == ""
