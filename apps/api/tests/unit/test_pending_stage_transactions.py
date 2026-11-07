import asyncio
import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import (
    KEY,
    checked_entries,
    claim_with_pending,
    finalize_pending,
    has_pending,
    pending_sql_predicate,
)
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.qa_journal_test_support import Journal


class TxJournal(Journal):
    def __init__(self):
        super().__init__()
        self.job = SimpleNamespace(user_id="actor", status="running", result={"other": 1},
                                   params={"source_analysis": {"generation_engine": "evidence_v3"}})
        self.fail_ack = False
    def sessions(self):
        journal = self
        class Session:
            async def __aenter__(self):
                self.snapshot = (deepcopy(journal.plans), deepcopy(journal.values), deepcopy(journal.job.result))
                self.committed = False
                return self
            async def scalar(self, statement):
                return journal.job
            async def commit(self):
                self.committed = True
                if journal.fail_ack:
                    raise TimeoutError("lost ack")
            async def __aexit__(self, *_args):
                if not self.committed:
                    journal.plans, journal.values, journal.job.result = self.snapshot
                if journal.lock.locked():
                    journal.lock.release()
        return Session()


def args(journal, name="a"):
    plan = {"tenant_id": journal.tenant_id, "job_id": journal.job_id, "stage": name}
    digest = _digest(plan)
    def validate(value):
        assert value["identity"] == digest
        return value["response"]
    return dict(journal=journal, user_id="actor", plan=plan, result_key="result-" + name,
                claim_key="claim-" + name, marker={"identity": digest, "claim_token": "a" * 32}, validate=validate)


def test_presence_including_null_and_malformed():
    assert has_pending({KEY: None}) and has_pending({KEY: {}}) and not has_pending({})
    for value in (None, {}, {"policy": "wrong", "entries": {}}, {"policy": "v3-pending-stages-v1", "entries": {}}):
        with pytest.raises(ValueError):
            checked_entries({KEY: value})


