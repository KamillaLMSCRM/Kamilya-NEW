"""A review defect may be repaired only in its identified case."""

from dataclasses import replace

import pytest

from app.modules.ai.v3.models import V3Course
from app.modules.ai.v3.service import _repair_reviewed_case


def lesson_fixture():
    def case(case_id):
        return {"case_id": case_id, "rule_id": "r", "variants": [{
            "variant_id": case_id + "-v", "scenario_premise": "ситуация", "prompt": "вопрос?",
            "correct_option": {"text": "a" * 12}, "source_quote": "точная цитата",
            "distractor_pool": [{"text": "b" * 12}, {"text": "c" * 12}, {"text": "d" * 12}],
            "explanation": "объяснение",
        }]}
    return V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
                               "lessons": [{"lesson_id": "l", "title": "урок", "content": "текст",
                                            "cases": [case("case-1"), case("case-2")]}]}).lessons[0]


def defect(case_id="case-2"):
    return {"verdict": "PASS", "defects": [{"scope": "question", "question_id": case_id,
            "issue": "вариант неоднозначен", "recommendation": "уточнить вариант"}]}


@pytest.mark.asyncio
async def test_review_defect_repairs_only_identified_case_and_preserves_its_context():
    lesson = lesson_fixture()
    part = replace(lesson, cases=(lesson.cases[1],), questions=())

    async def invoke(messages, response_format):
        assert "case-2-v" in messages[1]["content"]
        assert "case-1-v" not in messages[1]["content"]
        assert "уточнить вариант" not in messages[1]["content"]
        assert "правильный ответ дословно" in messages[0]["content"].lower()
        return {"repairs": [{"variant_id": "case-2-v", "correct": "a" * 12,
                "explanation": "новое объяснение", "distractors": [
                    {"text": text, "category": "procedural_confusion"} for text in ("e" * 12, "f" * 12, "g" * 12)]}]}

    updated, changed = await _repair_reviewed_case(
        lesson, part, defect(), "точная цитата", "a" * 64, ["точная цитата"], invoke)
    assert changed and updated.cases[0] == lesson.cases[0]
    old, new = lesson.cases[1].variants[0], updated.cases[1].variants[0]
    assert (old.scenario_premise, old.prompt, old.source_quote, old.correct_option) == (
        new.scenario_premise, new.prompt, new.source_quote, new.correct_option)
    assert new.distractor_pool != old.distractor_pool


@pytest.mark.asyncio
async def test_repair_preserves_other_exported_questions():
    lesson = lesson_fixture()
    lesson = replace(lesson, questions=tuple(case.variants[0].assemble_question(seed=99) for case in lesson.cases))

    async def invoke(messages, response_format):
        return {"repairs": [{"variant_id": "case-2-v", "correct": "a" * 12, "explanation": "обоснование",
                "distractors": [{"text": text, "category": "procedural_confusion"}
                                for text in ("e" * 12, "f" * 12, "g" * 12)]}]}

    updated, changed = await _repair_reviewed_case(
        lesson, replace(lesson, cases=(lesson.cases[1],), questions=()), defect(),
        "точная цитата", "a" * 64, ["точная цитата"], invoke)
    assert changed and updated.questions[0] == lesson.questions[0]


@pytest.mark.asyncio
async def test_semantic_repair_cannot_change_correct_answer():
    lesson = lesson_fixture()

    async def invoke(messages, response_format):
        return {"repairs": [{"variant_id": "case-2-v", "correct": "z" * 12, "explanation": "обоснование",
                "distractors": [{"text": text, "category": "procedural_confusion"}
                                for text in ("e" * 12, "f" * 12, "g" * 12)]}]}

    with pytest.raises(ValueError, match="v3_semantic_repair_changed_correct_answer"):
        await _repair_reviewed_case(lesson, replace(lesson, cases=(lesson.cases[1],)), defect(),
                                    "точная цитата", "a" * 64, ["точная цитата"], invoke)


@pytest.mark.asyncio
async def test_unchanged_correct_answer_keeps_original_metadata():
    lesson = lesson_fixture()
    case = lesson.cases[1]
    variant = case.variants[0]
    variant = replace(variant, correct_option=replace(variant.correct_option, distractor_rationale="retained"))
    case = replace(case, variants=(variant,))
    lesson = replace(lesson, cases=(lesson.cases[0], case))

    async def invoke(messages, response_format):
        return {"repairs": [{"variant_id": "case-2-v", "correct": "a" * 12, "explanation": "обоснование",
                "distractors": [{"text": text, "category": "procedural_confusion"}
                                for text in ("e" * 12, "f" * 12, "g" * 12)]}]}

    updated, changed = await _repair_reviewed_case(
        lesson, replace(lesson, cases=(case,)), defect(), "точная цитата", "a" * 64, ["точная цитата"], invoke)
    assert changed and updated.cases[1].variants[0].correct_option == variant.correct_option


@pytest.mark.asyncio
async def test_variant_scoped_defect_preserves_sibling_variants():
    lesson = lesson_fixture()
    case = lesson.cases[1]
    sibling = replace(case.variants[0], variant_id="case-2-v2")
    case = replace(case, variants=case.variants + (sibling,))
    lesson = replace(lesson, cases=(lesson.cases[0], case))

    async def invoke(messages, response_format):
        assert "case-2-v2" not in messages[1]["content"]
        return {"repairs": [{"variant_id": "case-2-v", "correct": "a" * 12, "explanation": "обоснование",
                "distractors": [{"text": text, "category": "procedural_confusion"}
                                for text in ("e" * 12, "f" * 12, "g" * 12)]}]}

    updated, changed = await _repair_reviewed_case(
        lesson, replace(lesson, cases=(case,)), defect("case-2-v"), "точная цитата", "a" * 64,
        ["точная цитата"], invoke)
    assert changed and updated.cases[1].variants[1] == sibling


@pytest.mark.asyncio
async def test_second_variant_repair_does_not_reassemble_first_exported_question():
    lesson = lesson_fixture()
    case = lesson.cases[1]
    sibling = replace(case.variants[0], variant_id="case-2-v2")
    case = replace(case, variants=case.variants + (sibling,))
    cases = (lesson.cases[0], case)
    lesson = replace(lesson, cases=cases, questions=tuple(c.variants[0].assemble_question(seed=99) for c in cases))

    async def invoke(messages, response_format):
        return {"repairs": [{"variant_id": "case-2-v2", "correct": "a" * 12, "explanation": "обоснование",
                "distractors": [{"text": text, "category": "procedural_confusion"}
                                for text in ("e" * 12, "f" * 12, "g" * 12)]}]}

    updated, changed = await _repair_reviewed_case(
        lesson, replace(lesson, cases=(case,), questions=()), defect("case-2-v2"),
        "точная цитата", "a" * 64, ["точная цитата"], invoke)
    assert changed and updated.questions == lesson.questions


@pytest.mark.asyncio
@pytest.mark.parametrize("review", [defect("unknown"), {"verdict": "FAIL", "defects": [
    {"scope": "lesson", "question_id": "case-2", "issue": "ошибка в уроке"}]},
    {"verdict": "FAIL", "defects": [{"scope": "question", "question_id": [], "issue": "ошибка"}]}])
async def test_unscoped_defect_never_triggers_repair(review):
    lesson = lesson_fixture()
    async def forbidden(*args):
        pytest.fail("unscoped issue must not trigger a model call")
    updated, changed = await _repair_reviewed_case(
        lesson, replace(lesson, cases=(lesson.cases[1],)), review, "точная цитата", "a" * 64,
        ["точная цитата"], forbidden)
    assert not changed and updated == lesson
