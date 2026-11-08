"""Grouped review and addressed editing integration regressions."""

import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle
from app.modules.ai.v3.practical_compact_editorial_cycle import _prior_comparison_owner, review_editorial_candidate
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_autonomous_editorial_cycle import predicate_value, rule_wire, source_wire
from tests.unit.test_v3_editorial_contract import review_value, revision_value
from tests.unit.test_v3_source_comparisons import comparison_case

pytest_plugins = ("tests.unit.test_v3_practical_cycle",)


def test_prior_uses_actual_source_section_before_shared_lesson_attention():
    def group(ref, scope='linked_lessons'):
        return {'scope': scope, 'lesson_ids': ['l1'], 'goals': [{'rule': {'source_refs': [ref]}}]}

    groups = [group('cover', 'course_coverage'), group('other'), group('exact')]
    prior = {'target': {'kind': 'lesson', 'id': 'l1'}, 'source_refs': ['exact']}
    assert _prior_comparison_owner(prior, groups, {'R1': 1}) == 2
    assert _prior_comparison_owner({**prior, 'source_rule_id': 'R1'}, groups, {'R1': 1}) == 1
    assert _prior_comparison_owner({**prior, 'source_refs': []}, groups, {}) == 1
    with pytest.raises(ValueError, match='prior_rule_identity'):
        _prior_comparison_owner({**prior, 'source_rule_id': 'foreign'}, groups, {})
    with pytest.raises(ValueError, match='comparison_inventory_empty'):
        _prior_comparison_owner(prior, [], {})


def _json_section(text, marker):
    return json.loads(text.split(marker, 1)[1].split("\n", 1)[0])


@pytest.mark.asyncio
async def test_linked_rule_sees_peer_prose_and_can_close_with_peer_evidence():
    packet, reading, course = comparison_case()
    course["lessons"][0]["content"] = "Primary prose."
    course["lessons"][1]["content"] = "Peer lesson contains the exact corrected source teaching."
    for lesson in course["lessons"]:
        lesson["questions"][0].update(prompt="QUIZ_SECRET_" + lesson["id"], explanation="KEY_SECRET_" + lesson["id"])
    view = PracticalModelView(packet)
    prior = {
        "issue_id": "peer-rule-issue",
        "domain": "content",
        "severity": "material",
        "target": {"kind": "lesson", "id": "l2"},
        "source_rule_id": "R1",
        "problem": "Prior contradiction",
        "basis": "Source meaning",
        "correction": "Review the peer lesson",
        "source_refs": [packet.blocks[0].block_id],
    }
    found = []

    async def call(name, group, messages, fmt, validate):
        props = fmt["json_schema"]["schema"]["properties"]
        value = review_value(packet, course)
        value["findings"] = []
        if "source_rule_checks" in props:
            body = messages[1]["content"]
            assert "QUIZ_SECRET_" not in body and "KEY_SECRET_" not in body
            ids = props["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
            primary = _json_section(body, "CURRENT_TEACHING_PROSE_JSON\n")
            peers = _json_section(body, "\nOTHER_CURRENT_TEACHING_PROSE_JSON\n")
            if "R1" in ids:
                assert [row["id"] for row in primary["lessons"]] == ["l1"]
                assert any(row["id"] == "l2" and row["content"] == course["lessons"][1]["content"] for row in peers)
                found.append(True)
            value["reading_fingerprint"] = props["reading_fingerprint"]["enum"][0]
            value["source_rule_checks"] = [
                {
                    "rule_id": rid,
                    "status": "SUPPORTED" if rid == "R1" else "NOT_APPLICABLE",
                    "lesson_ids": ["l2"] if rid == "R1" else [],
                    "lesson_quotes": [{"lesson_id": "l2", "quote": "exact corrected source teaching"}]
                    if rid == "R1"
                    else [],
                    "reason": "Compared current teaching",
                    "correction": "",
                    "severity": "material",
                }
                for rid in ids
            ]
            assigned = json.loads(body.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1])
            value["resolutions"] = [
                {
                    "issue_id": row["issue_id"],
                    "disposition": "FIXED",
                    "reason": "Peer text checked",
                    "source_refs": [packet.blocks[0].block_id],
                    "source_quote": packet.blocks[0].text,
                    "course_quote": "exact corrected source teaching",
                    "source_question": "",
                }
                for row in assigned
            ]
        validate(value)
        return value

    result = await review_editorial_candidate(
        packet,
        reading,
        course,
        "FULL_SOURCE",
        view,
        call,
        "Review prose",
        max_rules=128,
        assessment_system="Review assessments",
        verification_guide="Review current",
        prior=[prior],
    )
    assert found and len(result["resolutions"]) == 1 and result["resolutions"][0]["verified"]
    assert result["resolutions"][0]["course_quote"] == "exact corrected source teaching"


