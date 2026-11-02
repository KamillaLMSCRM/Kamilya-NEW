import hashlib
import socket
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.diversity_repair_selection import select_candidate
from app.modules.ai.v3.diversity_review import POLICY, _hash
from app.modules.ai.v3.diversity_variant_author import author_owned_variant
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_direct_luna_owned_stage import setup as journal_setup
from tests.unit.test_v3_diversity_repair_selection import setup as lesson_setup
from tests.unit.test_v3_owned_claim_guard import fresh_repair_scope


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
@pytest.mark.parametrize("timeout", [False, True])
async def test_owned_author_replay_or_unknown_never_repeats(monkeypatch, timeout):
    fake, journal, client, _, _ = journal_setup()
    fresh_repair_scope(fake, journal)
    data = lesson_setup()
    corpus = replace(data["corpus"], tenant_id=journal.tenant_id)
    lesson, rules = data["lesson"], data["rules"]
    manifest = build_primary_source_manifest(corpus, rules, expected_tenant_id=journal.tenant_id,
                                             expected_document_ids=("d1",))
    request = {"policy": POLICY, "manifest_sha256": manifest.fingerprint,
        "primary_sources": [{"rule_id": rules[0].rule_id, "text": manifest.fragments[0]}],
        "questions": [q.to_dict() for q in project_lesson_questions(lesson)]}
    review = {"fingerprint": _hash(request), "status": "observed", "overlaps": [[1, 2]],
              "omissions": [{"rule_id": "r1", "exact_quote": rules[0].source_quote}]}
    selected = select_candidate(lesson=lesson, corpus=corpus, rules=rules, expected_tenant_id=journal.tenant_id,
        expected_document_ids=("d1",), observation=review | {"status": "review_required"}, selected_index=2)
    assert selected is not None
    old_read = journal.read_owned_value_in_session
    async def read(session, key, plan):
        if plan.get("group_id") == "diversity:g":
            return {"identity": _digest(plan), "response": review, "response_sha256": _digest(review)}
        return await old_read(session, key, plan)
    journal.read_owned_value_in_session = read
    response = {"variant_id": selected.variant_id, "branch_context": "", "scenario_premise": "new",
        "prompt": "new?", "correct": "new fact", "explanation": "reason", "source_quote": selected.source_quote,
        "distractors": [{"text": x, "category": "role_confusion"} for x in ("a", "b", "c")]}
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(side_effect=TimeoutError("unknown") if timeout else None,
                       return_value=SimpleNamespace(content=response))
    monkeypatch.setattr(client, "prepare", prepare)
    monkeypatch.setattr(client, "invoke", invoke)
    args = dict(lesson=lesson, corpus=corpus, rules=rules, selected=selected, journal=journal,
        expected_document_ids=("d1",), review_group_id="diversity:g",
        source_sha256=hashlib.sha256(corpus.documents[0].source_text.encode()).hexdigest(),
        route_fingerprint="b" * 64, direct_client=client, max_output_tokens=128)
    if timeout:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await author_owned_variant(**args)
        assert has_pending(fake.job.result)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await author_owned_variant(**args)
    else:
        candidate = await author_owned_variant(**args)
        assert candidate.cases[0].variants[1].prompt == "new?"
        assert await author_owned_variant(**args) == candidate
        review["omissions"][0]["exact_quote"] = "foreign"
        with pytest.raises(ExtractionOutcomeUnknownError):
            await author_owned_variant(**args)
        review["omissions"][0]["exact_quote"] = selected.source_quote
        changed = replace(lesson, title="drift")
        with pytest.raises(ExtractionOutcomeUnknownError):
            await author_owned_variant(**(args | {"lesson": changed}))
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
