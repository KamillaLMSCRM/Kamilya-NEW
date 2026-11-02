import socket
from dataclasses import replace

import httpx
import pytest

from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.diversity_repair_selection import preserves_non_target, select_candidate
from app.modules.ai.v3.diversity_review import POLICY, _hash
from app.modules.ai.v3.models import V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase
from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest
from tests.unit.test_v3_primary_source_manifest import sample


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(httpx, "Client", blocked)
    monkeypatch.setattr(httpx, "AsyncClient", blocked)


def setup():
    corpus, rule = sample()

    def v(i):
        return V3QuestionVariant(
            i,
            "",
            "Scenario",
            "Prompt",
            V3Option("right", True),
            (V3Option("bad", False), V3Option("wrong", False), V3Option("no", False)),
            "explanation",
            rule.source_quote,
        )

    lesson = V3Lesson(
        "l", "title", "module", "body", ("r1",), cases=(V3ScenarioCase("c1", "r1", "objective", (v("v1"), v("v2"))),)
    )
    manifest = build_primary_source_manifest(
        corpus, (rule,), expected_tenant_id="tenant", expected_document_ids=("d1",)
    )
    request = {
        "policy": POLICY,
        "manifest_sha256": manifest.fingerprint,
        "primary_sources": [{"rule_id": rule.rule_id, "text": manifest.fragments[0]}],
        "questions": [q.to_dict() for q in project_lesson_questions(lesson)],
    }
    observed = {
        "status": "review_required",
        "fingerprint": _hash(request),
        "overlaps": [[1, 2]],
        "omissions": [{"rule_id": "r1", "exact_quote": rule.source_quote}],
    }
    return {
        "lesson": lesson,
        "corpus": corpus,
        "rules": (rule,),
        "expected_tenant_id": "tenant",
        "expected_document_ids": ("d1",),
        "observation": observed,
        "selected_index": 2,
    }


def test_selection_and_target_only_preservation():
    kw = setup()
    selected = select_candidate(**kw)
    assert selected and (selected.case_id, selected.variant_id, selected.question_index) == ("c1", "v2", 2)
    lesson = kw["lesson"]
    case = lesson.cases[0]
    candidate = replace(
        lesson, cases=(replace(case, variants=(case.variants[0], replace(case.variants[1], prompt="new"))),)
    )
    assert preserves_non_target(lesson, candidate, selected)
    assert not preserves_non_target(lesson, replace(candidate, content="changed"), selected)
    assert not preserves_non_target(
        lesson, replace(candidate, cases=(replace(candidate.cases[0],
            variants=(replace(case.variants[0], prompt="changed"), candidate.cases[0].variants[1])),)), selected)


@pytest.mark.parametrize("target", [1, 2])
def test_selected_variant_updates_only_its_canonical_compatibility_question(target):
    kw = setup()
    selected = select_candidate(**(kw | {"selected_index": target}))
    lesson = kw["lesson"]
    case = lesson.cases[0]
    original = replace(lesson, questions=(case.variants[0].assemble_question(seed=42),))
    variants = list(case.variants)
    variants[target - 1] = replace(variants[target - 1], prompt="new prompt")
    new_case = replace(case, variants=tuple(variants))
    questions = (variants[0].assemble_question(seed=42),) if target == 1 else original.questions
    candidate = replace(original, cases=(new_case,), questions=questions)
    assert preserves_non_target(original, candidate, selected)
    if target == 1:
        assert not preserves_non_target(original, replace(candidate, questions=original.questions), selected)
    assert not preserves_non_target(original, replace(candidate, questions=(replace(questions[0], explanation="bad"),)), selected)


def test_omission_subspan_must_be_unique_within_bound_fragment():
    kw = setup()
    observation = dict(kw["observation"])
    observation["omissions"] = [{"rule_id": "r1", "exact_quote": "сверяет документ"}]
    assert select_candidate(**(kw | {"observation": observation})) is not None
    observation["omissions"] = [{"rule_id": "r1", "exact_quote": "С"}]
    assert select_candidate(**(kw | {"observation": observation})) is not None
    observation["omissions"] = [{"rule_id": "r1", "exact_quote": "о"}]
    assert select_candidate(**(kw | {"observation": observation})) is None
    rule = replace(kw["rules"][0], source_end=len(kw["corpus"].documents[0].source_text))
    manifest = build_primary_source_manifest(kw["corpus"], (rule,), expected_tenant_id="tenant", expected_document_ids=("d1",))
    request = {"policy": POLICY, "manifest_sha256": manifest.fingerprint,
        "primary_sources": [{"rule_id": rule.rule_id, "text": manifest.fragments[0]}],
        "questions": [q.to_dict() for q in project_lesson_questions(kw["lesson"])]}
    observation["fingerprint"] = _hash(request)
    observation["omissions"] = [{"rule_id": "r1", "exact_quote": "ет"}]
    assert manifest.fragments[0].count("ет") > 1
    assert select_candidate(**(kw | {"rules": (rule,), "observation": observation})) is None


