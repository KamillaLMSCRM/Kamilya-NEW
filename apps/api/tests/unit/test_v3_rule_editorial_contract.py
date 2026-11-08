import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_rule_editorial_contract import (
    compile_rule_editorial_review,
    compile_rule_editorial_verification,
    is_rule_editorial_review_format,
    is_rule_editorial_verification_format,
    matches_rule_editorial_review,
    rule_editorial_review_format,
    rule_editorial_verification_format,
)
from app.modules.ai.v3.practical_source_semantics import compile_source_semantics, compile_source_semantics_verification
from tests.unit.test_v3_source_semantics import packet, reading, verification


def case():
    p = packet()
    initial = compile_source_semantics(reading(p), p)
    r = compile_source_semantics_verification(verification(p, initial), p, initial)
    course = {
        "title": "Course",
        "lessons": [
            {
                "id": "l1",
                "title": "One",
                "content": "A credit for personal use requires assessment.",
                "questions": [
                    {
                        "id": "q1",
                        "prompt": "manager checks records",
                        "choices": ["A", "B", "C"],
                        "correct_index": 0,
                        "explanation": "manager checks records",
                        "source_refs": [p.blocks[0].block_id],
                    }
                ],
            }
        ],
    }
    return p, course, r


def response(p, course, r):
    return {
        "source_fingerprint": p.fingerprint,
        "course_fingerprint": _digest(course),
        "reading_fingerprint": r["verified_reading_fingerprint"],
        "summary": "Reviewed",
        "findings": [],
        "source_notes": [],
        "narrative_sources": {"l1": [p.blocks[0].block_id]},
        "source_rule_checks": [
            {
                "rule_id": f"R{i}",
                "status": "SUPPORTED",
                "lesson_quotes": [{"lesson_id": "l1", "quote": "credit for personal use"}],
                "condition_checks": [
                    {
                        "condition_id": f"R{i}.C1",
                        "taught_applies_to": "credit",
                        "taught_expression": "personal use",
                        "scope_equivalent": "YES",
                        "reason": "Scope preserved.",
                    }
                ],
                "reason": "Compared the source and teaching.",
                "correction": "No correction.",
                "severity": "material",
            }
            for i in (1, 2)
        ],
    }


def test_compact_format_binding_and_unknown_ref_rejected_server_side():
    p, c, r = case()
    value = response(p, c, r)
    fmt = rule_editorial_review_format(p, c, r)
    assert is_rule_editorial_review_format(fmt) and matches_rule_editorial_review(value, fmt)
    assert compile_rule_editorial_review(value, p, c, r)["source_rule_checks"][0]["verified"]
    bad = copy.deepcopy(value)
    bad["narrative_sources"]["l1"] = ["foreign"]
    assert matches_rule_editorial_review(bad, fmt)
    with pytest.raises(ValueError):
        compile_rule_editorial_review(bad, p, c, r)
    bad = copy.deepcopy(value)
    bad["course_fingerprint"] = "0" * 64
    with pytest.raises(ValueError):
        compile_rule_editorial_review(bad, p, c, r)
    c2 = copy.deepcopy(c)
    c2["lessons"][0]["content"] = "changed"
    with pytest.raises(ValueError):
        compile_rule_editorial_review(value, p, c2, r)
    bad = copy.deepcopy(r)
    bad["interpretations"][0]["reason"] = "changed"
    with pytest.raises(ValueError):
        rule_editorial_review_format(p, c, bad)


def test_missing_duplicate_and_question_only_quote_remain_open():
    p, c, r = case()
    v = response(p, c, r)
    for mode in ("missing", "duplicate", "foreign"):
        bad = copy.deepcopy(v)
        if mode == "missing":
            bad["source_rule_checks"].pop()
        if mode == "duplicate":
            bad["source_rule_checks"][1]["rule_id"] = "R1"
        if mode == "foreign":
            bad["source_rule_checks"][1]["rule_id"] = "R3"
        with pytest.raises(ValueError):
            compile_rule_editorial_review(bad, p, c, r)
    v["source_rule_checks"][0]["lesson_quotes"][0]["quote"] = "manager checks records"
    out = compile_rule_editorial_review(v, p, c, r)
    assert not out["source_rule_checks"][0]["verified"] and out["source_rule_checks"][1]["verified"]
    assert out["review"]["findings"][0]["source_rule_id"] == "R1"
    assert out["review"]["findings"][0]["rule_check_unverified"]


