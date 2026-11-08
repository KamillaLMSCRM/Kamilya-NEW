import copy

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_semantics import (
    compile_source_semantics,
    compile_source_semantics_verification,
    is_source_semantics_format,
    is_source_semantics_verification_format,
    matches_source_semantics,
    matches_source_semantics_verification,
    source_semantics_context,
    source_semantics_format,
    source_semantics_verification_format,
)


def packet(text="A credit for personal use requires assessment. The manager checks records."):
    doc = DirectSourceDocument("doc", "Title", "f", "general", "r1", (), source_text=text)
    return build_practical_source_packet(DirectSourceCorpus("tenant", (doc,), len(text), 0))


def reading(p):
    ref = p.blocks[0].block_id

    def rule(quote):
        return {
            "source_refs": [ref],
            "source_quote": quote,
            "actor": "manager",
            "action": "assess",
            "object": "credit",
            "conditions": [{"applies_to": "credit", "expression": "personal use"}],
            "modality": "must",
            "alternatives": [],
            "limits": [],
        }

    return {
        "source_fingerprint": p.fingerprint,
        "sections": [
            {"section": "working rules", "rules": [rule("credit for personal use"), rule("manager checks records")]}
        ],
        "uncertainties": [{"source_refs": [ref], "source_quote": "manager checks records", "question": "Who checks?"}],
    }


def verification(p, r):
    return {
        "source_fingerprint": p.fingerprint,
        "reading_fingerprint": r["reading_fingerprint"],
        "additional_rules": [],
        "rule_checks": [
            {
                "rule_id": rule["rule_id"],
                "status": "SUPPORTED",
                "reason": "Condition modifies the credit.",
                "replacement": [],
                "source_question": "",
            }
            for s in r["sections"]
            for rule in s["rules"]
        ],
    }


def test_read_format_identity_custody_and_view():
    p = packet()
    v = reading(p)
    fmt = source_semantics_format(p)
    assert is_source_semantics_format(fmt) and matches_source_semantics(v, fmt)
    view = PracticalModelView(p)
    assert matches_source_semantics(view.encode(v), view.schema(fmt))
    r = compile_source_semantics(v, p)
    assert [x["rule_id"] for x in r["sections"][0]["rules"]] == ["R1", "R2"]
    bad = copy.deepcopy(v)
    bad["sections"][0]["rules"][0]["source_quote"] = "fabricated"
    out = compile_source_semantics(bad, p)
    assert not out["sections"][0]["rules"][0]["custody_valid"] and out["sections"][0]["rules"][1]["custody_valid"]
    bad = copy.deepcopy(v)
    bad["sections"][0]["rules"][0]["source_refs"] = ["foreign"]
    with pytest.raises(ValueError):
        compile_source_semantics(bad, p)
    with pytest.raises(ValueError):
        compile_source_semantics(v, packet("Different source."))
    bad = copy.deepcopy(fmt)
    bad["json_schema"]["schema"]["additionalProperties"] = True
    assert not is_source_semantics_format(bad)


def test_verification_requires_exact_ids_and_current_reading():
    p = packet()
    r = compile_source_semantics(reading(p), p)
    v = verification(p, r)
    fmt = source_semantics_verification_format(p, r)
    assert is_source_semantics_verification_format(fmt) and matches_source_semantics_verification(v, fmt)
    assert matches_source_semantics_verification(PracticalModelView(p).encode(v), PracticalModelView(p).schema(fmt))
    for mode in ("missing", "duplicate", "foreign", "drift"):
        bad = copy.deepcopy(v)
        if mode == "missing":
            bad["rule_checks"].pop()
        if mode == "duplicate":
            bad["rule_checks"][1]["rule_id"] = "R1"
        if mode == "foreign":
            bad["rule_checks"][1]["rule_id"] = "R3"
        if mode == "drift":
            bad["reading_fingerprint"] = "0" * 64
        with pytest.raises(ValueError):
            compile_source_semantics_verification(bad, p, r)
    mutated = copy.deepcopy(r)
    mutated["sections"][0]["rules"][0]["object"] = "borrower"
    with pytest.raises(ValueError):
        source_semantics_verification_format(p, mutated)