@pytest.mark.parametrize(
    "change",
    [
        {"selected_index": True},
        {"selected_index": 3},
        {"expected_tenant_id": "wrong"},
        {"expected_document_ids": ("wrong",)},
        {
            "observation": {
                "status": "review_required",
                "fingerprint": "fingerprint",
                "overlaps": [[1, 2], [1, 2]],
                "omissions": [],
            }
        },
        {
            "observation": {
                "status": "review_required",
                "fingerprint": "fingerprint",
                "overlaps": [[1, 2]],
                "omissions": [{"rule_id": "r1", "exact_quote": "not source"}],
            }
        },
        {"observation": {"status": "unknown", "fingerprint": "fingerprint", "overlaps": [[1, 2]], "omissions": []}},
    ],
)
def test_ambiguous_or_unowned_fails_closed(change):
    assert select_candidate(**(setup() | change)) is None


def test_duplicate_variant_id_or_flat_lesson_fails_closed():
    kw = setup()
    c = kw["lesson"].cases[0]
    duplicate_lesson = replace(kw["lesson"], cases=(replace(c, variants=(c.variants[0], c.variants[0])),))
    assert select_candidate(**(kw | {"lesson": duplicate_lesson})) is None
    assert select_candidate(**(kw | {"lesson": replace(duplicate_lesson, cases=())})) is None


def test_stale_question_and_absent_character_held():
    kw = setup()
    lesson = kw["lesson"]
    case = lesson.cases[0]
    changed = replace(case.variants[0], prompt="changed")
    assert (
        select_candidate(
            **(kw | {"lesson": replace(lesson, cases=(replace(case, variants=(changed, case.variants[1])),))})
        )
        is None
    )
    o = dict(kw["observation"])
    o["omissions"] = [{"rule_id": "r1", "exact_quote": "Я"}]
    assert select_candidate(**(kw | {"observation": o})) is None


def test_short_complete_fragment_is_eligible():
    kw = setup()
    corpus = kw["corpus"]
    doc = replace(corpus.documents[0], source_text="Да")
    corpus = replace(corpus, documents=(doc,))
    rule = replace(kw["rules"][0], source_quote="Да", source_start=0, source_end=2)
    lesson = kw["lesson"]
    manifest = build_primary_source_manifest(
        corpus, (rule,), expected_tenant_id="tenant", expected_document_ids=("d1",)
    )
    assert manifest is not None
    request = {
        "policy": POLICY,
        "manifest_sha256": manifest.fingerprint,
        "primary_sources": [{"rule_id": rule.rule_id, "text": manifest.fragments[0]}],
        "questions": [q.to_dict() for q in project_lesson_questions(lesson)],
    }
    observation = {
        "status": "review_required",
        "fingerprint": _hash(request),
        "overlaps": [[1, 2]],
        "omissions": [{"rule_id": "r1", "exact_quote": "Да"}],
    }
    assert select_candidate(**(kw | {"corpus": corpus, "rules": (rule,), "observation": observation})) is not None


