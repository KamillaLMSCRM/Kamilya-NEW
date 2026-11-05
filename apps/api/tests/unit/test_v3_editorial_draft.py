"""P30 draft readiness is distinct from self-review and human approval."""

from dataclasses import replace

import pytest

from app.modules.ai.v3.practical_curriculum import validate_curriculum
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_service import practical_artifacts
from app.modules.ai.v3.practical_source_core import compile_source_core, source_core_blueprint
from tests.unit.test_v3_practical_curriculum import plan_value
from tests.unit.test_v3_practical_source_core import author_value

pytest_plugins = ("tests.unit.test_v3_practical_cycle",)


def prepared(case):
    corpus, packet, _ = case
    plan = validate_curriculum(plan_value(packet), packet)
    course, custody = compile_source_core(packet, plan, author_value(packet, plan), course_title="Source course")
    result = PracticalCycleResult(
        course,
        {"source_notes": [], "narrative_sources": {"L1": [b.block_id for b in packet.blocks]}},
        PracticalReviewDecision(True, False, (), (), False, ()),
        ({"source_core_custody": custody, "final_bank": {"source_review": "All checked."}},),
        "reviewed",
        standalone_review=True,
        source_core=True,
        curriculum_plan=plan,
    )
    return corpus, packet, result


def test_clean_self_review_still_produces_a_human_reviewable_draft(case):
    corpus, packet, result = prepared(case)
    artifacts = practical_artifacts(result, corpus, packet, "a" * 64)
    assert artifacts.diagnostics["automated_review_passed"] is True
    assert artifacts.diagnostics["requires_source_review"] is True
    assert artifacts.diagnostics["quality_verdict"] == "needs_review"
    manifest = artifacts.diagnostics["draft_review"]
    assert manifest["generation_status"] == "draft_prepared"
    assert manifest["self_review_status"] == "passed"
    assert manifest["human_review_required"] is True
    assert artifacts.content.modules[0].lessons[0].source_validation_status == "needs_review"


def test_notes_are_observations_not_automatic_material_defects(case):
    corpus, packet, result = prepared(case)
    review = {
        **result.review,
        "source_notes": [{"note": "Useful glossary reference.", "source_refs": [packet.blocks[0].block_id]}],
    }
    artifacts = practical_artifacts(replace(result, review=review), corpus, packet, "a" * 64)
    manifest = artifacts.diagnostics["draft_review"]
    assert any("Useful glossary" in row["message"] for row in manifest["observations"])
    assert not any("Useful glossary" in row["message"] for row in manifest["issues"])


def test_valid_auxiliary_unit_roundtrip_keeps_every_original_source_byte(case):
    corpus, packet, _ = case
    raw = plan_value(packet)
    excluded = raw["sections"][0]["source_units"].pop()
    raw["non_teaching_units"] = [excluded]
    plan = validate_curriculum(raw, packet)
    blueprint = source_core_blueprint(packet, plan, course_title="Source course")
    course, meta = compile_source_core(packet, plan, author_value(packet, plan), course_title="Source course")
    assert blueprint["lessons"][0]["auxiliary_units"] == [excluded]
    assert corpus.documents[0].source_text in course["lessons"][0]["content"]
    assert [r for row in meta["source_custody"] for r in row["source_blocks"]] == [b.block_id for b in packet.blocks]
    assert meta["auxiliary_units_unverified"] == [excluded]


def test_initial_only_observation_is_preserved_without_becoming_a_blocking_issue(case):
    corpus, packet, result = prepared(case)
    note = {"note": "Initial-only source observation.", "source_refs": [packet.blocks[0].block_id]}
    history = {**result.history[0], "initial_bank": {"source_review": "Initial review.", "source_notes": [note]}}
    result = replace(result, history=(history,))
    artifacts = practical_artifacts(result, corpus, packet, "a" * 64)
    manifest = artifacts.diagnostics["draft_review"]
    assert sum(row["message"] == note["note"] for row in manifest["observations"]) == 1
    assert not any(row["message"] == note["note"] for row in manifest["issues"])


def test_one_source_paragraph_can_support_several_lessons_without_losing_owners(case):
    import copy

    corpus, packet, _ = case
    raw = plan_value(packet)
    first, second = raw['sections'][0]['source_units']
    base = raw['sections'][0]
    raw['sections'] = [
        {**copy.deepcopy(base), 'title': 'Telephone decision', 'source_units': [first]},
        {**copy.deepcopy(base), 'title': 'Signature decision', 'source_units': [second]},
        {**copy.deepcopy(base), 'title': 'System record decision', 'source_units': [second]},
    ]
    plan = validate_curriculum(raw, packet)
    blueprint = source_core_blueprint(packet, plan, course_title='Source course')
    value = author_value(packet, plan)
    ref = blueprint['lessons'][1]['source_refs'][0]
    value['lessons'][0]['assessment'][0]['source_refs'].append(ref)
    course, custody = compile_source_core(packet, plan, value, course_title='Source course')
    assert len(course['lessons']) == 3
    assert packet.blocks[1].text in course['lessons'][1]['content']
    assert packet.blocks[1].text in course['lessons'][2]['content']
    assert custody['unverified_discovered_dependencies'][0]['owner_lesson_ids'] == ['L2', 'L3']
    assert {ref for row in custody['source_custody'] for ref in row['source_blocks']} == {
        block.block_id for block in packet.blocks}


