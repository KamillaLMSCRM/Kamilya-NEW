"""Assembled V10 ownership, real decoding and scoped post-edit regression."""

import copy
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.source_fidelity import ConversionFidelity
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V10_POLICY, SIMPLE_COURSE_REVIEW_V11_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus
from tests.unit.test_v3_simple_owned_transport_v8 import BetweenStagesError, fresh_journal
from tests.unit.test_v3_simple_owned_transport_v9 import response_for


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['v10', 'v11_complete', 'v11_missing'])
@pytest.mark.parametrize(
    ("transport", "fault", "interrupt"),
    [
        ("managed", "clean", 0),
        ("cloud", "clean", 0),
        ("managed", "fix", 0),
        ("cloud", "fix", 0),
        ("managed", "fix", 8),
        ("cloud", "fix", 8),
        ("managed", "fix", 9),
        ("cloud", "fix", 9),
        ("managed", "body", 0),
        ("managed", "title", 0),
        ("managed", "sources", 0),
        ("managed", "unflagged", 0),
        ("managed", "two_findings", 0),
        ("managed", "body_finding", 0),
        ("managed", "unsupported_question", 0),
        ("managed", "unsupported_lesson", 0),
        ("managed", "unsupported_course", 0),
        ("cloud", "unsupported_question", 0),
        ("cloud", "unsupported_lesson", 0),
        ("cloud", "unsupported_course", 0),
        ("managed", "bank_source", 0),
        ("managed", "editor_source", 0),
        ("managed", "upstream_source", 0),
        ("managed", "null_extra", 0),
        ("managed", "nonnull_extra", 0),
        ("managed", "required_null", 0),
        ("managed", "parent_resolved", 0),
        ("managed", "parent_unresolved", 0),
        ("cloud", "body", 0),
        ("cloud", "sources", 0),
        ("cloud", "unflagged", 0),
        ("cloud", "two_findings", 0),
        ("cloud", "body_finding", 0),
        ("cloud", "bank_source", 0),
        ("cloud", "editor_source", 0),
        ("cloud", "upstream_source", 0),
        ("cloud", "null_extra", 0),
        ("cloud", "nonnull_extra", 0),
        ("cloud", "required_null", 0),
        ("cloud", "parent_resolved", 0),
        ("cloud", "parent_unresolved", 0),
    ],
)
async def test_v10_assembled_owned_stages_and_cold_replay(monkeypatch, transport, fault, interrupt, variant):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    policy = SIMPLE_COURSE_REVIEW_V10_POLICY if variant == 'v10' else SIMPLE_COURSE_REVIEW_V11_POLICY
    journal.expected_review_policy = policy
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    if fault in {
        "bank_source",
        "editor_source",
        "upstream_source",
        "unsupported_question",
        "unsupported_lesson",
        "unsupported_course",
    }:
        clean = ConversionFidelity(
            engine="synthetic", fallback_used=False, metadata_present=True, metadata_verified=True
        )
        corpus = replace(
            corpus,
            documents=tuple(
                replace(
                    doc, conversion_fidelity=clean, review_only_source_context=(), review_only_source_unresolved=False
                )
                for doc in corpus.documents
            ),
        )
    packet = build_practical_source_packet(corpus)
    image = "![Caption a](source-asset:asset-" + "a" * 64 + ")"
    client, calls, remembered = client_for(journal), [], {}
    spec = importlib.util.spec_from_file_location(
        "v10_owned_runner", Path(__file__).resolve().parents[4] / "infra/codex-reserve/runner.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def produce(fmt, messages):
        assert runner._checked_structured_format(fmt) == fmt["json_schema"]["schema"]
        payload = json.loads(messages[1]["content"])
        if fmt['json_schema']['name'] == 'simple_finding_evidence_v1':
            props = fmt['json_schema']['schema']['properties']
            return 'evidence', {**{key: props[key]['enum'][0] for key in (
                'source_fingerprint', 'draft_fingerprint', 'result_fingerprint', 'inventory_fingerprint')},
                'bindings': {key: value['enum'][0] for key, value in props['bindings']['properties'].items()}}
        if fmt['json_schema']['name'] == 'simple_plan_accounting_v1':
            return 'accounting', {'source_fingerprint': packet.fingerprint,
                'plan_fingerprint': payload['plan_fingerprint'], 'new_units': [],
                'assignments': [{'slice_id': row['id'], 'unit_id': '', 'role': 'non_teaching',
                    'reason': 'Administrative context.'} for row in payload['missing_slices']]}
        if "unapproved_question_cards" in payload or 'assessment_cards' in payload:
            role = "bank"
            cards = payload.get('assessment_cards', payload.get('unapproved_question_cards'))
            assert len(cards) == 6
            fields = {'id', 'lesson_id', 'lesson_title', 'prompt', 'choices'}
            if variant == 'v10':
                assert all(set(c) == fields for c in cards)
                assert "correct_index" not in messages[1]["content"] and "explanation" not in messages[1]["content"]
                assert "New intro." not in messages[1]["content"] and "Preserve body." not in messages[1]["content"]
            else:
                assert all(set(c) == fields | {'correct_index', 'explanation', 'source_refs'} for c in cards)
                assert len(payload['lesson_bodies']) == 2 and 'UNTRUSTED' in messages[0]['content']
                assert 'New intro.' in messages[1]['content'] and 'Preserve body.' in messages[1]['content']
            assert "independent_content_review" not in payload and "unit_reviews" not in payload
            target = cards[1]
            remembered["cards"] = copy.deepcopy(cards)
            navigation = payload.get('lesson_source_navigation', [{'lesson_id': row['id'], 'source_refs': ['SRC1']}
                for row in payload.get('lesson_bodies', [])])
            raw = {
                "source_fingerprint": packet.fingerprint,
                "course_fingerprint": payload["course_fingerprint"],
                "summary": "Card comparison",
                "findings": [],
                "source_notes": [],
                "narrative_sources": {row["lesson_id"]: row["source_refs"] for row in navigation},
            }
            if fault != "clean":
                raw["findings"].append(
                    {
                        "domain": "assessment",
                        "severity": "material",
                        "target": {"kind": "question", "id": target["id"]},
                        "problem": "Card needs correction",
                        "basis": "Source passage",
                        "correction": "Repair prompt",
                        "source_refs": ["SRC1"],
                    }
                )
            if fault.startswith("unsupported_"):
                kind = fault.removeprefix("unsupported_")
                unsupported = copy.deepcopy(raw["findings"][0])
                unsupported["domain"] = "source"
                unsupported["problem"] = "Unsupported source-target finding"
                unsupported["target"] = {
                    "kind": kind,
                    "id": target["id"] if kind == "question" else target["lesson_id"] if kind == "lesson" else "course",
                }
                raw["findings"].append(unsupported)

            if fault == "two_findings":
                other = copy.deepcopy(raw["findings"][0])
                other["problem"] = "Second distinct issue"
                raw["findings"].append(other)
            if fault == "body_finding":
                raw["findings"].append(
                    {
                        "domain": "content",
                        "severity": "material",
                        "target": {"kind": "lesson", "id": target["lesson_id"]},
                        "problem": "Unsupported body finding",
                        "basis": "Source passage",
                        "correction": "Check body",
                        "source_refs": ["SRC1"],
                    }
                )
            if fault == "bank_source":
                # Source target IDs are schema-bound aliases.
                raw["findings"].append(
                    {
                        "domain": "source",
                        "severity": "material",
                        "target": {"kind": "source", "id": "SRC1"},
                        "problem": "Source ambiguity",
                        "basis": "Source passage",
                        "correction": "Review source",
                        "source_refs": ["SRC1"],
                    }
                )
            return role, raw
        if "flagged_cards" in payload:
            role = "repair"
            flagged = payload["flagged_cards"]
            assert len(flagged) == 1 and flagged[0]["question"]["id"] == remembered["cards"][1]["id"]
            if variant == 'v10' or fault != 'body_finding':
                assert "New intro." not in messages[1]["content"] and "Preserve body." not in messages[1]["content"]
            assert remembered["cards"][2]["prompt"] not in messages[1]["content"]
            q = copy.deepcopy(flagged[0]["question"])
            q["prompt"] = "Corrected second prompt"
            raw = {
                "source_fingerprint": packet.fingerprint,
                "draft_fingerprint": payload["draft_fingerprint"],
                "body_edits": [],
                "title_edits": [],
                "question_edits": [q],
                "added_lessons": [],
                "lesson_sources": copy.deepcopy(payload["lesson_sources"]),
                "source_questions": [],
                "finding_dispositions": [],
            }
            finding = payload["material_findings"][0]
            raw["finding_dispositions"].append(
                {
                    "finding_id": finding["id"],
                    "status": "CORRECTED",
                    "reason": "Corrected prompt",
                    "source_refs": ["SRC1"],
                    "source_quote": packet.blocks[0].text,
                    "target": {"kind": "question_prompt", "id": q["id"], "choice_index": 0},
                    "final_quote": "Corrected second prompt",
                }
            )
            if fault == "body":
                raw["body_edits"] = [{"block_id": "BODY1", "after": "forbidden"}]
            elif fault == "title":
                raw["title_edits"] = [{"lesson_id": flagged[0]["lesson_id"], "title": "forbidden"}]
            elif fault == "sources":
                raw["lesson_sources"][0]["source_refs"] = ["SRC2"]
            elif fault == "unflagged":
                raw["question_edits"].append({**q, "id": remembered["cards"][2]["id"]})
            elif fault == "editor_source":
                raw["source_questions"] = [{"question": "Corrector source observation", "source_refs": ["SRC1"]}]
            elif fault == "null_extra":
                raw["extra_null"] = None
            elif fault == "nonnull_extra":
                raw["extra_null"] = "bad"
            elif fault == "required_null":
                raw["question_edits"] = None
            return role, raw
        inner_fault = 'finding_resolved' if variant == 'v11_evidence' else (
            "finding_resolved"
            if fault == "parent_resolved"
            else "finding_unresolved"
            if fault == "parent_unresolved"
            else None
        )
        role, raw = response_for(fmt, messages, packet, image, inner_fault)
        if role == 'joint' and variant == 'v11_evidence':
            assert raw['finding_dispositions']
            for decision in raw['finding_dispositions']:
                decision['source_quote'] = 'malformed stitched quote'
        if role == 'plan' and variant == 'v11_missing':
            raw['non_teaching'] = []
        if role == "joint" and fault == "upstream_source":
            raw["source_questions"] = [{"question": "Upstream source hold", "source_refs": ["SRC1"]}]
        return role, raw

    async def invoke(capability, *, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        request = json.loads(client._prepared[capability])
        role, raw = produce(request["response_format"], request["messages"])
        calls.append(role)
        envelope = {
            "model": client.model,
            "structured_output_policy": "typed-json-object-v1",
            "response_format_sha256": response_contract_hash(request["response_format"]),
            "choices": [{"message": {"content": json.dumps(raw)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 25},
        }
        result, _ = client._decode_response(json.dumps(envelope).encode(), client._prepared[capability])
        return result

    class Cloud:
        async def ainvoke(self, messages, *, response_format):
            role, raw = produce(response_format, messages)
            calls.append(role)
            return SimpleNamespace(content=json.dumps(raw), finish_reason="stop")

    def cold():
        result = fresh_journal(journal, fake)
        result.expected_review_policy = policy
        return result

    monkeypatch.setattr(client, "invoke", invoke)
    monkeypatch.setattr("app.modules.ai.v3.service._practical_output_budget", AsyncMock(return_value=32768))
    args = {
        "corpus": corpus,
        "intent": CourseIntent(),
        "generation_client": Cloud() if transport == "cloud" else None,
        "extraction_journal": journal,
        "direct_client": client if transport == "managed" else None,
        "revision_policy": POLICY,
        "review_policy": policy,
        "route_fingerprint": "d" * 64,
    }
    try:
        if fault in {"nonnull_extra", "required_null"}:
            with pytest.raises(ExtractionOutcomeUnknownError):
                await generate_v3_course_from_corpus(**args)
            assert calls[-1] == "repair"
            return
        if interrupt:

            async def progress(_stage, completed, _total, _provider, _attempt):
                if completed == interrupt:
                    raise BetweenStagesError()

            with pytest.raises(BetweenStagesError):
                await generate_v3_course_from_corpus(**args, progress_callback=progress)
            assert len(calls) == interrupt
            args["extraction_journal"] = cold()
        first = await generate_v3_course_from_corpus(**args)
        count = len(calls)
        replay = await generate_v3_course_from_corpus(**{**args, "extraction_journal": cold()})
        assert len(calls) == count and first.content == replay.content and first.assessment == replay.assessment
        assert calls == ["plan"] + (["accounting"] if variant == 'v11_missing' else []) + ["author", "unit-review", "author", "unit-review", "review", "joint"] + (['evidence'] if variant == 'v11_evidence' else []) + ["bank"] + (
            [] if fault == "clean" else ["repair"]
        )
        course = first.diagnostics["practical_course"]
        lessons = course["lessons"]
        assert lessons[0]["content"] == "New intro.\n\nPreserve body.\n" + image
        assert lessons[0]["questions"][0]["prompt"] == "Edited question"
        unapplied = fault in {"body", "title", "sources", "unflagged"}
        assert lessons[0]["questions"][1]["prompt"] == (
            "HIDDEN_QUESTION q1" if fault == "clean" or unapplied else "Corrected second prompt"
        )
        assert lessons[0]["questions"][2]["prompt"] == "HIDDEN_QUESTION q2"
        post = first.diagnostics["simple_review"]["postedit_card_review"]
        if variant == 'v11_evidence':
            evidence = first.diagnostics['simple_review']['source_evidence_repair']
            assert not evidence['semantic_approval']
            original = evidence['original_revision_receipt']['review_finding_dispositions'][0]
            current = first.diagnostics['simple_review']['revision_receipt']['review_finding_dispositions'][0]
            assert not original['model_resolved'] and current['model_resolved']
            assert current['result_fingerprint'] == _digest(course)
        assert [lesson["title"] for lesson in lessons] == (
            ["Lesson", "Lesson"] if variant == 'v10' else ["First — Lesson", "Second — Lesson"])
        assert lessons[1]["content"] == "Old intro.\n\nPreserve body."
        for lesson in lessons:
            assert _digest([lesson["title"], lesson["content"]]) == post["lesson_fingerprints"][lesson["id"]]
            for question in lesson["questions"]:
                if question["id"] != remembered["cards"][1]["id"] or fault == "clean" or unapplied:
                    assert _digest(question) == post["question_fingerprints"][question["id"]]
        assert post["application_status"] == (
            "not_needed" if fault == "clean" else "unapplied" if unapplied else "applied"
        )
        issues = first.diagnostics["draft_review"]["issues"]
        if unapplied:
            assert any(i["id"] == "simple-v10-card-application" and i["blocking"] for i in issues)
        if fault == "two_findings":
            rows = [i for i in [*issues, *first.diagnostics['draft_review']['observations']]
                    if i["id"].startswith("simple-v10-post-")]
            assert len(rows) == 2 and len({i["id"] for i in rows}) == 2 and sum(i["blocking"] for i in rows) == 1
        if fault == "body_finding":
            assert any("Unsupported body finding" in i["message"] and i["blocking"] for i in issues)
        if fault.startswith("unsupported_"):
            retained = [row for row in issues if "Unsupported source-target finding" in row["message"]]
            assert len(retained) == 1 and retained[0]["blocking"] and retained[0]["evidence"]["unverified"]
            assert post["application_status"] == "applied"
            assert not first.diagnostics["requires_source_review"]

        if fault == "bank_source":
            assert (
                first.diagnostics["requires_source_review"]
                and first.diagnostics["draft_review"]["source_clarification_required"]
            )
            assert any(i["id"].startswith("simple-v10-source-") and i["blocking"] for i in issues)
        if fault == "editor_source":
            observations = first.diagnostics["draft_review"]["observations"]
            assert any("Corrector source observation" in i["message"] and not i["blocking"] for i in observations)
            assert first.diagnostics["requires_source_review"] == any(
                doc.conversion_fidelity.needs_review
                or doc.review_only_source_unresolved
                or doc.review_only_source_context
                for doc in corpus.documents
            )
        if fault == "upstream_source":
            assert first.diagnostics["requires_source_review"]
            assert any("Upstream source hold" in i["message"] and i["blocking"] for i in issues)
        if fault in {"parent_resolved", "parent_unresolved"}:
            receipt = first.diagnostics["simple_review"]["revision_receipt"]
            row = receipt["review_finding_dispositions"][0]
            assert row["model_resolved"] == (fault == "parent_resolved") and not row["semantic_approval"]
            assert receipt["pre_postedit_finding_dispositions"][0]["model_resolved"] == (fault == "parent_resolved")
            assert row["result_fingerprint"] == post["result_fingerprint"]
            assert any(
                i["message"].startswith("Synthetic observation") and i["blocking"] == (fault == "parent_unresolved")
                for i in first.diagnostics['draft_review']['observations' if fault == 'parent_resolved' else 'issues']
            )
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('transport', ['managed', 'cloud'])
@pytest.mark.parametrize('interrupt', [0, 8, 9, 10])
async def test_v11_evidence_actual_decoders_owned_cold_replay(monkeypatch, transport, interrupt):
    await test_v10_assembled_owned_stages_and_cold_replay(monkeypatch, transport, 'fix', interrupt, 'v11_evidence')
