import copy
import json
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_source_alignment import build_source_alignment_goals
from app.modules.ai.v3.practical_source_semantics import compile_source_semantics, compile_source_semantics_verification
from tests.unit.test_v3_rule_editorial_contract import case


def corrected_case():
    packet, course, verified = case()
    initial = verified["original_reading"]
    raw = copy.deepcopy(verified["raw_checks"])
    replacement = copy.deepcopy(initial["original"]["sections"][0]["rules"][0])
    replacement["conditions"][0]["applies_to"] = "loan"
    raw["rule_checks"][0].update(status="REVISE", replacement=[replacement], reason="The condition modifies the loan.")
    return packet, course, compile_source_semantics_verification(raw, packet, initial)


def test_source_correction_is_goal_not_course_error_and_preserves_inputs():
    packet, course, reading = corrected_case()
    before = copy.deepcopy((course, reading))
    result = build_source_alignment_goals(packet, reading, course)
    assert result["target_lesson_ids"] == ["l1"] and result["unmapped_rule_ids"] == []
    goal = result["goals"][0]
    assert goal["rule_id"] == "R1" and goal["reason"] == "The condition modifies the loan."
    assert goal["before"]["conditions"][0]["applies_to"] == "credit"
    assert goal["after"]["conditions"][0]["applies_to"] == "loan"
    assert "not a finding" in goal["instruction"] and (course, reading) == before


def test_unmapped_never_grants_global_rewrite_and_source_identity_is_checked():
    packet, course, reading = corrected_case()
    course["lessons"][0]["questions"][0]["source_refs"] = [packet.blocks[-1].block_id]
    # A one-block synthetic packet cannot demonstrate an unmapped valid ref; add a question-free lesson mapping by
    # using a source packet with distinct blocks in the dedicated test below.
    altered = copy.deepcopy(reading)
    altered["interpretations"][0]["reason"] = "forged"
    with pytest.raises(ValueError):
        build_source_alignment_goals(packet, altered, course)


def test_quote_only_revision_does_not_create_goal():
    packet, course, verified = case()
    initial = verified["original_reading"]
    raw = copy.deepcopy(verified["raw_checks"])
    replacement = copy.deepcopy(initial["original"]["sections"][0]["rules"][0])
    replacement["source_quote"] = "credit"
    raw["rule_checks"][0].update(status="REVISE", replacement=[replacement], reason="Exact quote corrected.")
    result = build_source_alignment_goals(packet, compile_source_semantics_verification(raw, packet, initial), course)
    assert result == {"goals": [], "target_lesson_ids": [], "unmapped_rule_ids": []}


def test_distinct_source_refs_require_explicit_mapping():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    docs = tuple(
        DirectSourceDocument(f"d{i}", "Title", "f", "general", "r1", (), source_text=t)
        for i, t in enumerate(("First source rule.", "Second source rule."))
    )
    packet = build_practical_source_packet(DirectSourceCorpus("t", docs, 33, 0))
    first, second = packet.blocks

    def rule(ref, quote):
        return {
            "source_refs": [ref],
            "source_quote": quote,
            "actor": "a",
            "action": "do",
            "object": "x",
            "modality": "must",
            "conditions": [],
            "alternatives": [],
            "limits": [],
        }

    raw = {
        "source_fingerprint": packet.fingerprint,
        "sections": [{"section": "s", "rules": [rule(first.block_id, first.text)]}],
        "uncertainties": [],
    }
    initial = compile_source_semantics(raw, packet)
    replacement = copy.deepcopy(raw["sections"][0]["rules"][0])
    replacement["object"] = "y"
    check = {
        "source_fingerprint": packet.fingerprint,
        "reading_fingerprint": initial["reading_fingerprint"],
        "additional_rules": [],
        "rule_checks": [
            {
                "rule_id": "R1",
                "status": "REVISE",
                "reason": "Correction",
                "replacement": [replacement],
                "source_question": "",
            }
        ],
    }
    verified = compile_source_semantics_verification(check, packet, initial)
    course = {
        "title": "c",
        "lessons": [
            {
                "id": "l",
                "title": "lesson",
                "content": "Text",
                "questions": [
                    {
                        "id": "q",
                        "prompt": "Question?",
                        "choices": ["a", "b", "c"],
                        "correct_index": 0,
                        "explanation": "Reason",
                        "source_refs": [second.block_id],
                    }
                ],
            }
        ],
    }
    result = build_source_alignment_goals(packet, verified, course)
    assert (
        result["target_lesson_ids"] == []
        and result["unmapped_rule_ids"] == ["R1"]
        and result["goals"][0]["lesson_ids"] == []
    )