def test_revision_individual_bad_custody_and_sibling_preserved():
    p = packet()
    raw = reading(p)
    r = compile_source_semantics(raw, p)
    before = copy.deepcopy(r)
    v = verification(p, r)
    replacement = copy.deepcopy(raw["sections"][0]["rules"][0])
    replacement["source_quote"] = "invented"
    v["rule_checks"][0].update(status="REVISE", replacement=[replacement])
    out = compile_source_semantics_verification(v, p, r)
    assert r == before and out["original_reading"] == before
    first, second = out["interpretations"]
    assert first["status"] == "REVISE" and first["rule"]["source_quote"] == p.blocks[0].text
    assert first["model_quote_valid"] is False and first["generated_source_quote"] == "invented"
    assert first["quote_origin"] == "FIRST_OWNED_SOURCE_BLOCK"
    assert out["raw_checks"]["rule_checks"][0]["replacement"][0]["source_quote"] == "invented"
    assert "invented" not in source_semantics_context(out, PracticalModelView(p))
    assert second["status"] == "SUPPORTED" and second["reason"] == "Condition modifies the credit."
    replacement["source_quote"] = "credit for personal use"
    replacement["object"] = "loan"
    v["rule_checks"][0]["replacement"] = [replacement]
    out = compile_source_semantics_verification(v, p, r)
    assert out["interpretations"][0]["rule"]["object"] == "loan" and r == before
    context = source_semantics_context(out, PracticalModelView(p))
    assert (
        "source_quote" not in context
        and "Condition modifies the credit." in context
        and "not source authority" in context
    )


def test_source_ambiguity_distinct_from_invalid_custody():
    p = packet()
    raw = reading(p)
    raw["sections"][0]["rules"][0]["source_quote"] = "wrong"
    r = compile_source_semantics(raw, p)
    v = verification(p, r)
    v["rule_checks"][0].update(status="SOURCE_AMBIGUITY", source_question="Which case applies?")
    out = compile_source_semantics_verification(v, p, r)
    assert out["interpretations"][0]["status"] == "UNVERIFIED" and out["interpretations"][0]["source_question"] == ""
    assert out["interpretations"][1]["status"] == "SUPPORTED"
    v["rule_checks"][0]["source_question"] = ""
    with pytest.raises(ValueError):
        compile_source_semantics_verification(v, p, r)


def test_passive_actor_may_be_unstated_without_inventing_identity():
    p = packet()
    raw = reading(p)
    raw["sections"][0]["rules"][0]["actor"] = ""
    assert compile_source_semantics(raw, p)["sections"][0]["rules"][0]["actor"] == ""
    raw["sections"][0]["rules"][0]["action"] = ""
    raw["sections"][0]["rules"][0]["object"] = ""
    with pytest.raises(ValueError):
        compile_source_semantics(raw, p)


def test_context_adds_stable_condition_ids_without_mutating_reading():
    import json

    p = packet()
    initial = compile_source_semantics(reading(p), p)
    result = compile_source_semantics_verification(verification(p, initial), p, initial)
    before = copy.deepcopy(result)
    context = source_semantics_context(result, PracticalModelView(p))
    payload = json.loads(context.split("\n")[2])
    assert payload["interpretations"][0]["rule"]["conditions"][0]["condition_id"] == "R1.C1"
    assert payload["interpretations"][1]["rule"]["conditions"][0]["condition_id"] == "R2.C1"
    assert result == before
    assert result["reading_fingerprint"] == before["reading_fingerprint"]
    assert "condition_id" not in result["interpretations"][0]["rule"]["conditions"][0]