def test_current_contradiction_blocks_old_resolution_and_preserves_other():
    p, c, r = case()
    v = response(p, c, r)
    v["source_rule_checks"][0].update(status="CONTRADICTED", reason="Wrong object", correction="Fix object")
    initial = compile_rule_editorial_review(v, p, c, r)
    finding = initial["review"]["findings"][0]
    assert finding["target"] == {"kind": "lesson", "id": "l1"} and finding["source_refs"] == [p.blocks[0].block_id]
    v["resolutions"] = [
        {
            "issue_id": finding["issue_id"],
            "disposition": "FIXED",
            "reason": "Resolved",
            "source_refs": [p.blocks[0].block_id],
            "source_quote": "credit for personal use",
            "course_quote": "credit for personal use",
            "source_question": "",
        }
    ]
    fmt = rule_editorial_verification_format(p, c, r, [finding])
    assert is_rule_editorial_verification_format(fmt)
    out = compile_rule_editorial_verification(v, p, c, r, [finding])
    assert (
        not out["resolutions"][0]["verified"]
        and "current_rule_check_open" in out["resolutions"][0]["verification_errors"]
    )
    assert out["source_rule_checks"][1]["verified"]


def test_source_dispute_and_invalid_quote_are_technical_holds():
    p, c, r = case()
    v = response(p, c, r)
    v["source_rule_checks"][0]["status"] = "SOURCE_READING_DISPUTED"
    v["source_rule_checks"][1]["lesson_quotes"][0]["quote"] = "absent"
    out = compile_rule_editorial_review(v, p, c, r)
    assert all(not x["verified"] for x in out["source_rule_checks"])
    assert all(x["domain"] == "content" and x["severity"] == "material" for x in out["review"]["findings"])


def test_rewording_same_rule_does_not_create_endless_new_findings():
    p, c, r = case()
    v = response(p, c, r)
    v["source_rule_checks"][0].update(status="CONTRADICTED", reason="Wrong object", correction="Fix object")
    first = compile_rule_editorial_review(v, p, c, r)["review"]["findings"][0]
    v["source_rule_checks"][0].update(
        reason="The qualifier still modifies the wrong object", correction="Correct this qualifier"
    )
    second = compile_rule_editorial_review(v, p, c, r)["review"]["findings"][0]
    assert first["issue_id"] == second["issue_id"]
    v["source_rule_checks"][0]["lesson_quotes"][0]["quote"] = "not in teaching"
    technical = compile_rule_editorial_review(v, p, c, r)["review"]["findings"][0]
    assert technical["issue_id"] != first["issue_id"] and technical["rule_check_unverified"]


def test_condition_binding_is_per_rule_and_not_literal_comparison():
    p, c, r = case()
    v = response(p, c, r)
    v["source_rule_checks"][0]["condition_checks"][0]["scope_equivalent"] = "NO"
    v["source_rule_checks"][1]["condition_checks"][0]["taught_expression"] = "a paraphrase"
    out = compile_rule_editorial_review(v, p, c, r)
    assert not out["source_rule_checks"][0]["verified"] and out["source_rule_checks"][1]["verified"]
    v["source_rule_checks"][0]["condition_checks"][0]["condition_id"] = "R7.C1"
    out = compile_rule_editorial_review(v, p, c, r)
    assert "condition_ids_invalid" in out["source_rule_checks"][0]["verification_errors"]
    v["source_rule_checks"][0]["condition_checks"][0]["scope_equivalent"] = False
    with pytest.raises(ValueError):
        compile_rule_editorial_review(v, p, c, r)