@pytest.mark.asyncio
async def test_concurrent_claim_one_winner_and_process_kill_holds():
    journal = TxJournal()
    results = await asyncio.gather(claim_with_pending(**args(journal)), claim_with_pending(**args(journal)),
                                   return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ExtractionOutcomeUnknownError) for result in results) == 1
    assert has_pending(journal.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await claim_with_pending(**args(journal))


@pytest.mark.asyncio
async def test_multistage_finalize_clears_only_matching_marker():
    journal = TxJournal()
    one, two = args(journal, "a"), args(journal, "b")
    await claim_with_pending(**one)
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_pending_existing"):
        await claim_with_pending(**two)
    value = {"identity": _digest(one["plan"]), "response": {"ok": True}}
    assert await finalize_pending(**one, value=value) == {"ok": True}
    assert not has_pending(journal.job.result) and journal.job.result["other"] == 1
    await claim_with_pending(**two)
    value = {"identity": _digest(two["plan"]), "response": {"ok": True}}
    await finalize_pending(**two, value=value)
    assert not has_pending(journal.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("output_cap", [8192, 16384])
async def test_retained_replay_audit_is_atomic_and_bound_to_original_marker(output_cap):
    from app.modules.ai.v3.managed_rejection_quarantine import KEY as QUARANTINE_KEY
    from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY
    journal = TxJournal()
    options = args(journal)
    options["plan"].update({"stage": "lesson", "group_id": f"practical:author:editorial:v31:output={output_cap}", "route_fingerprint": "e" * 64})
    digest = _digest(options["plan"])
    options["marker"]["identity"] = digest
    options["validate"] = lambda value: value["response"] if value["identity"] == digest else pytest.fail("wrong identity")
    await claim_with_pending(**options)
    receipt = {"body_sha256": "a" * 64, "wire_request_sha256": "b" * 64, "route_fingerprint": "e" * 64}
    journal.job.result[QUARANTINE_KEY] = {"entries": {digest: receipt}}
    journal.job.params[AUTHORIZATION_KEY] = {"policy": AUTHORIZATION_POLICY, "stage": digest,
        "body_sha256": receipt["body_sha256"], "pending_sha256": _digest(journal.job.result[KEY]), "delivery_id": None}
    audit = {"policy": AUTHORIZATION_POLICY, "stage_sha256": digest, "body_sha256": receipt["body_sha256"],
             "wire_request_sha256": receipt["wire_request_sha256"], "model": "gpt-6-luna"}
    value = {"identity": digest, "response": {"ok": True}}
    before = deepcopy(journal.job.result)
    for changed in ({**audit, "stage_sha256": "c" * 64}, {**audit, "body_sha256": "d" * 64},
                    {**audit, "extra": "not allowed"}):
        with pytest.raises(ExtractionOutcomeUnknownError):
            await finalize_pending(**options, value=value, replay_audit=changed)
        assert journal.job.result == before
    assert await finalize_pending(**options, value=value, replay_audit=audit) == {"ok": True}
    assert not has_pending(journal.job.result)
    assert journal.job.result[QUARANTINE_KEY]["entries"][digest] == receipt
    assert journal.job.result["v3_retained_author_replay_audit"] == audit
    with pytest.raises(ExtractionOutcomeUnknownError):
        await finalize_pending(**options, value=value, replay_audit=audit)
    assert journal.job.result["v3_retained_author_replay_audit"] == audit


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["practical:author:editorial:v31", "practical:review:editorial:v31:output=16384",
                                    "practical:author:editorial:v31:output=016384", "practical:author:editorial:v31:output=32768"])
async def test_retained_audit_rejects_foreign_or_malformed_group(group):
    from app.modules.ai.v3.managed_rejection_quarantine import KEY as QUARANTINE_KEY
    from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY
    journal = TxJournal()
    options = args(journal)
    options["plan"].update({"stage": "lesson", "group_id": group, "route_fingerprint": "e" * 64})
    digest = _digest(options["plan"])
    options["marker"]["identity"] = digest
    options["validate"] = lambda value: value["response"]
    await claim_with_pending(**options)
    receipt = {"body_sha256": "a" * 64, "wire_request_sha256": "b" * 64, "route_fingerprint": "e" * 64}
    journal.job.result[QUARANTINE_KEY] = {"entries": {digest: receipt}}
    journal.job.params[AUTHORIZATION_KEY] = {"policy": AUTHORIZATION_POLICY, "stage": digest,
        "body_sha256": receipt["body_sha256"], "pending_sha256": _digest(journal.job.result[KEY]), "delivery_id": None}
    audit = {"policy": AUTHORIZATION_POLICY, "stage_sha256": digest, "body_sha256": receipt["body_sha256"],
             "wire_request_sha256": receipt["wire_request_sha256"], "model": "gpt-6-luna"}
    before = deepcopy(journal.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await finalize_pending(**options, value={"identity": digest, "response": {}}, replay_audit=audit)
    assert journal.job.result == before and has_pending(journal.job.result)


@pytest.mark.asyncio
async def test_lost_ack_and_bad_marker_stay_held():
    journal = TxJournal()
    journal.fail_ack = True
    with pytest.raises(ExtractionOutcomeUnknownError):
        await claim_with_pending(**args(journal))
    assert has_pending(journal.job.result)
    journal.fail_ack = False
    changed = args(journal) | {"marker": {"identity": _digest(args(journal)["plan"]), "claim_token": "b" * 32}}
    with pytest.raises(ExtractionOutcomeUnknownError):
        await finalize_pending(**changed, value={"identity": _digest(changed["plan"]), "response": {"ok": True}})
    assert has_pending(journal.job.result)


@pytest.mark.asyncio
async def test_present_null_blocks_new_claim_and_preserves_unrelated():
    journal = TxJournal()
    journal.job.result = {"other": 1, KEY: None}
    with pytest.raises(ExtractionOutcomeUnknownError) as error:
        await claim_with_pending(**args(journal))
    assert isinstance(error.value.__cause__, ValueError)
    assert journal.job.result == {"other": 1, KEY: None} and not journal.plans


def test_sql_presence_uses_jsonb_key_operator():
    from sqlalchemy.dialects import postgresql
    text = str(pending_sql_predicate().compile(dialect=postgresql.dialect()))
    assert " ? " in text and "coalesce" in text.lower() and "false" in text.lower()


@pytest.mark.asyncio
async def test_finalize_lost_ack_never_falsely_claims_failure(caplog):
    journal = TxJournal()
    options = args(journal)
    await claim_with_pending(**options)
    journal.fail_ack = True
    value = {"identity": _digest(options["plan"]), "response": {"ok": True}}
    with caplog.at_level(logging.INFO, logger="app.modules.ai.v3.pending_stage_transactions"):
        with pytest.raises(ExtractionOutcomeUnknownError) as error:
            await finalize_pending(**options, value=value)
    assert isinstance(error.value.__cause__, TimeoutError)
    assert journal.values[options["result_key"]] == value
    assert not has_pending(journal.job.result)
    assert f"v3_finalize job=unknown stage={_digest(options['plan'])} phase=persistence_or_commit outcome=unknown" in caplog.text
    assert "lost ack" not in caplog.text and "response" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["source_first_commit_intent", "source_first_partitioned_commit_intent"])
async def test_any_source_first_intent_key_blocks_claim(key):
    journal = TxJournal()
    journal.job.result[key] = None
    with pytest.raises(ExtractionOutcomeUnknownError, match="source_first_intent"):
        await claim_with_pending(**args(journal))
    assert journal.job.result[key] is None and not journal.plans


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", [None, "evidence_v2", "source_first_qa_v1", "source_first_partitioned_v2"])
async def test_foreign_or_missing_engine_blocks_claim(engine):
    journal = TxJournal()
    journal.job.params = {"source_analysis": {"generation_engine": engine}}
    with pytest.raises(ExtractionOutcomeUnknownError, match="engine_invalid"):
        await claim_with_pending(**args(journal))
    assert not journal.plans



@pytest.mark.asyncio
async def test_source_hook_rechecks_under_claim_lock_and_denial_prevents_claim():
    journal = TxJournal()
    async def reject(session, job, plan):
        assert journal.lock.locked() and job is journal.job and plan == args(journal)["plan"]
        return False
    with pytest.raises(ExtractionOutcomeUnknownError, match="source_unverified"):
        await claim_with_pending(**args(journal), verify_source=reject)
    assert not journal.plans and not journal.values and not has_pending(journal.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, ValueError("synthetic-private"), asyncio.CancelledError("synthetic-private")])