def test_verifier_adds_missing_rule_without_changing_original_or_existing_rules():
    p = packet()
    initial = compile_source_semantics(reading(p), p)
    before = copy.deepcopy(initial)
    value = verification(p, initial)
    new_rule = copy.deepcopy(initial["original"]["sections"][0]["rules"][1])
    new_rule.update(action="prevent", object="conflict", source_quote="manager checks records")
    new_rule["conditions"] = [{"applies_to": "conflict", "expression": "when identified"}]
    value["additional_rules"] = [{"section": "Additional duty", "rule": new_rule}]
    result = compile_source_semantics_verification(value, p, initial)
    assert initial == before and result["original_reading"] == before and result["raw_checks"] == value
    assert [x["rule_id"] for x in result["interpretations"]] == ["R1", "R2", "R3"]
    assert result["interpretations"][2]["provenance"] == "SOURCE_VERIFIER_ADDITION"
    assert result["interpretations"][2]["custody_valid"]
    assert result["interpretations"][0]["rule"] == before["original"]["sections"][0]["rules"][0]
    context = source_semantics_context(result)
    assert "R3.C1" in context and result["reading_fingerprint"] == before["reading_fingerprint"]


def test_invalid_added_quote_or_reference_remains_technical_unverified():
    p = packet()
    initial = compile_source_semantics(reading(p), p)
    for mode in ("quote", "reference"):
        value = verification(p, initial)
        new_rule = copy.deepcopy(initial["original"]["sections"][0]["rules"][0])
        if mode == "quote":
            new_rule["source_quote"] = "not found"
        if mode == "reference":
            new_rule["source_refs"] = ["foreign"]
        value["additional_rules"] = [{"section": "New rule", "rule": new_rule}]
        result = compile_source_semantics_verification(value, p, initial)
        added = result["interpretations"][2]
        if mode == "quote":
            assert added["status"] == "SUPPORTED" and added["custody_valid"]
            assert added["rule"]["source_quote"] == p.blocks[0].text
            assert added["model_quote_valid"] is False and added["generated_source_quote"] == "not found"
            assert "not found" not in source_semantics_context(result)
            assert {k: v for k, v in added["rule"].items() if k != "source_quote"} == {
                k: v for k, v in new_rule.items() if k != "source_quote"
            }
        else:
            assert added["status"] == "UNVERIFIED" and not added["custody_valid"]
        assert added["source_question"] == "" and result["interpretations"][0]["status"] == "SUPPORTED"


def test_verified_reading_identity_changes_for_same_original_and_rejects_tamper():
    from app.modules.ai.v3.practical_source_semantics import source_semantics_final_rules

    p = packet()
    initial = compile_source_semantics(reading(p), p)
    first = verification(p, initial)
    second = copy.deepcopy(first)
    second["additional_rules"] = [
        {"section": "Added", "rule": copy.deepcopy(initial["original"]["sections"][0]["rules"][0])}
    ]
    a = compile_source_semantics_verification(first, p, initial)
    b = compile_source_semantics_verification(second, p, initial)
    assert a["reading_fingerprint"] == b["reading_fingerprint"]
    assert a["verified_reading_fingerprint"] != b["verified_reading_fingerprint"]
    tampered = copy.deepcopy(b)
    tampered["interpretations"][-1]["rule"]["object"] = "altered"
    with pytest.raises(ValueError):
        source_semantics_final_rules(p, tampered)


def test_quote_resolver_requires_all_refs_owned_and_is_deterministic():
    from app.modules.ai.v3.practical_source_semantics import source_semantics_final_rules

    p = packet()
    initial = compile_source_semantics(reading(p), p)
    value = verification(p, initial)
    added = copy.deepcopy(initial["original"]["sections"][0]["rules"][0])
    added["source_refs"] = [p.blocks[0].block_id, "foreign"]
    added["source_quote"] = p.blocks[0].text
    value["additional_rules"] = [{"section": "Additional", "rule": added}]
    result = compile_source_semantics_verification(value, p, initial)
    assert not result["interpretations"][2]["custody_valid"]
    assert result["interpretations"][2]["status"] == "UNVERIFIED"
    assert source_semantics_final_rules(p, result) == result["interpretations"]
    bad = copy.deepcopy(result)
    bad["interpretations"][2]["custody_valid"] = True
    with pytest.raises(ValueError):
        source_semantics_final_rules(p, bad)


