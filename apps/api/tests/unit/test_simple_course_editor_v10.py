import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.simple_course_editor import SimpleCourseResult
from app.modules.ai.v3.simple_course_editor_v10 import complete_card_review_v10, postedit_review_state
from app.modules.ai.v3.simple_editor_findings import compile_finding_dispositions, inventory
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


@pytest.fixture
def base_case():
    corpus = synthetic_corpus("tenant", mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    image = "![Caption a](source-asset:asset-" + "a" * 64 + ")"
    draft = unit_course(packet.blocks[0].block_id, "Preserved lesson.\n\n" + image)
    original = copy.deepcopy(draft)
    original["lessons"][0]["questions"][2]["prompt"] = "Parent correction"
    sources = [{"lesson_id": original["lessons"][0]["id"], "source_refs": [packet.blocks[0].block_id]}]
    receipt = {
        "application_status": "applied",
        "joint_delta_receipt": {
            "source_fingerprint": packet.fingerprint,
            "draft_fingerprint": _digest(draft),
            "result_fingerprint": _digest(original),
        },
    }
    parent = {
        "source_fingerprint": packet.fingerprint,
        "draft_fingerprint": _digest(draft),
        "unverified_source_questions": [],
        "unapplied_review_findings": [],
        "review_finding_dispositions": [],
    }
    base = SimpleCourseResult(
        draft=draft,
        course=original,
        plan={},
        source_questions=[],
        changes=[],
        review={"editor_delta_receipts": {"body": receipt}, "revision_receipt": parent, "proposals": []},
        lesson_sources=sources,
    )
    return corpus, packet, base


def stage_for(packet, base, *, findings=None, edit=True, bad_edit=False, source_note=False, decision=None):
    calls = []

    async def stage(name, group, messages, fmt, validator):
        calls.append((name, group))
        payload = json.loads(messages[1]["content"])
        if ":review-bank:" in group:
            value = {
                "source_fingerprint": packet.fingerprint,
                "course_fingerprint": _digest(base.course),
                "summary": "Literal comparison",
                "findings": copy.deepcopy(findings or []),
                "source_notes": [],
                "narrative_sources": {lesson["id"]: ["SRC2"] for lesson in base.course["lessons"]},
            }
        else:
            assert ":repair-cards:" in group
            card = copy.deepcopy(payload["flagged_cards"][0]["question"])
            if bad_edit:
                body_edits = [{"block_id": "BODY1", "after": "discarded body"}]
            else:
                body_edits = []
            if edit:
                card["prompt"] = "Corrected card prompt"
            value = {
                "source_fingerprint": packet.fingerprint,
                "draft_fingerprint": _digest(base.course),
                "body_edits": body_edits,
                "title_edits": [],
                "added_lessons": [],
                "question_edits": [card] if edit else [],
                "lesson_sources": payload["lesson_sources"],
                "source_questions": [{"question": "Editor speculation", "source_refs": ["SRC1"]}]
                if source_note
                else [],
                "finding_dispositions": [],
            }
            if decision:
                value["finding_dispositions"] = [
                    {
                        "finding_id": payload["material_findings"][0]["id"],
                        "status": decision,
                        "reason": "Source supports it",
                        "source_refs": ["SRC1"],
                        "source_quote": packet.blocks[0].text.strip(),
                        "target": {"kind": "question_prompt", "id": card["id"], "choice_index": 0},
                        "final_quote": card["prompt"],
                    }
                ]
        validator(value)
        return value

    return stage, calls


def finding(qid, problem="First problem"):
    return {
        "domain": "assessment",
        "severity": "material",
        "target": {"kind": "question", "id": qid},
        "problem": problem,
        "basis": "Source comparison",
        "correction": "Check this card",
        "source_refs": ["SRC1"],
    }


@pytest.mark.asyncio
async def test_clean_bank_keeps_course_and_skips_correction(base_case):
    corpus, packet, base = base_case
    source_question = {"question": "Existing source hold", "source_refs": [packet.blocks[0].block_id]}
    base.source_questions.append(source_question)
    stage, calls = stage_for(packet, base)
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    issues, observations, source_hold = postedit_review_state(result, packet)
    assert len(calls) == 1 and result.course == base.course and result.lesson_sources == base.lesson_sources
    assert result.source_questions == [source_question] and not issues and not observations and not source_hold


@pytest.mark.asyncio
async def test_safe_card_fix_retains_distinct_findings_and_upstream_holds(base_case):
    corpus, packet, base = base_case
    qid = base.course["lessons"][0]["questions"][0]["id"]
    base.source_questions.append({"question": "Prior source question", "source_refs": [packet.blocks[0].block_id]})
    base.review["revision_receipt"]["unverified_source_questions"].append({"id": "prior", "question": "Prior hold"})
    source_finding = {
        "domain": "source",
        "severity": "material",
        "target": {"kind": "source", "id": "SRC1"},
        "problem": "Reviewer source uncertainty",
        "basis": "Source",
        "correction": "Review",
        "source_refs": ["SRC1"],
    }
    stage, calls = stage_for(
        packet,
        base,
        findings=[finding(qid), finding(qid, "Second problem"), source_finding],
        source_note=True,
        decision="CORRECTED",
    )
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    issues, observations, source_hold = postedit_review_state(result, packet)
    assert len(calls) == 2 and source_hold
    assert result.source_questions == base.source_questions and result.lesson_sources == base.lesson_sources
    assert (
        result.review["revision_receipt"]["unverified_source_questions"]
        == base.review["revision_receipt"]["unverified_source_questions"]
    )
    assert result.course["lessons"][0]["content"] == base.course["lessons"][0]["content"]
    assert result.course["lessons"][0]["title"] == base.course["lessons"][0]["title"]
    assert result.course["lessons"][0]["questions"][1:] == base.course["lessons"][0]["questions"][1:]
    qissues = [i for i in issues if i["target_id"] == qid]
    assert len(qissues) == 2 and len({i["id"] for i in qissues}) == 2
    assert any(not i["blocking"] for i in qissues) and any(i["blocking"] for i in qissues)
    assert any(o["message"] == "Editor speculation" and not o["blocking"] for o in observations)


@pytest.mark.asyncio
async def test_out_of_scope_correction_preserves_course_and_exposes_blocker(base_case):
    corpus, packet, base = base_case
    qid = base.course["lessons"][0]["questions"][0]["id"]
    stage, _ = stage_for(packet, base, findings=[finding(qid)], bad_edit=True)
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    issues, _, _ = postedit_review_state(result, packet)
    assert result.course == base.course and result.review["postedit_card_review"]["application_status"] == "unapplied"
    assert any(i["blocking"] and i["target_id"] == qid for i in issues)


@pytest.mark.asyncio
async def test_noop_not_material_is_unverified_model_claim(base_case):
    corpus, packet, base = base_case
    qid = base.course["lessons"][0]["questions"][0]["id"]
    stage, _ = stage_for(packet, base, findings=[finding(qid)], edit=False, decision="NOT_MATERIAL")
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    issues, _, _ = postedit_review_state(result, packet)
    assert result.course == base.course and len(issues) == 1 and not issues[0]["blocking"]
    assert issues[0]["evidence"]["unverified"] and not issues[0]["evidence"]["semantic_approval"]


@pytest.mark.asyncio
async def test_unsupported_body_finding_does_not_block_scoped_card_fix_or_disappear(base_case):
    corpus, packet, base = base_case
    qid = base.course["lessons"][0]["questions"][0]["id"]
    body = {
        "domain": "content",
        "severity": "material",
        "target": {"kind": "lesson", "id": base.course["lessons"][0]["id"]},
        "problem": "Body claim",
        "basis": "Source",
        "correction": "Review",
        "source_refs": ["SRC1"],
    }
    stage, _ = stage_for(packet, base, findings=[finding(qid), body])
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    issues, _, _ = postedit_review_state(result, packet)
    assert result.course["lessons"][0]["questions"][0]["prompt"] == "Corrected card prompt"
    assert any(i["blocking"] and "Body claim" in i["message"] for i in issues)


@pytest.mark.asyncio
async def test_prior_question_disposition_revalidates_after_edit_and_body_claim_survives(base_case):
    corpus, packet, base = base_case
    q = base.draft["lessons"][0]["questions"][0]
    lesson = base.draft["lessons"][0]
    ref = packet.blocks[0].block_id
    previous = {
        "findings": [
            {
                "domain": "assessment",
                "severity": "material",
                "target": {"kind": "question", "id": q["id"]},
                "problem": "Prior card",
                "basis": "Source",
                "correction": "Check",
                "source_refs": [ref],
            },
            {
                "domain": "content",
                "severity": "material",
                "target": {"kind": "lesson", "id": lesson["id"]},
                "problem": "Prior body",
                "basis": "Source",
                "correction": "Check",
                "source_refs": [ref],
            },
        ]
    }
    rows = inventory(packet.fingerprint, _digest(base.draft), [("prior", previous)])
    source_quote = packet.blocks[0].text.strip()
    decisions = [
        {
            "finding_id": rows[0]["id"],
            "status": "ALREADY_SATISFIED",
            "reason": "Present",
            "source_refs": [ref],
            "source_quote": source_quote,
            "target": {"kind": "question_prompt", "id": q["id"], "choice_index": 0},
            "final_quote": q["prompt"],
        },
        {
            "finding_id": rows[1]["id"],
            "status": "ALREADY_SATISFIED",
            "reason": "Present",
            "source_refs": [ref],
            "source_quote": source_quote,
            "target": {"kind": "lesson_content", "id": lesson["id"], "choice_index": 0},
            "final_quote": "Preserved lesson.",
        },
    ]
    old = compile_finding_dispositions(rows, decisions, packet, base.draft, base.course)
    assert all(row["model_resolved"] for row in old)
    base.review["revision_receipt"]["review_finding_dispositions"] = old
    stage, _ = stage_for(packet, base, findings=[finding(q["id"])])
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    receipt = result.review["revision_receipt"]
    current = receipt["review_finding_dispositions"]
    assert not current[0]["model_resolved"] and current[1]["model_resolved"]
    assert all(row["result_fingerprint"] == _digest(result.course) for row in current)
    assert any(row["finding"]["problem"] == "Prior card" for row in receipt["unapplied_review_findings"])
    assert receipt["pre_postedit_finding_dispositions"] == old


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source", "draft", "before", "question", "body", "sources"])
async def test_tampered_postedit_ancestry_fails(base_case, fault):
    corpus, packet, base = base_case
    qid = base.course["lessons"][0]["questions"][0]["id"]
    stage, _ = stage_for(packet, base, findings=[finding(qid)])
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    result = copy.deepcopy(result)
    post = result.review["postedit_card_review"]
    if fault == "source":
        post["source_fingerprint"] = "0" * 64
    elif fault == "draft":
        post["pipeline_draft_fingerprint"] = "0" * 64
    elif fault == "before":
        post["reviewed_course_fingerprint"] = "0" * 64
    elif fault == "question":
        post["before_questions"][qid]["prompt"] += " tamper"
    elif fault == "body":
        result.course["lessons"][0]["content"] += " tamper"
    else:
        result.lesson_sources[0]["source_refs"] = [packet.blocks[1].block_id]
    with pytest.raises(ValueError):
        postedit_review_state(result, packet)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["question", "lesson", "course"])
async def test_unsupported_source_target_stays_visible_beside_safe_card_fix(base_case, kind):
    corpus, packet, base = base_case
    lesson = base.course["lessons"][0]
    qid = lesson["questions"][0]["id"]
    unsupported = finding(qid, "Unsupported source-target finding")
    unsupported["domain"] = "source"
    unsupported["target"] = {
        "kind": kind,
        "id": qid if kind == "question" else lesson["id"] if kind == "lesson" else "course",
    }
    stage, _ = stage_for(packet, base, findings=[finding(qid), unsupported], decision="CORRECTED")
    result = await complete_card_review_v10(packet, corpus, {}, base, stage)
    issues, _, source_hold = postedit_review_state(result, packet)
    assert result.course["lessons"][0]["questions"][0]["prompt"] == "Corrected card prompt"
    assert result.review["postedit_card_review"]["application_status"] == "applied"
    matching = [row for row in issues if "Unsupported source-target finding" in row["message"]]
    assert len(matching) == 1 and matching[0]["blocking"] and matching[0]["evidence"]["unverified"]
    assert not source_hold
    assert result.course["lessons"][0]["content"] == lesson["content"]
    assert result.course["lessons"][0]["questions"][1:] == lesson["questions"][1:]