@pytest.mark.parametrize("target", ["L1Q1", "L1P1"])
def test_counterexamples_are_locatable_and_distinct_even_for_the_same_target(case, target):
    corpus, packet, result = prepared(case)
    ref = packet.blocks[0].block_id
    findings = tuple(
        {
            "scope": "question",
            "id": target,
            "issue_id": f"issue-{i}",
            "evidence": {
                "problem": "option_answerability_unresolved",
                "counterexample": {
                    "case_description": f"Competing source-compatible case {i}.",
                    "unstated_condition": "The actor status is not specified.",
                    "source_refs": [ref],
                    "possible_options": [0, 1],
                },
            },
        }
        for i in range(2)
    )
    history = {
        **result.history[0],
        "case_context": {
            target: {
                "lesson_title": "Approval procedure",
                "prompt": "Who is authorized in this situation?",
                "choices": ["Worker", "Approver"],
                "source_refs": [ref],
            }
        },
    }
    result = replace(
        result, history=(history,), decision=PracticalReviewDecision(False, False, (), (), False, findings)
    )
    artifacts = practical_artifacts(result, corpus, packet, "a" * 64)
    issues = [row for row in artifacts.diagnostics["draft_review"]["issues"] if row["kind"] == "finding"]
    assert len(artifacts.content.modules[0].lessons) == 1
    assert len(artifacts.assessment.assessments[0].mcq) == 3
    assert artifacts.diagnostics["draft_review"]["generation_status"] == "draft_prepared"
    assert len(issues) == 2 and len({row["id"] for row in issues}) == 2
    assert all("Who is authorized" in row["target_title"] for row in issues)
    assert all(row["evidence"]["unverified"] is True for row in issues)
    assert issues[0]["evidence"]["possible_answers"] == ["Worker", "Approver"]
    assert issues[0]["evidence"]["source_quotes"] == [packet.blocks[0].text]
    assert issues[0]["evidence"]["observation"] != issues[1]["evidence"]["observation"]


def test_retained_counterexample_uses_its_own_question_version_after_option_edit(case):
    from app.modules.ai.v3.practical_source_core_cycle import _finding_case_context, _retain_unverified

    corpus, packet, result = prepared(case)
    question = result.course["lessons"][0]["questions"][0]
    old = {
        "L1Q1": {
            "prompt": question["prompt"],
            "choices": ["Original A", "Original B"],
            "source_refs": question["source_refs"],
        }
    }
    new = {"L1Q1": {**old["L1Q1"], "choices": ["Changed B", "Changed A"]}}
    initial = (
        {
            "scope": "question",
            "id": "L1Q1",
            "issue_id": "old-issue",
            "evidence": {"problem": "option_answerability_unresolved", "possible_options": [0]},
        },
    )
    final = (
        {
            "scope": "question",
            "id": "L1Q1",
            "issue_id": "new-issue",
            "evidence": {"problem": "option_answerability_unresolved", "possible_options": [0]},
        },
    )
    retained = _retain_unverified(initial, final, {"L1Q1"}, {"L1Q1": "L1"})
    contexts = _finding_case_context(initial, final, old, new, {"L1Q1": "L1"}, result.course["lessons"])
    result = replace(
        result,
        history=({**result.history[0], "initial_findings": initial, "finding_case_context": contexts},),
        decision=PracticalReviewDecision(False, False, (), (), False, tuple(retained)),
    )
    manifest = practical_artifacts(result, corpus, packet, "a" * 64).diagnostics["draft_review"]
    options = {tuple(row["evidence"]["possible_answers"]) for row in manifest["issues"] if row["kind"] == "finding"}
    assert options == {("Original A",), ("Changed B",)}


def test_open_prior_finding_never_rebinds_its_original_answer_indices(case):
    from app.modules.ai.v3.practical_source_core_cycle import _finding_case_context

    _, _, result = prepared(case)
    original = {"prompt": "Original case", "choices": ["Original A", "Original B"], "source_refs": ["ref"]}
    edited = {**original, "prompt": "Edited case", "choices": ["Changed B", "Changed A"]}
    # interpret_practical_review retains an OPEN prior finding verbatim. Its
    # presence in final.feedback does not turn the old evidence into new evidence.
    prior = {"scope": "question", "id": "L1Q1", "issue_id": "same-open-issue", "evidence": {"possible_options": [0]}}
    contexts = _finding_case_context(
        (prior,), (dict(prior),), {"L1Q1": original}, {"L1Q1": edited}, {"L1Q1": "L1"}, result.course["lessons"]
    )
    bound = contexts["same-open-issue"]
    assert bound["review_round"] == "initial"
    assert bound["choices"][0] == "Original A" and bound["prompt"] == "Original case"
