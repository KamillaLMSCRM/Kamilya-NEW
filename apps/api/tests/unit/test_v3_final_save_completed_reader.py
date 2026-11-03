"""Guarded fake-session checks; not proof of database locking or storage."""
import socket
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai.lesson_cycle import POLICY_VERSION
from app.modules.ai.source_assessment_plan import PLAN_POLICY
from app.modules.ai.v3.final_save_completed_reader import completed_receipt, read_completed_snapshot
from app.modules.ai.v3.final_save_contract import RECEIPT_KEY
from app.modules.ai.v3.final_save_snapshot import make_snapshot
from tests.unit.test_v3_final_save_readback import fixture


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "Client", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Session:
    def __init__(self, scalars, rows):
        self.scalar_values = iter(scalars)
        self.row_values = iter(rows)

    async def execute(self, *_args, **_kwargs):
        return None

    async def scalar(self, *_args, **_kwargs):
        statement = _args[0]
        if "ai_jobs" in str(statement):
            parameters = statement.compile().params
            assert isinstance(parameters["id_1"], str)
        return next(self.scalar_values)

    async def scalars(self, *_args, **_kwargs):
        return Rows(next(self.row_values))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "foreign_owner", "snapshot_tamper", "wrong_receipt", "missing_row",
                                   "source_drift", "checkpoint_incomplete", "source_revision", "extra_choice",
                                   "foreign_course", "run_plan_drift"])
async def test_completed_reader_rejects_tampering_and_foreign_owner(monkeypatch, case):
    from app.modules.ai.v3 import final_save_completed_reader as module

    data = fixture()
    intent, job, course = data["intent"], data["job"], data["course"]
    snapshot = make_snapshot(data["state"], intent)
    receipt = completed_receipt(intent, snapshot, str(course.id))
    job.result[RECEIPT_KEY] = receipt
    if case == "snapshot_tamper":
        snapshot["output"]["content"]["title"] = "changed"
    if case == "wrong_receipt":
        receipt["snapshot_digest"] = "0" * 64
    run = SimpleNamespace(id=uuid4(), plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                          plan_payload={"schema": "v3-final-snapshot-v1", "intent_digest": intent["intent_digest"]})
    if case == "run_plan_drift":
        run.plan_payload["intent_digest"] = "0" * 64
    if case == "foreign_course":
        course.tenant_id = uuid4()
    if case == "source_revision":
        data["documents"][0].content_sha256 = "0" * 64
    checkpoint = SimpleNamespace(module_key="cycle", lesson_key="lesson", assessment_status="completed",
                                 assessment_payload=snapshot)
    if case == "checkpoint_incomplete":
        checkpoint.assessment_status = "pending"
    async def source(*_args, **_kwargs):
        if case == "source_drift":
            doc = replace(data["source_corpus"].documents[0], source_text="changed")
            return replace(data["source_corpus"], documents=(doc,))
        return data["source_corpus"]
    monkeypatch.setattr(module, "build_direct_source_corpus", source)
    rows = [[checkpoint], data["documents"], data["modules"], data["lessons"], data["quizzes"],
            data["questions"], [] if case == "missing_row" else data["choices"]]
    if case == "extra_choice":
        rows[-1] = [*data["choices"], SimpleNamespace(id=uuid4())]
    session = Session([None if case == "foreign_owner" else job, run, course], rows)
    result = await read_completed_snapshot(session, tenant_id=UUID(intent["tenant_id"]),
                                           actor_id=UUID(intent["user_id"]), job_id=UUID(intent["job_id"]))
    assert result is (case == "valid")
