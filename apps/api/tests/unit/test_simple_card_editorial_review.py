import copy
import json
from dataclasses import replace

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_card_editorial_review import card_editorial_review_request, compile_card_editorial_review
from tests.unit.test_v3_simple_course_editor import course
from tests.unit.test_v3_simple_course_editor_v2 import approved_fixture


@pytest.fixture
def example():
    corpus, packet, _ = approved_fixture()
    original = course(ref=packet.blocks[0].block_id, content="HIDDEN_BODY_SENTINEL")
    original["lessons"][0]["questions"][0]["explanation"] = "HIDDEN_EXPLANATION_SENTINEL"
    nav = [{"lesson_id": lesson["id"], "source_refs": [packet.blocks[0].block_id]} for lesson in original["lessons"]]
    messages, fmt, context = card_editorial_review_request(packet, corpus, {}, original, nav)
    response = {
        "source_fingerprint": packet.fingerprint,
        "course_fingerprint": _digest(original),
        "summary": "Literal review",
        "findings": [],
        "source_notes": [],
        "narrative_sources": {lesson["id"]: ["SRC1"] for lesson in original["lessons"]},
    }
    return corpus, packet, original, nav, messages, fmt, context, response


def test_measured_projection_and_approved_decisions_are_isolated(example):
    _, _, original, _, messages, fmt, _, _ = example
    payload = json.loads(messages[1]["content"])
    assert "HIDDEN_BODY_SENTINEL" not in messages[1]["content"]
    assert "HIDDEN_EXPLANATION_SENTINEL" not in messages[1]["content"]
    assert "correct_index" not in messages[1]["content"] and "PREVIOUS_FINDINGS" not in messages[1]["content"]
    assert "replacement interpretation reason" in messages[1]["content"]
    assert "keep interpretation reason" in messages[1]["content"]
    assert "OLD_PRIVATE_WORD" not in messages[1]["content"] and "CURRENT_WORD" in messages[1]["content"]
    card = payload["unapproved_question_cards"][0]
    assert set(card) == {"id", "lesson_id", "lesson_title", "prompt", "choices"}
    assert card["lesson_title"] == original["lessons"][0]["title"]
    assert fmt["json_schema"]["name"] == "v3_practical_editorial_review_v2"


def test_clean_review_and_distinct_duplicate_and_source_findings_are_retained(example):
    _, packet, original, _, _, _, context, response = example
    assert compile_card_editorial_review(response, packet, original, context)["findings"] == []
    question = original["lessons"][0]["questions"][0]["id"]
    finding = {
        "domain": "assessment",
        "severity": "material",
        "target": {"kind": "question", "id": question},
        "problem": "Problem one",
        "basis": "Source",
        "correction": "Check",
        "source_refs": ["SRC1"],
    }
    other = {**finding, "problem": "Different issue"}
    source = {**finding, "domain": "source", "target": {"kind": "source", "id": "SRC1"}}
    response["findings"] = [finding, copy.deepcopy(finding), other, source]
    response["source_notes"] = [{"note": "Unverified source note", "source_refs": ["SRC1"]}]
    result = compile_card_editorial_review(response, packet, original, context)
    assert len(result["findings"]) == 4 and result["findings"][0] == result["findings"][1]
    assert result["findings"][2]["problem"] == "Different issue"
    assert result["findings"][3]["target"]["id"] == packet.blocks[0].block_id
    assert result["source_notes"][0]["source_refs"] == [packet.blocks[0].block_id]


@pytest.mark.parametrize("fault", ["course", "source", "card", "payload", "navigation", "ref", "target", "body_scope"])
def test_stale_foreign_or_out_of_scope_rejected(example, fault):
    _, packet, original, _, _, _, context, response = example
    if fault == "course":
        original["lessons"][0]["content"] += " changed"
    elif fault == "source":
        context = replace(context, source_fingerprint="0" * 64)
    elif fault == "card":
        original["lessons"][0]["questions"][0]["prompt"] += " changed"
    elif fault == "payload":
        context = replace(context, payload_json=context.payload_json + " ")
    elif fault == "navigation":
        context = replace(context, navigation_json="[]")
    else:
        question = original["lessons"][0]["questions"][0]["id"]
        finding = {
            "domain": "assessment",
            "severity": "material",
            "target": {"kind": "question", "id": question},
            "problem": "Problem",
            "basis": "Source",
            "correction": "Check",
            "source_refs": ["SRC1"],
        }
        if fault == "ref":
            finding["source_refs"] = ["SRC999"]
        elif fault == "target":
            finding["target"]["id"] = "foreign"
        else:
            finding["domain"], finding["target"] = "content", {"kind": "lesson", "id": original["lessons"][0]["id"]}
        response["findings"] = [finding]
    with pytest.raises(ValueError):
        compile_card_editorial_review(response, packet, original, context)


@pytest.mark.parametrize("fault", ["foreign_ref", "missing_lesson", "duplicate_lesson", "duplicate_ref"])
def test_navigation_must_be_owned_and_complete(example, fault):
    corpus, packet, original, nav, *_ = example
    if fault == "foreign_ref":
        nav[0]["source_refs"] = ["foreign"]
    elif fault == "missing_lesson":
        nav.clear()
    elif fault == "duplicate_lesson":
        nav.append(copy.deepcopy(nav[0]))
    else:
        nav[0]["source_refs"].append(nav[0]["source_refs"][0])
    with pytest.raises(ValueError):
        card_editorial_review_request(packet, corpus, {}, original, nav)
