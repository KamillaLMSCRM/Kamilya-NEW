from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.modules.ai.assessment_audit import audit_course_assessment
from app.modules.ai.assessment_schema import (
    CourseAssessment,
    LessonAssessment,
    MatchingPair,
    MatchingQuestion,
    MCQOption,
    MCQQuestion,
    TrueFalseQuestion,
)
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


class FakeLLM:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self._payloads = list(payloads)
        self.calls: list[object] = []

    async def ainvoke(self, prompt: object, **kwargs: object) -> SimpleNamespace:
        self.calls.append(prompt)
        if not self._payloads:
            raise AssertionError("Unexpected model call")
        return SimpleNamespace(content=json.dumps(self._payloads.pop(0), ensure_ascii=False))


def _course_content() -> CourseContent:
    shared_chunk = "Shared policy chunk: approval requires two signatures."
    return CourseContent(title="Synthetic audit course", modules=[ModuleContent(title="Module", lessons=[
        LessonContent(title="Lesson one", objectives=["Identify the approval requirement."],
                      content="Generated prose says approval requires a signature.", source_chunks=[
                          shared_chunk, "Contradiction outside the selected quote: approval requires two signatures."]),
        LessonContent(title="Lesson two", objectives=["Recognize the escalation path."],
                      content="Generated prose describes escalation.", source_chunks=[
                          shared_chunk, "Escalate unresolved requests to the manager."]),
    ])])


def _question(text: str, correct_index: int = 0) -> MCQQuestion:
    return MCQQuestion(question=text, options=[MCQOption("Two", correct_index == 0), MCQOption("One", correct_index == 1)],
                       explanation="Original server explanation must survive deletion-only filtering.",
                       source_quote="approval requires two signatures", quality_score=4.0)


def _assessment() -> CourseAssessment:
    return CourseAssessment(assessments=[
        LessonAssessment(lesson_title="Lesson one", mcq=[_question("How many signatures are required?")]),
        LessonAssessment(lesson_title="Lesson two", mcq=[_question("How many signatures are required before approval?")]),
    ])


