import copy
import json

import pytest

from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_rule_editorial_cycle import review_source_rules, rule_parts
from tests.unit.test_v3_rule_editorial_contract import case, response


@pytest.mark.parametrize("size,expected", [(1, [["R1"], ["R2"]]), (2, [["R1", "R2"]]), (40, [["R1", "R2"]])])
def test_parts_cover_each_identity_once_without_a_document_limit(size, expected):
    packet, _, reading = case()
    assert rule_parts(packet, reading, size) == expected


@pytest.mark.parametrize("size", [True, 0, 129])
def test_part_budget_is_checked(size):
    packet, _, reading = case()
    with pytest.raises(ValueError):
        rule_parts(packet, reading, size)


@pytest.mark.asyncio
async def test_review_parts_keep_full_context_and_verify_each_prior_issue_with_its_rule():
    packet, course, reading = case()
    view = PracticalModelView(packet)
    calls = []
    prior = None

    async def call(name, group, messages, fmt, validate):
        props = fmt["json_schema"]["schema"]["properties"]
        ids = props["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
        calls.append(ids)
        text = messages[1]["content"]
        assert "ALL_ORIGINAL_SOURCE_AND_CONFIRMED_DECISIONS" in text
        assert view.encode(course)["title"] in text and reading["reading_fingerprint"] in text
        assert (
            json.loads(text.split("\nREQUIRED_SOURCE_RULE_IDS_JSON\n")[1].split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[0])
            == ids
        )
        value = response(packet, course, reading)
        value["source_rule_checks"] = [row for row in value["source_rule_checks"] if row["rule_id"] in ids]
        if ":verify:" in group:
            findings = view.decode(json.loads(text.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1]))
            assert all(row.get("source_rule_id") in ids for row in findings)
            value["resolutions"] = [
                {
                    "issue_id": row["issue_id"],
                    "disposition": "FIXED",
                    "reason": "The current teaching contains the source rule.",
                    "source_refs": [packet.blocks[0].block_id],
                    "source_quote": "credit for personal use",
                    "course_quote": course["lessons"][0]["content"],
                    "source_question": "",
                }
                for row in findings
            ]
        else:
            for row in value["source_rule_checks"]:
                row.update(
                    status="CONTRADICTED",
                    reason="The teaching changes the rule.",
                    correction="Correct this source rule.",
                )
        validate(value)
        return value

    kwargs = dict(
        packet=packet,
        reading=reading,
        course=course,
        context="ALL_ORIGINAL_SOURCE_AND_CONFIRMED_DECISIONS",
        view=view,
        call=call,
        system="Semantic review",
        max_rules=1,
    )
    initial = await review_source_rules(**kwargs)
    prior = initial["review"]["findings"]
    assert {row["source_rule_id"] for row in prior} == {"R1", "R2"}
    assert len(initial["source_rule_checks"]) == 2 and len(initial["raw_parts"]) == 2
    verified = await review_source_rules(**kwargs, prior=prior)
    assert len(verified["resolutions"]) == 2 and all(r["verified"] for r in verified["resolutions"])
    assert calls == [["R1"], ["R2"], ["R1"], ["R2"]]


@pytest.mark.asyncio
async def test_unknown_second_part_is_not_retried_or_certified_from_first():
    packet, course, reading = case()
    count = 0
    before = copy.deepcopy(reading)

    async def call(name, group, messages, fmt, validate):
        nonlocal count
        count += 1
        if count == 2:
            raise TimeoutError("No authoritative response")
        value = response(packet, course, reading)
        value["source_rule_checks"] = value["source_rule_checks"][:1]
        validate(value)
        return value

    with pytest.raises(TimeoutError):
        await review_source_rules(
            packet, reading, course, "Full source", PracticalModelView(packet), call, "Review", max_rules=1
        )
    assert count == 2 and reading == before


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["corrected", "still_invalid", "unknown"])
async def test_model_repairs_only_bad_proof_and_preserves_valid_sibling_and_real_finding(outcome):
    packet, course, reading = case()
    calls = []
    preserved = None

    async def call(name, group, messages, fmt, validate):
        nonlocal preserved
        ids = fmt["json_schema"]["schema"]["properties"]["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
        calls.append(ids)
        value = response(packet, course, reading)
        value["source_rule_checks"] = [row for row in value["source_rule_checks"] if row["rule_id"] in ids]
        if len(calls) == 1:
            value["source_rule_checks"][0]["lesson_quotes"][0]["quote"] = "Invented teaching quote"
            preserved = copy.deepcopy(value["source_rule_checks"][1])
            value["findings"] = [
                {
                    "domain": "assessment",
                    "severity": "material",
                    "target": {"kind": "question", "id": "q1"},
                    "problem": "A real independent question issue",
                    "basis": "The question asks for the wrong object.",
                    "correction": "Correct the question.",
                    "source_refs": [packet.blocks[0].block_id],
                }
            ]
        else:
            assert ids == ["R1"] and "PRIOR_RULE_CHECKS_UNVERIFIED_JSON" in messages[1]["content"]
            assert "Invented teaching quote" in messages[1]["content"]
            if outcome == "unknown":
                raise TimeoutError("Uncertain correction outcome")
            if outcome == "still_invalid":
                value["source_rule_checks"][0]["lesson_quotes"][0]["quote"] = "Still invented"
        validate(value)
        return value

    run = review_source_rules(
        packet, reading, course, "Full source", PracticalModelView(packet), call, "Review", max_rules=40
    )
    if outcome == "unknown":
        with pytest.raises(TimeoutError):
            await run
    else:
        result = await run
        assert result["source_rule_checks"][0]["verified"] is (outcome == "corrected")
        assert {
            k: v for k, v in result["source_rule_checks"][1].items() if k not in ("verified", "verification_errors")
        } == preserved
        assert any(row["problem"] == "A real independent question issue" for row in result["review"]["findings"])
        assert (
            result["raw_parts"][0]["response"]["source_rule_checks"][0]["lesson_quotes"][0]["quote"]
            == "Invented teaching quote"
        )
        assert result["raw_parts"][0]["evidence_correction"]
    assert calls == [["R1", "R2"], ["R1"]]