@pytest.mark.asyncio
async def test_two_lessons_are_edited_sequentially_against_current_course(case):
    corpus, packet, base = case
    original = copy.deepcopy(base)
    peer = copy.deepcopy(original["lessons"][0])
    peer["id"] = "l2"
    peer["title"] = "Peer"
    peer["content"] = "Peer source teaching."
    for question in peer["questions"]:
        question["id"] += "-peer"
    original["lessons"].append(peer)
    current = copy.deepcopy(original)
    view = PracticalModelView(packet)
    scopes = []
    findings = []
    for target in ("q1", "q1-peer"):
        row = review_value(packet, original, target=target)["findings"][0]
        row["problem"] = "Repair " + target
        findings.append(row)

    async def stage(name, group, messages, fmt, validate):
        source = source_wire(packet, view, fmt, messages, validate)
        if source is not None:
            return source
        nonlocal current
        if name == "lesson":
            value = original
        elif ":revision:" in group:
            body = messages[1]["content"]
            scope = _json_section(body, "\nCURRENT_EDIT_SCOPE_JSON\n")
            fingerprint = body.split("\nCURRENT_COURSE_FINGERPRINT\n")[1].split("\n", 1)[0]
            assert fingerprint == _digest(current)
            assert len(scope["lessons"]) == 1
            lid = scope["lessons"][0]["id"]
            scopes.append((lid, fingerprint))
            before = copy.deepcopy(current)
            proposal = copy.deepcopy(current)
            edited = next(row for row in proposal["lessons"] if row["id"] == lid)
            edited["questions"][0]["prompt"] = "Repaired " + lid
            other = next(row for row in proposal["lessons"] if row["id"] != lid)
            other["questions"][0]["prompt"] = "UNREQUESTED SIBLING MUTATION"
            value = revision_value(packet, before, proposal)
            next(lesson for lesson in current["lessons"] if lesson["id"] == lid)["questions"][0]["prompt"] = (
                "Repaired " + lid
            )
        elif "option-predicates" in group:
            value = predicate_value(packet, current, fmt=fmt)
        else:
            value = review_value(packet, current)
            value["findings"] = []
            props = fmt["json_schema"]["schema"]["properties"]
            if "source_rule_checks" not in props and ":review:" in group and not scopes:
                value["findings"] = copy.deepcopy(findings)
            if "resolutions" in props:
                assigned = json.loads(messages[1]["content"].split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1])
                questions = {q["id"]: q for lesson in current["lessons"] for q in lesson["questions"]}
                value["resolutions"] = [
                    {
                        "issue_id": row["issue_id"],
                        "disposition": "FIXED",
                        "reason": "Repaired",
                        "source_refs": [packet.blocks[0].block_id],
                        "source_quote": packet.blocks[0].text,
                        "course_quote": questions[row["target"]["id"]]["prompt"],
                        "source_question": "",
                    }
                    for row in assigned
                ]
            value = rule_wire(value, fmt, current)
            for row in value.get("source_rule_checks", []):
                row["lesson_ids"] = [q["lesson_id"] for q in row["lesson_quotes"]]
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_autonomous_editorial_cycle(packet, corpus, CourseIntent(), (), stage, max_revisions=3)
    assert [lid for lid, _ in scopes] == ["l1", "l2"] and scopes[0][1] != scopes[1][1]
    assert result.decision.accepted and result.course == current
    assert [lesson["questions"][0]["prompt"] for lesson in result.course["lessons"]] == ["Repaired l1", "Repaired l2"]
    assert all(
        lesson["questions"][1] == original["lessons"][index]["questions"][1]
        for index, lesson in enumerate(result.course["lessons"])
    )
    assert all(row["verified"] for row in result.history[0]["verified_resolutions"])