def test_compact_wire_aliases_reject_foreign_before_compile():
    from app.modules.ai.v3.practical_model_view import PracticalModelView

    p, c, r = case()
    value = response(p, c, r)
    view = PracticalModelView(p)
    fmt = rule_editorial_review_format(p, c, r)
    wire = view.encode(value)
    assert matches_rule_editorial_review(wire, view.schema(fmt))
    assert compile_rule_editorial_review(view.decode(wire), p, c, r)
    wire["narrative_sources"]["l1"] = ["SRC9999"]
    with pytest.raises(ValueError):
        view.decode(wire)


def test_reserve_runner_accepts_all_four_protocols_and_rejects_old_primitives():
    import importlib.util
    from pathlib import Path

    from app.modules.ai.v3.practical_source_semantics import (
        source_semantics_format,
        source_semantics_verification_format,
    )

    p, c, r = case()
    spec = importlib.util.spec_from_file_location(
        "source_semantics_compat_runner", Path(__file__).resolve().parents[4] / "infra/codex-reserve/runner.py"
    )
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    formats = [
        source_semantics_format(p),
        source_semantics_verification_format(p, r["original_reading"]),
        rule_editorial_review_format(p, c, r),
        rule_editorial_verification_format(p, c, r, []),
    ]
    for fmt in formats:
        assert runner._checked_structured_format(fmt) == fmt["json_schema"]["schema"]
    old_boolean = copy.deepcopy(formats[2])
    old_boolean["json_schema"]["schema"]["properties"]["source_rule_checks"]["items"]["properties"]["condition_checks"][
        "items"
    ]["properties"]["scope_equivalent"] = {"type": "boolean"}
    old_null = copy.deepcopy(formats[1])
    replacement = old_null["json_schema"]["schema"]["properties"]["rule_checks"]["items"]["properties"]["replacement"]
    old_null["json_schema"]["schema"]["properties"]["rule_checks"]["items"]["properties"]["replacement"] = {
        "anyOf": [replacement["items"], {"type": "null"}]
    }
    for fmt in (old_boolean, old_null):
        with pytest.raises(runner.RunnerError):
            runner._checked_structured_format(fmt)


def test_strict_condition_enum_and_replacement_cardinality():
    p, c, r = case()
    v = response(p, c, r)
    v["source_rule_checks"][0]["condition_checks"][0]["scope_equivalent"] = True
    with pytest.raises(ValueError):
        compile_rule_editorial_review(v, p, c, r)
    initial = r["original_reading"]
    raw = verification(p, initial)
    for status, replacement in [
        ("SUPPORTED", None),
        ("SUPPORTED", [initial["original"]["sections"][0]["rules"][0]]),
        ("REVISE", []),
        ("REVISE", [initial["original"]["sections"][0]["rules"][0]] * 2),
    ]:
        bad = copy.deepcopy(raw)
        bad["rule_checks"][0].update(status=status, replacement=replacement)
        with pytest.raises(ValueError):
            compile_source_semantics_verification(bad, p, initial)


def test_rule_subsets_exact_identity_and_union():
    p, c, r = case()
    full = response(p, c, r)
    seen = []
    for ids in (["R1"], ["R2"]):
        fmt = rule_editorial_review_format(p, c, r, rule_ids=ids)
        assert is_rule_editorial_review_format(fmt)
        value = copy.deepcopy(full)
        value["source_rule_checks"] = [x for x in value["source_rule_checks"] if x["rule_id"] in ids]
        assert matches_rule_editorial_review(value, fmt)
        out = compile_rule_editorial_review(value, p, c, r, rule_ids=ids)
        seen.extend(x["rule_id"] for x in out["source_rule_checks"])
        other = ["R2"] if ids == ["R1"] else ["R1"]
        with pytest.raises(ValueError):
            compile_rule_editorial_review(value, p, c, r, rule_ids=other)
        with pytest.raises(ValueError):
            compile_rule_editorial_review(value, p, c, r)
        assert fmt != rule_editorial_review_format(p, c, r, rule_ids=other)
    assert set(seen) == {"R1", "R2"} and len(seen) == 2
    for ids in ([], ["R1", "R1"], ["R1", "R3"], ["R3"], ("R1",)):
        with pytest.raises(ValueError):
            rule_editorial_review_format(p, c, r, rule_ids=ids)
    assert rule_editorial_review_format(p, c, r) == rule_editorial_review_format(p, c, r, rule_ids=["R1", "R2"])