def _answers(rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {"answers": rows or [
        {"id": "L0Q0", "valid_option_indices": [0], "quality": "valid", "reason": "Two is the only supported answer."},
        {"id": "L1Q0", "valid_option_indices": [0], "quality": "valid", "reason": "Two is the only supported answer."},
    ]}


def _review() -> dict[str, object]:
    return {"decisions": [
        {"question_id": "L0Q0", "decision": "keep", "reason": "valid", "duplicate_of": None},
        {"question_id": "L1Q0", "decision": "drop", "reason": "duplicate", "duplicate_of": "L0Q0"},
    ], "coverage": [
        {"lesson_index": 0, "uncovered_objective_indices": [], "uncovered_content_objective_indices": []},
        {"lesson_index": 1, "uncovered_objective_indices": [0], "uncovered_content_objective_indices": []},
    ]}


@pytest.mark.asyncio
async def test_audit_blinds_first_pass_then_applies_only_derived_and_final_deletions() -> None:
    assessment = _assessment()
    kept, dropped = assessment.assessments[0].mcq[0], assessment.assessments[1].mcq[0]
    llm = FakeLLM(_answers(), _review())

    result = await audit_course_assessment(llm, _course_content(), assessment)

    assert len(llm.calls) == 2
    assert result.assessment.assessments[0].mcq == [kept]
    assert result.assessment.assessments[0].mcq[0] is kept
    assert result.assessment.assessments[0].mcq[0].options == kept.options
    assert result.assessment.assessments[1].mcq == []
    assert dropped not in result.assessment.assessments[1].mcq
    assert result.uncovered_objectives == [(1, 0)]
    assert result.decisions == _review()["decisions"]


@pytest.mark.asyncio
async def test_first_prompt_contains_complete_deduplicated_sources_and_objectives_but_no_answer_metadata() -> None:
    llm = FakeLLM(_answers(), _review())
    await audit_course_assessment(llm, _course_content(), _assessment())

    first_prompt = str(llm.calls[0])
    assert first_prompt.count("Shared policy chunk: approval requires two signatures.") == 1
    assert "Contradiction outside the selected quote: approval requires two signatures." in first_prompt
    assert "Identify the approval requirement." not in first_prompt
    assert "Recognize the escalation path." not in first_prompt
    for forbidden_field in ('"is_correct"', '"explanation"', '"source_quote_id"', '"quality_score"'):
        assert forbidden_field not in first_prompt
    second_prompt = str(llm.calls[1])
    assert "How many signatures are required?" in second_prompt
    assert "Two" in second_prompt
    assert "Identify the approval requirement." in second_prompt
    assert "Recognize the escalation path." in second_prompt
    assert "Contradiction outside the selected quote" not in second_prompt
    assert "ANY kept question across the entire course" in second_prompt
    assert "ONLY questions you keep IN THAT LESSON" not in second_prompt


@pytest.mark.asyncio
async def test_first_pass_derives_drop_reasons_and_skips_final_review_when_no_question_survives() -> None:
    assessment = CourseAssessment(assessments=[
        LessonAssessment(lesson_title="Lesson one", mcq=[_question("Unsupported answer"), _question("Several valid answers"),
                                                        _question("Wrong keyed answer"), _question("Malformed answer")]),
        LessonAssessment(lesson_title="Lesson two"),
    ])
    llm = FakeLLM(_answers([
        {"id": "L0Q0", "valid_option_indices": [], "quality": "valid", "reason": "No option is supported."},
        {"id": "L0Q1", "valid_option_indices": [0, 1], "quality": "valid", "reason": "Both options fit."},
        {"id": "L0Q2", "valid_option_indices": [1], "quality": "valid", "reason": "The other option is supported."},
        {"id": "L0Q3", "valid_option_indices": [0], "quality": "malformed", "reason": "Question is malformed."},
    ]))

    result = await audit_course_assessment(llm, _course_content(), assessment)

    assert len(llm.calls) == 1
    assert [item.mcq for item in result.assessment.assessments] == [[], []]
    assert result.uncovered_objectives == [(0, 0), (1, 0)]
    assert result.decisions == [
        {"question_id": "L0Q0", "decision": "drop", "reason": "unsupported", "duplicate_of": None},
        {"question_id": "L0Q1", "decision": "drop", "reason": "ambiguous", "duplicate_of": None},
        {"question_id": "L0Q2", "decision": "drop", "reason": "wrong_key", "duplicate_of": None},
        {"question_id": "L0Q3", "decision": "drop", "reason": "malformed", "duplicate_of": None},
    ]


@pytest.mark.asyncio
async def test_numeric_scope_review_drops_question_missed_by_batch_answer_solver() -> None:
    content = CourseContent(
        title="Limits",
        modules=[ModuleContent(title="Module", lessons=[LessonContent(
            title="Penalty limits",
            objectives=["Distinguish the daily rate from the annual cap."],
            content="The policy defines a daily rate and a separate annual cap.",
            source_chunks=[
                "After 90 days the daily penalty rate is 0.03% of the overdue payment. "
                "The annual penalty cap is 10% of the issued amount."
            ],
        )])],
    )
    question = MCQQuestion(
        question="What penalty limit applies after 90 days?",
        options=[
            MCQOption("0.03% of the overdue payment", True),
            MCQOption("10% of the issued amount", False),
        ],
        explanation="Two different scopes exist in the policy.",
        source_quote="After 90 days the daily penalty rate is 0.03% of the overdue payment.",
        quality_score=4.0,
    )
    assessment = CourseAssessment([LessonAssessment("Penalty limits", mcq=[question])])
    batch_answer = {"answers": [{
        "id": "L0Q0",
        "valid_option_indices": [0],
        "quality": "valid",
        "reason": "The first option matches one sentence.",
    }]}
    numeric_scope = {"answers": [{
        "id": "L0Q0",
        "valid_option_indices": [0, 1],
        "quality": "valid",
        "reason": "The stem omits whether it asks for the daily rate or annual cap.",
    }]}
    llm = FakeLLM(batch_answer, numeric_scope)

    result = await audit_course_assessment(llm, content, assessment)

    assert len(llm.calls) == 2
    assert result.assessment.assessments[0].mcq == []
    assert result.uncovered_objectives == [(0, 0)]
    assert result.decisions == [
        {"question_id": "L0Q0", "decision": "drop", "reason": "ambiguous", "duplicate_of": None}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("answers", [
    _answers([{ "id": "L0Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok" }]),
    _answers([{"id": "L0Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"},
              {"id": "L0Q0", "valid_option_indices": [0], "quality": "valid", "reason": "duplicate id"}]),
    _answers([{"id": "L0Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"},
              {"id": "L9Q0", "valid_option_indices": [0], "quality": "valid", "reason": "unknown id"}]),
    _answers([{"id": "L0Q0", "valid_option_indices": [True], "quality": "valid", "reason": "bool is not an index"},
              {"id": "L1Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"}]),
    _answers([{"id": "L0Q0", "valid_option_indices": [2], "quality": "valid", "reason": "out of range"},
              {"id": "L1Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"}]),
    _answers([{"id": "L0Q0", "valid_option_indices": [0, 0], "quality": "valid", "reason": "repeated index"},
              {"id": "L1Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"}]),
])
async def test_audit_rejects_incomplete_duplicate_unknown_or_malformed_blind_answers(answers: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        await audit_course_assessment(FakeLLM(answers), _course_content(), _assessment())


@pytest.mark.asyncio
@pytest.mark.parametrize("review", [
    {"decisions": [{"question_id": "L0Q0", "decision": "keep", "reason": "valid", "duplicate_of": None}], "coverage": _review()["coverage"]},
    {"decisions": [{"question_id": "L0Q0", "decision": "drop", "reason": "duplicate", "duplicate_of": "L0Q0"},
                   {"question_id": "L1Q0", "decision": "keep", "reason": "valid", "duplicate_of": None}], "coverage": _review()["coverage"]},
    {"decisions": [{"question_id": "L0Q0", "decision": "keep", "reason": "valid", "duplicate_of": "L1Q0"},
                   {"question_id": "L1Q0", "decision": "keep", "reason": "valid", "duplicate_of": None}], "coverage": _review()["coverage"]},
    {"decisions": _review()["decisions"], "coverage": [{"lesson_index": 0, "uncovered_objective_indices": [], "uncovered_content_objective_indices": []}]},
])
async def test_audit_rejects_incomplete_or_invalid_final_review_without_silent_pass(review: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        await audit_course_assessment(FakeLLM(_answers(), review), _course_content(), _assessment())


@pytest.mark.asyncio
async def test_audit_preserves_a_later_kept_duplicate_representative_in_its_original_course_order() -> None:
    assessment = _assessment()
    later_representative = assessment.assessments[1].mcq[0]
    review = {
        "decisions": [
            {"question_id": "L0Q0", "decision": "drop", "reason": "duplicate", "duplicate_of": "L1Q0"},
            {"question_id": "L1Q0", "decision": "keep", "reason": "valid", "duplicate_of": None},
        ],
        "coverage": [
            {"lesson_index": 0, "uncovered_objective_indices": [0], "uncovered_content_objective_indices": []},
            {"lesson_index": 1, "uncovered_objective_indices": [0], "uncovered_content_objective_indices": []},
        ],
    }

    result = await audit_course_assessment(FakeLLM(_answers(), review), _course_content(), assessment)

    assert result.assessment.assessments[0].mcq == []
    assert result.assessment.assessments[1].mcq == [later_representative]
    assert result.assessment.assessments[1].mcq[0] is later_representative
    assert result.decisions == review["decisions"]


@pytest.mark.asyncio
async def test_audit_reports_content_gap_separately_from_course_wide_assessment_gap() -> None:
    review = _review()
    review["coverage"] = [
        {
            "lesson_index": 0,
            "uncovered_objective_indices": [],
            "uncovered_content_objective_indices": [0],
        },
        {
            "lesson_index": 1,
            "uncovered_objective_indices": [0],
            "uncovered_content_objective_indices": [],
        },
    ]

    result = await audit_course_assessment(FakeLLM(_answers(), review), _course_content(), _assessment())

    assert result.uncovered_objectives == [(1, 0)]
    assert result.uncovered_content_objectives == [(0, 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize("decisions", [
    [
        {"question_id": "L0Q0", "decision": "drop", "reason": "duplicate", "duplicate_of": "L0Q0"},
        {"question_id": "L0Q1", "decision": "keep", "reason": "valid", "duplicate_of": None},
        {"question_id": "L1Q0", "decision": "keep", "reason": "valid", "duplicate_of": None},
    ],
    [
        {"question_id": "L0Q0", "decision": "drop", "reason": "duplicate", "duplicate_of": "L0Q1"},
        {"question_id": "L0Q1", "decision": "drop", "reason": "duplicate", "duplicate_of": "L1Q0"},
        {"question_id": "L1Q0", "decision": "keep", "reason": "valid", "duplicate_of": None},
    ],
    [
        {"question_id": "L0Q0", "decision": "drop", "reason": "duplicate", "duplicate_of": "L0Q1"},
        {"question_id": "L0Q1", "decision": "drop", "reason": "duplicate", "duplicate_of": "L0Q0"},
        {"question_id": "L1Q0", "decision": "keep", "reason": "valid", "duplicate_of": None},
    ],
])
async def test_audit_rejects_self_references_duplicate_chains_cycles_and_dropped_targets(decisions: list[dict[str, object]]) -> None:
    assessment = CourseAssessment(assessments=[
        LessonAssessment("Lesson one", mcq=[_question("First"), _question("Second")]),
        LessonAssessment("Lesson two", mcq=[_question("Third")]),
    ])
    answers = _answers([
        {"id": "L0Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"},
        {"id": "L0Q1", "valid_option_indices": [0], "quality": "valid", "reason": "ok"},
        {"id": "L1Q0", "valid_option_indices": [0], "quality": "valid", "reason": "ok"},
    ])
    review = {"decisions": decisions, "coverage": [
        {"lesson_index": 0, "uncovered_objective_indices": [], "uncovered_content_objective_indices": []},
        {"lesson_index": 1, "uncovered_objective_indices": [], "uncovered_content_objective_indices": []},
    ]}

    with pytest.raises(ValueError):
        await audit_course_assessment(FakeLLM(answers, review), _course_content(), assessment)


@pytest.mark.asyncio
async def test_audit_skips_both_calls_for_zero_initial_questions() -> None:
    assessment = CourseAssessment(assessments=[LessonAssessment("Lesson one"), LessonAssessment("Lesson two")])
    llm = FakeLLM()
    result = await audit_course_assessment(llm, _course_content(), assessment)
    assert result.assessment is assessment
    assert result.uncovered_objectives == [(0, 0), (1, 0)]
    assert result.decisions == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_audit_checks_cancellation_before_and_after_each_model_await() -> None:
    for checkpoint_to_cancel, expected_calls in ((1, 0), (2, 0), (3, 1), (4, 1), (5, 2)):
        llm = FakeLLM(_answers(), _review())
        checkpoints = 0

        async def cancel_at_checkpoint(expected_checkpoint: int = checkpoint_to_cancel) -> None:
            nonlocal checkpoints
            checkpoints += 1
            if checkpoints == expected_checkpoint:
                raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await audit_course_assessment(llm, _course_content(), _assessment(), check_cancelled=cancel_at_checkpoint)
        assert len(llm.calls) == expected_calls


@pytest.mark.asyncio
async def test_audit_rejects_assessment_content_lesson_count_mismatch_before_model_call() -> None:
    llm = FakeLLM(_answers(), _review())
    mismatched = CourseAssessment(assessments=[LessonAssessment("Lesson one")])
    with pytest.raises(ValueError, match="lesson alignment mismatch"):
        await audit_course_assessment(llm, _course_content(), mismatched)
    assert llm.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("assessment", [
    CourseAssessment(assessments=[
        LessonAssessment("Lesson one", true_false=[TrueFalseQuestion("A statement", True)]),
        LessonAssessment("Lesson two"),
    ]),
    CourseAssessment(assessments=[
        LessonAssessment("Lesson one", matching=[MatchingQuestion("Match", [MatchingPair("left", "right")])]),
        LessonAssessment("Lesson two"),
    ]),
])
async def test_audit_rejects_unaudited_non_mcq_questions_before_model_call(assessment: CourseAssessment) -> None:
    llm = FakeLLM(_answers(), _review())

    with pytest.raises(ValueError, match="non-mcq|unsupported"):
        await audit_course_assessment(llm, _course_content(), assessment)

    assert llm.calls == []


@pytest.mark.asyncio
async def test_audit_rejects_equal_count_assessments_with_swapped_lesson_titles_before_model_call() -> None:
    llm = FakeLLM(_answers(), _review())
    swapped = CourseAssessment(assessments=[
        LessonAssessment("Lesson two", mcq=[_question("Question assigned to the wrong lesson")]),
        LessonAssessment("Lesson one", mcq=[_question("Other wrong lesson question")]),
    ])

    with pytest.raises(ValueError, match="lesson alignment mismatch|lesson title"):
        await audit_course_assessment(llm, _course_content(), swapped)

    assert llm.calls == []