@pytest.mark.asyncio
async def test_generic_lesson_prior_prefers_later_linked_group_over_first_catchall():
    packet, reading, course = comparison_case()
    # R1 links only to the first source block; point both lessons at the second
    # so the first source group is a course-wide fallback and a later one is linked.
    course["lessons"][0]["questions"][0]["source_refs"] = [packet.blocks[1].block_id]
    view = PracticalModelView(packet)
    prior = {
        "issue_id": "lesson-prior",
        "domain": "content",
        "severity": "material",
        "target": {"kind": "lesson", "id": "l2"},
        "problem": "Clarify lesson",
        "basis": "Source rule",
        "correction": "Clarify",
        "source_refs": [packet.blocks[1].block_id],
    }
    assignments = []

    async def call(name, group, messages, fmt, validate):
        props = fmt["json_schema"]["schema"]["properties"]
        value = review_value(packet, course)
        value["findings"] = []
        if "source_rule_checks" in props:
            body = messages[1]["content"]
            scope = body.split("\nCOMPARISON_SCOPE\n")[1].split("\n", 1)[0]
            assigned = json.loads(body.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1])
            assignments.append((scope, [item["issue_id"] for item in assigned]))
            value["reading_fingerprint"] = props["reading_fingerprint"]["enum"][0]
            ids = props["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
            value["source_rule_checks"] = [
                {
                    "rule_id": rid,
                    "status": "NOT_APPLICABLE",
                    "lesson_ids": [],
                    "lesson_quotes": [],
                    "reason": "Not applicable",
                    "correction": "",
                    "severity": "material",
                }
                for rid in ids
            ]
            value["resolutions"] = [
                {
                    "issue_id": row["issue_id"],
                    "disposition": "FIXED",
                    "reason": "Reviewed",
                    "source_refs": [packet.blocks[1].block_id],
                    "source_quote": packet.blocks[1].text,
                    "course_quote": course["lessons"][1]["content"],
                    "source_question": "",
                }
                for row in assigned
            ]
        validate(value)
        return value

    result = await review_editorial_candidate(
        packet,
        reading,
        course,
        "FULL_SOURCE",
        view,
        call,
        "Review",
        max_rules=128,
        assessment_system="Assess",
        verification_guide="Verify",
        prior=[prior],
    )
    assert assignments[0] == ("course_coverage", [])
    assert [(scope, ids) for scope, ids in assignments if ids] == [("linked_lessons", ["lesson-prior"])]
    assert len(result["resolutions"]) == 1 and result["resolutions"][0]["verified"]
    raw_ids = [
        row["issue_id"]
        for part in result["raw_parts"]
        if part["review_kind"] == "prose"
        for row in part["response"].get("resolutions", [])
    ]
    assert raw_ids == ["lesson-prior"]


@pytest.mark.asyncio
@pytest.mark.parametrize("literal_prose", [True, False])
async def test_content_fidelity_finding_routes_to_whole_course_and_requires_current_prose(literal_prose):
    packet, reading, course = comparison_case()
    view = PracticalModelView(packet)
    course["lessons"][0]["content"] = "Current literal source-grounded teaching."
    course["lessons"][0]["questions"][0]["prompt"] = "Question-only text."
    qa_prior = []
    stage_mode = "discover"

    async def call(name, group, messages, fmt, validate):
        props = fmt["json_schema"]["schema"]["properties"]
        body = messages[1]["content"]
        value = review_value(packet, course)
        value["findings"] = []
        if "source_rule_checks" in props:
            if "\nPRIOR_MATERIAL_FINDINGS_JSON\n" in body:
                assert json.loads(body.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1]) == []
            value["reading_fingerprint"] = props["reading_fingerprint"]["enum"][0]
            ids = props["source_rule_checks"]["items"]["properties"]["rule_id"]["enum"]
            value["source_rule_checks"] = [
                {
                    "rule_id": rid,
                    "status": "NOT_APPLICABLE",
                    "lesson_ids": [],
                    "lesson_quotes": [],
                    "reason": "Not applicable",
                    "correction": "",
                    "severity": "material",
                }
                for rid in ids
            ]
            if "resolutions" in props:
                value["resolutions"] = []
        elif ":proof:" in group:
            assigned = json.loads(
                body.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1].split("\nPRIOR_INVALID_RESOLUTIONS_JSON\n")[0]
            )
            value["resolutions"] = [
                {
                    "issue_id": row["issue_id"],
                    "disposition": "FIXED",
                    "reason": "Checked",
                    "source_refs": [packet.blocks[0].block_id],
                    "source_quote": packet.blocks[0].text,
                    "course_quote": "Question-only text.",
                    "source_question": "",
                }
                for row in assigned
            ]
        elif stage_mode == "discover":
            value["findings"] = review_value(packet, course, kind="lesson", target="l1", domain="content")["findings"]
        else:
            assert "FULL_COURSE_WITH_KEYS_AND_EXPLANATIONS_JSON" in body
            assigned = json.loads(body.split("\nPRIOR_MATERIAL_FINDINGS_JSON\n")[1])
            qa_prior.extend(row["issue_id"] for row in assigned)
            value["resolutions"] = [
                {
                    "issue_id": row["issue_id"],
                    "disposition": "FIXED",
                    "reason": "Checked",
                    "source_refs": [packet.blocks[0].block_id],
                    "source_quote": packet.blocks[0].text,
                    "course_quote": "Current literal source-grounded teaching."
                    if literal_prose
                    else "Question-only text.",
                    "source_question": "",
                }
                for row in assigned
            ]
        validate(value)
        return value

    args = dict(
        packet=packet,
        reading=reading,
        course=course,
        context="FULL_SOURCE",
        view=view,
        call=call,
        system="Review",
        max_rules=128,
        assessment_system="Assess",
        verification_guide="Verify",
    )
    initial = await review_editorial_candidate(**args)
    finding = initial["review"]["findings"][0]
    assert finding["domain"] == "content" and finding["review_origin"] == "COURSE_FIDELITY"
    stage_mode = "verify"
    checked = await review_editorial_candidate(**args, prior=[finding])
    assert qa_prior == [finding["issue_id"]]
    assert len(checked["resolutions"]) == 1
    assert checked["resolutions"][0]["verified"] is literal_prose
    if not literal_prose:
        assert "course_quote_invalid" in checked["resolutions"][0]["verification_errors"]