def test_subset_verification_cannot_close_unchecked_rule():
    p, c, r = case()
    v = response(p, c, r)
    v["source_rule_checks"][0].update(status="CONTRADICTED", reason="Wrong object", correction="Fix object")
    finding = compile_rule_editorial_review(v, p, c, r)["review"]["findings"][0]
    v["source_rule_checks"] = [v["source_rule_checks"][1]]
    v["resolutions"] = [
        {
            "issue_id": finding["issue_id"],
            "disposition": "FIXED",
            "reason": "Resolved",
            "source_refs": [p.blocks[0].block_id],
            "source_quote": "credit for personal use",
            "course_quote": "credit for personal use",
            "source_question": "",
        }
    ]
    fmt = rule_editorial_verification_format(p, c, r, [finding], rule_ids=["R2"])
    assert is_rule_editorial_verification_format(fmt)
    out = compile_rule_editorial_verification(v, p, c, r, [finding], rule_ids=["R2"])
    assert not out["resolutions"][0]["verified"]
    assert "current_rule_not_checked_in_subset" in out["resolutions"][0]["verification_errors"]
    with pytest.raises(ValueError):
        compile_rule_editorial_verification(v, p, c, r, [finding], rule_ids=["R1"])


def test_rule_subset_formats_compatible_with_runner():
    import importlib.util
    from pathlib import Path

    p, c, r = case()
    spec = importlib.util.spec_from_file_location(
        "subset_compat_runner", Path(__file__).resolve().parents[4] / "infra/codex-reserve/runner.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    for fmt in (
        rule_editorial_review_format(p, c, r, rule_ids=["R1"]),
        rule_editorial_verification_format(p, c, r, [], rule_ids=["R2"]),
    ):
        assert runner._checked_structured_format(fmt) == fmt["json_schema"]["schema"]


def test_condition_ids_must_be_exact_scoped_strings():
    p, c, r = case()
    base = response(p, c, r)
    for mode in ("foreign", "missing", "duplicate", "integer"):
        value = copy.deepcopy(base)
        checks = value["source_rule_checks"][0]["condition_checks"]
        if mode == "foreign":
            checks[0]["condition_id"] = "R2.C1"
        if mode == "missing":
            checks.clear()
        if mode == "duplicate":
            checks.append(copy.deepcopy(checks[0]))
        if mode == "integer":
            checks[0]["condition_id"] = 1
        if mode == "integer":
            with pytest.raises(ValueError):
                compile_rule_editorial_review(value, p, c, r)
        else:
            result = compile_rule_editorial_review(value, p, c, r)
            assert not result["source_rule_checks"][0]["verified"]
            assert "condition_ids_invalid" in result["source_rule_checks"][0]["verification_errors"]
            assert result["source_rule_checks"][1]["verified"]
    result = compile_rule_editorial_review(base, p, c, r)
    assert all(row["verified"] for row in result["source_rule_checks"])


def test_verified_reading_binding_rejects_cross_reading_replay():
    p, course, first = case()
    source = first["original_reading"]
    raw = copy.deepcopy(first["raw_checks"])
    raw["additional_rules"] = [
        {"section": "Added", "rule": copy.deepcopy(source["original"]["sections"][0]["rules"][0])}
    ]
    second = compile_source_semantics_verification(raw, p, source)
    first_response = response(p, course, first)
    first_fmt = rule_editorial_review_format(p, course, first)
    second_fmt = rule_editorial_review_format(p, course, second, rule_ids=["R1", "R2"])
    assert first_fmt != second_fmt
    assert not matches_rule_editorial_review(first_response, second_fmt)
    with pytest.raises(ValueError):
        compile_rule_editorial_review(first_response, p, course, second, rule_ids=["R1", "R2"])