async def test_legacy_claim_and_source_failure_are_held_without_leak(failure):
    import traceback
    journal = TxJournal()
    options = args(journal)
    journal.plans[options["claim_key"]] = options["plan"]
    async def verify(_session, _job, _plan):
        if isinstance(failure, BaseException):
            raise failure
        return failure
    with pytest.raises(ExtractionOutcomeUnknownError, match="source_unverified") as error:
        await claim_with_pending(**options, verify_source=verify)
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert "synthetic-private" not in "".join(traceback.format_exception(error.value))
    assert options["claim_key"] in journal.plans and not journal.values


@pytest.mark.asyncio
async def test_concurrent_distinct_digests_do_not_create_two_claims():
    journal = TxJournal()
    first, second = args(journal, "route-a"), args(journal, "route-b")
    outcomes = await asyncio.gather(claim_with_pending(**first), claim_with_pending(**second), return_exceptions=True)
    assert sum(item is None for item in outcomes) == 1
    assert sum(isinstance(item, ExtractionOutcomeUnknownError) for item in outcomes) == 1
    assert len(checked_entries(journal.job.result)) == 1


@pytest.mark.asyncio
async def test_existing_pending_fences_other_stage_before_callbacks():
    journal = TxJournal()
    await claim_with_pending(**args(journal, "first"))
    prior = deepcopy(journal.job.result)
    calls = []
    async def verify(*_args):
        calls.append(1)
        return True
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_pending_existing"):
        await claim_with_pending(**args(journal, "changed-prompt"), verify_source=verify)
    assert not calls and journal.job.result == prior
