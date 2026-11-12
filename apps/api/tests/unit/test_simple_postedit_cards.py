import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.simple_postedit_cards import apply_postedit_cards, prepare_postedit_cards
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


@pytest.fixture
def example():
    corpus = synthetic_corpus("tenant", mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    ref = packet.blocks[0].block_id
    original = unit_course(ref, "BODY_PRIVATE")
    lesson = original["lessons"][0]
    lesson["questions"][2]["prompt"] = "UNFLAGGED_PRIVATE"
    findings = [
        {
            "domain": "assessment",
            "severity": "material",
            "target": {"kind": "question", "id": q["id"]},
            "problem": "Question may be unclear",
            "basis": "Source evidence",
            "correction": "Check question",
            "source_refs": [ref],
        }
        for q in lesson["questions"][:2]
    ]
    review = {
        "source_fingerprint": packet.fingerprint,
        "course_fingerprint": _digest(original),
        "summary": "Review",
        "findings": findings,
        "source_notes": [],
        "narrative_sources": {lesson["id"]: [ref]},
    }
    messages, fmt, context = prepare_postedit_cards(packet, corpus, {}, original, review)
    value = {
        "source_fingerprint": packet.fingerprint,
        "draft_fingerprint": _digest(original),
        "body_edits": [],
        "title_edits": [],
        "question_edits": [],
        "added_lessons": [],
        "source_questions": [],
        "lesson_sources": copy.deepcopy(context["lesson_sources"]),
        "finding_dispositions": [],
    }
    return packet, corpus, original, review, messages, fmt, context, value


def test_request_contains_only_flagged_complete_cards_and_keeps_source_context(example):
    packet, _, original, _, messages, fmt, context, _ = example
    payload = json.loads(messages[1]["content"])
    assert "BODY_PRIVATE" not in messages[1]["content"] and "UNFLAGGED_PRIVATE" not in messages[1]["content"]
    assert len(payload["flagged_cards"]) == 2
    assert all(set(row) == {"lesson_id", "lesson_title", "question"} for row in payload["flagged_cards"])
    assert payload["flagged_cards"][0]["question"]["id"] == original["lessons"][0]["questions"][0]["id"]
    assert fmt["json_schema"]["name"] == "simple_course_block_editor_v2"
    assert context["source_fingerprint"] == packet.fingerprint


def test_targeted_fix_preserves_unflagged_and_unresolved_peer(example):
    packet, _, original, review, _, _, context, value = example
    updated = copy.deepcopy(original["lessons"][0]["questions"][0])
    updated["prompt"] = "Corrected prompt"
    value["question_edits"] = [updated]
    envelope, receipt = apply_postedit_cards(value, packet, original, context)
    lesson = envelope["course"]["lessons"][0]
    assert lesson["content"] == original["lessons"][0]["content"] and lesson["title"] == original["lessons"][0]["title"]
    assert lesson["questions"][0] == updated and lesson["questions"][1:] == original["lessons"][0]["questions"][1:]
    assert receipt["review"] == review and len(receipt["finding_dispositions"]) == 2
    assert all(row["status"] == "UNVERIFIED" and not row["model_resolved"] for row in receipt["finding_dispositions"])


def test_noop_false_finding_can_have_supported_disposition(example):
    packet, _, original, _, _, _, context, value = example
    question = original["lessons"][0]["questions"][0]
    source = next(b.text for b in packet.blocks if b.block_id == context["findings"][0]["finding"]["source_refs"][0])
    value["finding_dispositions"] = [
        {
            "finding_id": context["findings"][0]["id"],
            "status": "NOT_MATERIAL",
            "reason": "Already correct",
            "source_refs": context["findings"][0]["finding"]["source_refs"],
            "source_quote": source.strip(),
            "target": {"kind": "question_prompt", "id": question["id"], "choice_index": 0},
            "final_quote": question["prompt"],
        }
    ]
    envelope, receipt = apply_postedit_cards(value, packet, original, context)
    assert envelope["course"] == original and receipt["finding_dispositions"][0]["model_resolved"]
    assert not receipt["finding_dispositions"][1]["model_resolved"] and not receipt["semantic_approval"]


def test_source_findings_and_returned_source_questions_remain_available(example):
    packet, corpus, original, review, _, _, _, _ = example
    ref = packet.blocks[0].block_id
    source_finding = {
        "domain": "source",
        "severity": "material",
        "target": {"kind": "source", "id": ref},
        "problem": "Source ambiguity",
        "basis": "Source",
        "correction": "Human review",
        "source_refs": [ref],
    }
    review["findings"].append(source_finding)
    _, _, context = prepare_postedit_cards(packet, corpus, {}, original, review)
    value = {
        "source_fingerprint": packet.fingerprint,
        "draft_fingerprint": _digest(original),
        "body_edits": [],
        "title_edits": [],
        "question_edits": [],
        "added_lessons": [],
        "source_questions": [{"question": "Source ambiguity", "source_refs": [ref]}],
        "lesson_sources": copy.deepcopy(context["lesson_sources"]),
        "finding_dispositions": [],
    }
    envelope, receipt = apply_postedit_cards(value, packet, original, context)
    assert source_finding in receipt["review"]["findings"]
    assert envelope["source_questions"] == value["source_questions"]


def test_complete_target_card_may_correct_only_its_answer_key_without_semantic_approval(example):
    packet, _, original, _, _, _, context, value = example
    updated = copy.deepcopy(original["lessons"][0]["questions"][0])
    updated["correct_index"] = (updated["correct_index"] + 1) % len(updated["choices"])
    value["question_edits"] = [updated]
    envelope, receipt = apply_postedit_cards(value, packet, original, context)
    assert envelope["course"]["lessons"][0]["questions"][0] == updated
    assert envelope["course"]["lessons"][0]["questions"][1:] == original["lessons"][0]["questions"][1:]
    assert not receipt["semantic_approval"]
    assert all(row["status"] == "UNVERIFIED" for row in receipt["finding_dispositions"])


@pytest.mark.parametrize(
    "fault",
    [
        "body",
        "title",
        "added",
        "unflagged",
        "foreign",
        "duplicate",
        "partial_key",
        "source",
        "draft",
        "context",
        "sources",
    ],
)
def test_out_of_scope_or_stale_edits_are_rejected(example, fault):
    packet, _, original, _, _, _, context, value = example
    if fault == "body":
        value["body_edits"] = [{"block_id": "BODY1", "after": "changed"}]
    elif fault == "title":
        value["title_edits"] = [{"lesson_id": original["lessons"][0]["id"], "title": "changed"}]
    elif fault == "added":
        value["added_lessons"] = [copy.deepcopy(original["lessons"][0])]
    elif fault in ("unflagged", "foreign", "duplicate", "partial_key"):
        q = copy.deepcopy(original["lessons"][0]["questions"][2 if fault == "unflagged" else 0])
        if fault == "foreign":
            q["id"] = "foreign"
        elif fault == "partial_key":
            q = {"id": q["id"], "correct_index": 1}
        else:
            q["prompt"] = "changed"
        value["question_edits"] = [q, copy.deepcopy(q)] if fault == "duplicate" else [q]
    elif fault == "source":
        value["source_fingerprint"] = "0" * 64
    elif fault == "draft":
        value["draft_fingerprint"] = "0" * 64
    elif fault == "context":
        context["allowed_question_ids"].append("foreign")
    else:
        value["lesson_sources"] = []
    with pytest.raises(ValueError):
        apply_postedit_cards(value, packet, original, context)
