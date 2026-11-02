"""Pure transitions and fake lock/commit semantics; no live database."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from app.modules.ai.v3.final_save_contract import (
    INTENT_KEY,
    PENDING_KEY,
    RECEIPT_KEY,
    FinalSaveContractError,
    install_intent,
    make_intent,
    resolve_intent,
)
from app.modules.ai.v3.pending_stage_transactions import has_pending


def intent():
    return make_intent(tenant_id=str(uuid4()), user_id=str(uuid4()), job_id=str(uuid4()), delivery_id="delivery",
        route_policy="qa-direct-luna-diversity-v3", route_fingerprint="a" * 64,
        documents=[{"doc_id": str(uuid4()), "revision": "document:" + "b" * 64, "text_sha256": "c" * 64}],
        output_digest="d" * 64)


def test_intent_fences_all_existing_pending_checks_and_receipt_retains_other_result():
    value = intent()
    saved = install_intent({"resume_count": 2}, value)
    assert has_pending(saved) and saved[INTENT_KEY] == value
    done = resolve_intent(saved, value, course_id=str(uuid4()), output_digest="d" * 64)
    assert not has_pending(done) and done["resume_count"] == 2
    assert done[RECEIPT_KEY]["intent_digest"] == value["intent_digest"]


@pytest.mark.parametrize("existing", [{PENDING_KEY: None}, {PENDING_KEY: {}}, {INTENT_KEY: None},
                                       {RECEIPT_KEY: None}, {"source_first_commit_intent": None},
                                       {"source_first_partitioned_commit_intent": None}, [], "bad"])
def test_existing_holds_or_corruption_are_never_overwritten(existing):
    before = deepcopy(existing)
    with pytest.raises(FinalSaveContractError):
        install_intent(existing, intent())
    assert existing == before


@pytest.mark.parametrize("tamper", ["intent", "fence", "output", "foreign_intent"])
def test_resolve_rejects_foreign_or_changed_state(tamper):
    i = intent()
    saved = install_intent({}, i)
    before = deepcopy(saved)
    if tamper == "intent":
        saved[INTENT_KEY]["delivery_id"] = "foreign"
    if tamper == "fence":
        saved[PENDING_KEY] = None
    if tamper == "foreign_intent":
        saved["source_first_commit_intent"] = None
    with pytest.raises(FinalSaveContractError):
        resolve_intent(saved, i, course_id=str(uuid4()), output_digest=("e" * 64 if tamper == "output" else "d" * 64))
    assert has_pending(saved)
    assert PENDING_KEY in before


class FakeLockedRow:
    def __init__(self):
        self.result = {}
        self.lock = asyncio.Lock()

    async def prepare(self, value, *, lost_ack=False):
        async with self.lock:
            self.result = install_intent(self.result, value)
            if lost_ack:
                raise TimeoutError("commit acknowledgement unknown")

    async def finish(self, value, course, *, lost_ack=False):
        async with self.lock:
            self.result = resolve_intent(self.result, value, course_id=course, output_digest="d" * 64)
            if lost_ack:
                raise TimeoutError("commit acknowledgement unknown")


@pytest.mark.asyncio
async def test_fake_concurrent_claims_and_lost_ack_never_admit_duplicate():
    row = FakeLockedRow()
    first, second = intent(), intent()
    outcomes = await asyncio.gather(row.prepare(first, lost_ack=True), row.prepare(second), return_exceptions=True)
    assert isinstance(outcomes[0], TimeoutError) and isinstance(outcomes[1], FinalSaveContractError)
    assert has_pending(row.result) and row.result[INTENT_KEY] == first
    with pytest.raises(FinalSaveContractError):
        await row.prepare(first)


@pytest.mark.asyncio
async def test_fake_final_commit_lost_ack_does_not_allow_repeat():
    row, i = FakeLockedRow(), intent()
    await row.prepare(i)
    with pytest.raises(TimeoutError):
        await row.finish(i, str(uuid4()), lost_ack=True)
    assert RECEIPT_KEY in row.result and not has_pending(row.result)
    with pytest.raises(FinalSaveContractError):
        await row.prepare(i)
    with pytest.raises(FinalSaveContractError):
        await row.finish(i, str(uuid4()))


@pytest.mark.asyncio
async def test_fake_cancellation_after_commit_keeps_fence():
    row, i = FakeLockedRow(), intent()
    async def committed_then_cancelled():
        async with row.lock:
            row.result = install_intent(row.result, i)
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await committed_then_cancelled()
    assert has_pending(row.result) and row.result[INTENT_KEY] == i
    with pytest.raises(FinalSaveContractError):
        await row.prepare(i)


@pytest.mark.asyncio
async def test_fake_rollback_before_commit_preserves_existing_row():
    row, i = FakeLockedRow(), intent()
    async with row.lock:
        candidate = install_intent(row.result, i)
        assert has_pending(candidate)
        # Fake rollback drops the candidate and leaves durable row untouched.
    assert row.result == {} and not has_pending(row.result)


def test_output_digest_binds_complete_proposed_projection_and_metadata():
    from app.modules.ai.architect_schema import CourseStructure
    from app.modules.ai.assessment_schema import CourseAssessment
    from app.modules.ai.v3.final_save_contract import output_digest
    from app.modules.ai.writer_schema import CourseContent

    params = dict(structure=CourseStructure(title="course"), content=CourseContent(title="course", description="body"),
                  assessment=CourseAssessment(), source_document_ids=[str(uuid4())], source_strategy="single_topic",
                  source_combination_goal="", source_analysis={"generation_engine": "evidence_v3"},
                  source_review_required=True, reuse_reason=None)
    first = output_digest(**params)
    assert len(first) == 64 and output_digest(**params) == first
    assert output_digest(**(params | {"content": CourseContent(title="course", description="changed")})) != first
    assert output_digest(**(params | {"source_review_required": False})) != first
    with pytest.raises(FinalSaveContractError):
        output_digest(**(params | {"source_analysis": {"invalid": float("nan")}}))


def test_diversity_repair_attempts_survive_intent_and_completion():
    original = {"v3_diversity_repair_attempts": {"group": {"attempt": "retained"}}}
    original_copy = deepcopy(original)
    value = intent()
    held = install_intent(original, value)
    done = resolve_intent(held, value, course_id=str(uuid4()), output_digest="d" * 64)
    assert original == original_copy
    assert held["v3_diversity_repair_attempts"] == original_copy["v3_diversity_repair_attempts"]
    assert done["v3_diversity_repair_attempts"] == original_copy["v3_diversity_repair_attempts"]