def test_invalid_original_supported_rule_gets_owned_literal_without_semantic_change():
    p = packet()
    raw = reading(p)
    raw["sections"][0]["rules"][0]["source_quote"] = "paraphrased"
    initial = compile_source_semantics(raw, p)
    checks = verification(p, initial)
    result = compile_source_semantics_verification(checks, p, initial)
    row = result["interpretations"][0]
    assert row["rule"]["source_quote"] == p.blocks[0].text
    assert row["model_quote_valid"] is False and row["generated_source_quote"] == "paraphrased"
    assert {k: v for k, v in row["rule"].items() if k != "source_quote"} == {
        k: v for k, v in raw["sections"][0]["rules"][0].items() if k != "source_quote"
    }
    assert all(
        term not in source_semantics_context(result) for term in ("paraphrased", "model_quote_valid", "quote_origin")
    )


def test_additive_completeness_preserves_corrected_grammar_and_lineage():
    from app.modules.ai.v3.practical_source_semantics import (
        compile_source_completeness,
        source_completeness_format,
        source_semantics_final_rules,
    )

    p = packet()
    original = compile_source_semantics(reading(p), p)
    checks = verification(p, original)
    corrected = copy.deepcopy(original["original"]["sections"][0]["rules"][0])
    corrected["conditions"][0]["applies_to"] = "credit"
    checks["rule_checks"][0].update(
        status="REVISE", replacement=[corrected], reason="The condition applies to the credit."
    )
    grammar = compile_source_semantics_verification(checks, p, original)
    before = copy.deepcopy(grammar)
    addition = copy.deepcopy(corrected)
    addition["action"] = "record"
    addition["object"] = "approval"
    payload = {
        "source_fingerprint": p.fingerprint,
        "verified_reading_fingerprint": grammar["verified_reading_fingerprint"],
        "additional_rules": [{"section": "Other duty", "rule": addition}],
    }
    result = compile_source_completeness(payload, p, grammar)
    assert (
        grammar == before and result["interpretations"][: len(grammar["interpretations"])] == grammar["interpretations"]
    )
    assert result["interpretations"][0]["rule"]["conditions"][0]["applies_to"] == "credit"
    assert result["interpretations"][-1]["rule_id"] == "R3"
    assert result["interpretations"][-1]["provenance"] == "SOURCE_COMPLETENESS_ADDITION"
    assert result["completeness_lineage"] == {"previous": before, "raw": payload}
    assert (
        result["raw_checks"] == checks
        and result["verified_reading_fingerprint"] != grammar["verified_reading_fingerprint"]
    )
    assert source_semantics_final_rules(p, result) == result["interpretations"]
    for mode in ("wrong_fp", "foreign_ref", "overwrite", "missing_fp"):
        bad = copy.deepcopy(payload)
        if mode == "wrong_fp":
            bad["verified_reading_fingerprint"] = "0" * 64
        if mode == "foreign_ref":
            bad["additional_rules"][0]["rule"]["source_refs"] = ["foreign"]
        if mode == "overwrite":
            bad["interpretations"] = []
        if mode == "missing_fp":
            del bad["verified_reading_fingerprint"]
        with pytest.raises(ValueError):
            compile_source_completeness(bad, p, grammar)
    tampered = copy.deepcopy(result)
    tampered["interpretations"][0]["rule"]["conditions"][0]["applies_to"] = "person"
    with pytest.raises(ValueError):
        source_semantics_final_rules(p, tampered)
    with pytest.raises(ValueError):
        source_completeness_format(p, result)


def test_completeness_zero_additions_and_wire_checker():
    import importlib.util
    from pathlib import Path

    from app.modules.ai.v3.practical_source_semantics import compile_source_completeness, source_completeness_format

    p = packet()
    initial = compile_source_semantics(reading(p), p)
    grammar = compile_source_semantics_verification(verification(p, initial), p, initial)
    payload = {
        "source_fingerprint": p.fingerprint,
        "verified_reading_fingerprint": grammar["verified_reading_fingerprint"],
        "additional_rules": [],
    }
    result = compile_source_completeness(payload, p, grammar)
    assert (
        result["interpretations"] == grammar["interpretations"] and result["uncertainties"] == grammar["uncertainties"]
    )
    spec = importlib.util.spec_from_file_location(
        "completeness_test_runner", Path(__file__).resolve().parents[4] / "infra/codex-reserve/runner.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    fmt = source_completeness_format(p, grammar)
    assert runner._checked_structured_format(fmt) == fmt["json_schema"]["schema"]
