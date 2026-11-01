from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError, PlannedLesson
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_stage_inspection import inspect_owned_stage
from app.modules.ai.v3.stage_checkpoint import _digest
from app.modules.ai.worker_lesson_cycle import PLAN_POLICY, POLICY_VERSION
from tests.unit.test_pending_stage_transactions import TxJournal, args


def setup_journal():
    journal = TxJournal()
    async def load(_session, *, tenant_id, generation_key):
        if generation_key not in journal.plans:
            raise AIGenerationCheckpointError("generation_plan_not_found")
        return SimpleNamespace(source_job_id=journal.job_id, plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                               plan_payload=journal.plans[generation_key], lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
    journal.load_plan = load
    return journal


def inspect_args(journal):
    values = args(journal)
    async def verify_source(_session, _job, _plan):
        return True
    return {key: values[key] for key in ("journal", "user_id", "plan", "result_key", "claim_key", "validate")} | {"verify_source": verify_source}


@pytest.mark.asyncio
async def test_fresh_and_legacy_completed_are_read_only():
    journal = setup_journal()
    options = inspect_args(journal)
    assert (await inspect_owned_stage(**options)).decision == "needs_count"
    assert not journal.plans and not journal.values
    journal.plans[options["result_key"]] = options["plan"]
    journal.values[options["result_key"]] = {"identity": _digest(options["plan"]), "response": {"secret": "x"}}
    before = (deepcopy(journal.plans), deepcopy(journal.values), deepcopy(journal.job.result))
    result = await inspect_owned_stage(**options)
    assert result.decision == "replay" and result.result == {"secret": "x"} and "secret" not in repr(result)
    assert before == (journal.plans, journal.values, journal.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["null", "legacy_claim", "plan_drift", "foreign_user"])
async def test_unverified_states_hold_without_writes(variant):
    journal = setup_journal()
    options = inspect_args(journal)
    if variant == "null":
        journal.job.result["v3_pending_stages"] = None
    if variant == "legacy_claim":
        journal.plans[options["claim_key"]] = options["plan"]
    if variant == "plan_drift":
        journal.plans[options["result_key"]] = {**options["plan"], "stage": "foreign"}
    if variant == "foreign_user":
        options["user_id"] = "foreign"
    before = (deepcopy(journal.plans), deepcopy(journal.values), deepcopy(journal.job.result))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await inspect_owned_stage(**options)
    assert before == (journal.plans, journal.values, journal.job.result)


@pytest.mark.asyncio
async def test_unverified_source_fails_before_decision():
    journal = setup_journal()
    options = inspect_args(journal)
    async def deny(_session, _job, _plan):
        return False
    options["verify_source"] = deny
    with pytest.raises(ExtractionOutcomeUnknownError):
        await inspect_owned_stage(**options)
    assert not journal.plans and not journal.values


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["source", "validator", "plan"])
async def test_inspection_sanitizes_untrusted_exception_details(site):
    import traceback

    journal = setup_journal()
    options = inspect_args(journal)
    if site == "source":
        async def fail(_session, _job, _plan):
            raise ValueError("synthetic-private")
        options["verify_source"] = fail
    elif site == "validator":
        journal.plans[options["result_key"]] = options["plan"]
        journal.values[options["result_key"]] = {"identity": _digest(options["plan"]), "response": {}}
        def fail(_value):
            raise ValueError("synthetic-private")
        options["validate"] = fail
    else:
        options["plan"] = None
    with pytest.raises(ExtractionOutcomeUnknownError) as error:
        await inspect_owned_stage(**options)
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert "synthetic-private" not in "".join(traceback.format_exception(error.value))


@pytest.mark.asyncio
async def test_pending_other_digest_cannot_be_inspected_as_fresh():
    journal = setup_journal()
    options = inspect_args(journal)
    journal.job.result["v3_pending_stages"] = {"policy": "v3-pending-stages-v1", "entries": {
        "a" * 64: {"claim_key": "claim-other", "result_key": "result-other", "token": "b" * 32}}}
    with pytest.raises(ExtractionOutcomeUnknownError):
        await inspect_owned_stage(**options)
    assert not journal.plans and not journal.values
