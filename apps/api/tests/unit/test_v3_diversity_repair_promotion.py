import socket
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.ai.v3.diversity_repair_promotion import staged_diversity_repair
from app.modules.ai.v3.diversity_repair_selection import select_candidate
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
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
@pytest.mark.parametrize("failure", ["candidate", "citation", "case", "post", "unknown", None])
async def test_only_independently_reviewed_candidate_can_be_promoted(monkeypatch, failure):
    import app.modules.ai.v3.case_repair_gate as case_gate
    import app.modules.ai.v3.diversity_repair_promotion as promotion
    import app.modules.ai.v3.service as service

    data = setup()
    lesson = data["lesson"]
    selected = select_candidate(**data)
    assert selected is not None
    case = lesson.cases[0]
    variant = replace(case.variants[1], prompt="distinct target")
    candidate = replace(lesson, cases=(replace(case, variants=(case.variants[0], variant)),))
    author = AsyncMock(return_value=None if failure == "candidate" else candidate)
    monkeypatch.setattr(promotion, "author_owned_variant", author)
    monkeypatch.setattr(service, "_review_source_unit_fragments", lambda *_: ["source"])
    monkeypatch.setattr(service, "_unbound_case_citation_ids", lambda *_: ["bad"] if failure == "citation" else [])
    critic = AsyncMock(return_value=(failure != "case", {}))
    monkeypatch.setattr(case_gate, "review_staged_case", critic)
    post = AsyncMock(side_effect=ExtractionOutcomeUnknownError("held") if failure == "unknown" else None,
        return_value={"status": "review_required", "overlaps": [[1, 2]] if failure == "post" else [], "omissions": []})
    monkeypatch.setattr(promotion, "review_final_lesson", post)
    source = data["corpus"].documents[0].source_text
    quote = "Далее выполняется запись."
    start = source.index(quote)
    dependency = replace(data["rules"][0], rule_id="dependency", source_quote=quote,
                         source_start=start, source_end=start + len(quote))
    args = dict(lesson=lesson, corpus=data["corpus"], rules=data["rules"], selected=selected,
        journal=type("Journal", (), {"tenant_id": "tenant"})(), expected_document_ids=("d1",),
        review_group_id="diversity:g", source_sha256="a" * 64, route_fingerprint="b" * 64,
        direct_client=object(), context_rules=(dependency,), unresolved_dependencies=())
    if failure == "unknown":
        with pytest.raises(ExtractionOutcomeUnknownError):
            await staged_diversity_repair(**args)
    else:
        result, accepted = await staged_diversity_repair(**args)
        assert accepted is (failure is None)
        assert result == (candidate if accepted else lesson)
    author.assert_awaited_once()
    assert author.await_args.kwargs["context_rules"] == (dependency,)
    if failure in (None, "post", "unknown"):
        critic.assert_awaited_once()
        post.assert_awaited_once()
        assert post.await_args.kwargs["lesson"] == candidate
        assert post.await_args.kwargs["context_rules"] == (dependency,)
        assert post.await_args.kwargs["group_id"] == "diversity-post-repair:diversity:g"
    else:
        post.assert_not_awaited()



@pytest.mark.asyncio
async def test_unresolved_and_changed_dependency_hold_before_author(monkeypatch):
    import app.modules.ai.v3.diversity_repair_promotion as promotion

    data = setup()
    selected = select_candidate(**data)
    corpus, rule = data["corpus"], data["rules"][0]
    source = corpus.documents[0].source_text
    quote = "Далее выполняется запись."
    start = source.index(quote)
    context_rule = replace(rule, rule_id="dependency", statement=quote, source_quote=quote,
                           source_start=start, source_end=start + len(quote))
    author = AsyncMock()
    monkeypatch.setattr(promotion, "author_owned_variant", author)
    args = dict(lesson=data["lesson"], corpus=corpus, rules=data["rules"], selected=selected,
        journal=type("Journal", (), {"tenant_id": "tenant"})(), expected_document_ids=("d1",),
        review_group_id="diversity:g", source_sha256="a" * 64, route_fingerprint="b" * 64,
        direct_client=object(), context_rules=(context_rule,), unresolved_dependencies=("missing",))
    assert await staged_diversity_repair(**args) == (data["lesson"], False)
    changed = replace(corpus, documents=(replace(corpus.documents[0], source_text=source.replace(quote, "changed")),))
    assert await staged_diversity_repair(**(args | {"corpus": changed, "unresolved_dependencies": ()})) == (data["lesson"], False)
    author.assert_not_awaited()



@pytest.mark.asyncio
async def test_case_reviewer_echo_never_enters_feedback(monkeypatch):
    import json

    import app.modules.ai.v3.case_repair_gate as case_gate
    import app.modules.ai.v3.diversity_repair_promotion as promotion
    import app.modules.ai.v3.service as service

    data = setup()
    selected = select_candidate(**data)
    lesson = data["lesson"]
    case = lesson.cases[0]
    candidate = replace(lesson, cases=(replace(case, variants=(case.variants[0],
        replace(case.variants[1], prompt="new"))),))
    monkeypatch.setattr(promotion, "author_owned_variant", AsyncMock(return_value=candidate))
    monkeypatch.setattr(service, "_review_source_unit_fragments", lambda *_: ["source"])
    monkeypatch.setattr(service, "_unbound_case_citation_ids", lambda *_: [])
    secret = "SYNTHETIC_PRIVATE_ECHO_4831"
    async def critic(*args):
        args[-1].update(recheck={"summary": secret}, answer_rechecks=[{"question_id": secret,
            "review": {"claims": [secret]}, "rejection_reason": secret}], rejected=secret)
        return False, {}
    monkeypatch.setattr(case_gate, "review_staged_case", critic)
    feedback = {}
    result = await staged_diversity_repair(lesson=lesson, corpus=data["corpus"], rules=data["rules"],
        selected=selected, journal=type("Journal", (), {"tenant_id": "tenant"})(),
        expected_document_ids=("d1",), review_group_id="diversity:g", source_sha256="a" * 64,
        route_fingerprint="b" * 64, direct_client=object(), context_rules=(), unresolved_dependencies=(),
        feedback=feedback)
    assert result == (lesson, False)
    assert secret not in json.dumps(feedback)
    assert feedback["case_review"] == {"status": "rejected", "reviewed_variant_count": 1}