@pytest.mark.asyncio
async def test_owned_reader_rejects_stale_and_selects_persisted_review(monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.modules.ai.v3.diversity_repair_selection import select_owned_candidate
    from app.modules.ai.v3.diversity_review import review_final_lesson
    from tests.unit.test_direct_luna_owned_stage import setup as direct_setup

    kw = setup()
    fake, journal, client, _, _ = direct_setup()
    corpus = replace(kw["corpus"], tenant_id=journal.tenant_id)
    source_sha = hashlib.sha256(corpus.documents[0].source_text.encode()).hexdigest()
    common = dict(
        lesson=kw["lesson"],
        corpus=corpus,
        rules=kw["rules"],
        expected_tenant_id=journal.tenant_id,
        expected_document_ids=("d1",),
        journal=journal,
        group_id="diversity:g",
        source_sha256=source_sha,
        route_fingerprint="b" * 64,
    )
    fingerprints = []

    async def prepare(messages, **kwargs):
        fingerprints.append(json.loads(messages[1]["content"])["fingerprint"])
        return object()

    async def invoke(_cap, **kwargs):
        return SimpleNamespace(
            content={
                "fingerprint": fingerprints[-1],
                "status": "observed",
                "overlaps": [[1, 2]],
                "omissions": [{"rule_id": "r1", "exact_quote": kw["rules"][0].source_quote}],
            }
        )

    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))

    async def forbidden(_messages):
        raise AssertionError("legacy call")

    await review_final_lesson(**common, invoke=forbidden, direct_client=client)
    selection = await select_owned_candidate(**common, selected_index=2)
    assert selection is not None and selection.variant_id == "v2"
    assert await select_owned_candidate(**(common | {"source_sha256": "a" * 64}), selected_index=2) is None
    lesson = common["lesson"]
    case = lesson.cases[0]
    changed = replace(
        lesson, cases=(replace(case, variants=(replace(case.variants[0], prompt="changed"), case.variants[1])),)
    )
    assert await select_owned_candidate(**(common | {"lesson": changed}), selected_index=2) is None
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()


@pytest.fixture
def network_denied(monkeypatch):
    import socket

    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unknown", "malformed", "verifier_denied", "forged_digest", "drift_after_inspection"])
async def test_owned_reader_rejects_untrusted_results(monkeypatch, network_denied, mode):
    import hashlib
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.modules.ai.v3.diversity_repair_selection import select_owned_candidate
    from app.modules.ai.v3.diversity_review import review_final_lesson
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from tests.unit.test_direct_luna_owned_stage import setup as direct_setup

    kw = setup()
    fake, journal, client, _, _ = direct_setup()
    corpus = replace(kw["corpus"], tenant_id=journal.tenant_id)
    source_sha = hashlib.sha256(corpus.documents[0].source_text.encode()).hexdigest()
    common = dict(
        lesson=kw["lesson"],
        corpus=corpus,
        rules=kw["rules"],
        expected_tenant_id=journal.tenant_id,
        expected_document_ids=("d1",),
        journal=journal,
        group_id="diversity:g",
        source_sha256=source_sha,
        route_fingerprint="b" * 64,
    )
    fingerprints = []

    async def prepare(messages, **kwargs):
        fingerprints.append(json.loads(messages[1]["content"])["fingerprint"])
        return object()

    async def invoke(_cap, **kwargs):
        content = {
            "fingerprint": fingerprints[-1],
            "status": "observed",
            "overlaps": [[1, 2]],
            "omissions": [{"rule_id": "r1", "exact_quote": kw["rules"][0].source_quote}],
        }
        if mode == "unknown":
            content["status"] = "unknown"
        if mode == "malformed":
            content["overlaps"] = [[1, 1]]
        return SimpleNamespace(content=content)

    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))

    async def forbidden(_messages):
        raise AssertionError("provider forbidden")

    await review_final_lesson(**common, invoke=forbidden, direct_client=client)
    if mode == "verifier_denied":

        async def deny(_session, _job, _plan):
            return False

        journal.verify_source = deny
    if mode == "drift_after_inspection":
        from app.modules.ai.v3 import owned_stage_inspection

        original_inspect = owned_stage_inspection.inspect_owned_stage

        async def drift_after(*args, **kwargs):
            result = await original_inspect(*args, **kwargs)

            async def deny(_session, _job, _plan):
                return False

            journal.verify_source = deny
            return result

        monkeypatch.setattr(owned_stage_inspection, "inspect_owned_stage", drift_after)
    if mode == "forged_digest":
        keys = [key for key in fake.values if "result" in key]
        assert len(keys) == 1
        fake.values[keys[0]]["response_sha256"] = "0" * 64
    if mode in ("verifier_denied", "forged_digest"):
        with pytest.raises(ExtractionOutcomeUnknownError):
            await select_owned_candidate(**common, selected_index=2)
    elif mode == "drift_after_inspection":
        # Documents the separate-transaction gap; the later repair must recheck ownership.
        assert await select_owned_candidate(**common, selected_index=2) is not None
    else:
        assert await select_owned_candidate(**common, selected_index=2) is None
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()
