"""Offline owned observation guard, with hard network denial."""
import hashlib
import socket
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.v3.diversity_owned_selection_guard import build_owned_selection_guard
from app.modules.ai.v3.diversity_repair_selection import select_candidate
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_v3_diversity_repair_selection import setup


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "Client", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)


@pytest.mark.asyncio
async def test_exact_owned_review_is_reloaded_in_claim_session_and_drift_denies():
    args = setup()
    selected = select_candidate(**args)
    assert selected is not None
    corpus, rule, lesson = args["corpus"], args["rules"][0], args["lesson"]
    journal = PendingStageJournal("tenant", uuid4(), "job", object())
    source_hash = hashlib.sha256(corpus.documents[0].source_text.encode()).hexdigest()
    response = {"fingerprint": selected.observation_fingerprint, "status": "observed",
                "overlaps": [[1, 2]], "omissions": [{"rule_id": rule.rule_id, "exact_quote": rule.source_quote}]}
    seen = []
    async def read(session, key, plan):
        seen.append((session, key, plan))
        return {"identity": _digest(plan), "response": response, "response_sha256": _digest(response)}
    journal.read_owned_value_in_session = AsyncMock(side_effect=read)
    guard = build_owned_selection_guard(lesson=lesson, corpus=corpus, rules=(rule,), journal=journal,
        expected_document_ids=("d1",), review_group_id="diversity:g", source_sha256=source_hash,
        route_fingerprint="b" * 64, selected=selected)
    session = object()
    assert await guard(session, object(), {}) is True
    assert seen[0][0] is session
    response["omissions"][0]["exact_quote"] = "foreign"
    assert await guard(session, object(), {}) is False


@pytest.mark.asyncio
async def test_stale_projection_or_missing_owned_receipt_denies():
    args = setup()
    selected = select_candidate(**args)
    assert selected is not None
    corpus, rule, lesson = args["corpus"], args["rules"][0], args["lesson"]
    journal = PendingStageJournal("tenant", uuid4(), "job", object())
    journal.read_owned_value_in_session = AsyncMock(return_value=None)
    digest = hashlib.sha256(corpus.documents[0].source_text.encode()).hexdigest()
    case = lesson.cases[0]
    changed = replace(lesson, cases=(replace(case, variants=(replace(case.variants[0], prompt="different"), case.variants[1])),))
    guard = build_owned_selection_guard(lesson=changed, corpus=corpus, rules=(rule,), journal=journal,
        expected_document_ids=("d1",), review_group_id="diversity:g", source_sha256=digest,
        route_fingerprint="b" * 64, selected=selected)
    assert await guard(object(), object(), {}) is False