def test_saved_model_grammar_correction_maps_to_source_linked_lesson():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    path = Path(__file__).parents[1] / "fixtures/v3/source-qualifier-model-revision.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    text = fixture["reading"]["source_quote"]
    doc = DirectSourceDocument("doc", "Instruction", "source", "general", "immutable", (), source_text=text)
    packet = build_practical_source_packet(DirectSourceCorpus("tenant", (doc,), len(text), 0))
    source_ref = packet.blocks[0].block_id
    original = copy.deepcopy(fixture["reading"])
    original["source_refs"] = [source_ref]
    raw = {
        "source_fingerprint": packet.fingerprint,
        "sections": [{"section": "Assessment", "rules": [original]}],
        "uncertainties": [],
    }
    initial = compile_source_semantics(raw, packet)
    check = copy.deepcopy(fixture["verification"])
    check["rule_id"] = "R1"
    check["replacement"][0]["source_refs"] = [source_ref]
    checks = {
        "source_fingerprint": packet.fingerprint,
        "reading_fingerprint": initial["reading_fingerprint"],
        "rule_checks": [check],
        "additional_rules": [],
    }
    verified = compile_source_semantics_verification(checks, packet, initial)
    course = {
        "title": "Course",
        "lessons": [
            {
                "id": "lesson",
                "title": "Lesson",
                "content": "Teaching text.",
                "questions": [
                    {
                        "id": "question",
                        "prompt": "Question?",
                        "choices": ["A", "B", "C"],
                        "correct_index": 0,
                        "explanation": "Explanation",
                        "source_refs": [source_ref],
                    }
                ],
            }
        ],
    }
    result = build_source_alignment_goals(packet, verified, course)
    goal = result["goals"][0]
    assert goal["rule_id"] == "R1" and goal["lesson_ids"] == ["lesson"]
    assert goal["reason"] == fixture["verification"]["reason"]
    assert goal["before"] == original and goal["after"] == check["replacement"][0]
    assert result["target_lesson_ids"] == ["lesson"] and result["unmapped_rule_ids"] == []


def test_completeness_addition_maps_without_asserting_course_defect():
    from app.modules.ai.v3.practical_source_semantics import compile_source_completeness

    packet, course, grammar = case()
    before = copy.deepcopy((course, grammar))
    second_action = copy.deepcopy(grammar["interpretations"][0]["rule"])
    second_action["action"] = "record independent action"
    payload = {
        "source_fingerprint": packet.fingerprint,
        "verified_reading_fingerprint": grammar["verified_reading_fingerprint"],
        "additional_rules": [{"section": "Additional action", "rule": second_action}],
    }
    completed = compile_source_completeness(payload, packet, grammar)
    assert completed["interpretations"][: len(grammar["interpretations"])] == grammar["interpretations"]
    result = build_source_alignment_goals(packet, completed, course)
    assert len(result["goals"]) == 1
    goal = result["goals"][0]
    assert goal["rule_id"] == "R3" and goal["origin"] == "SOURCE_COMPLETENESS_ADDITION"
    assert goal["before"] == {} and goal["after"] == second_action and goal["lesson_ids"] == ["l1"]
    assert goal["reason"] == completed["interpretations"][-1]["reason"]
    assert "not a finding" in goal["instruction"] and "representative questions" in goal["instruction"]
    assert (course, grammar) == before
