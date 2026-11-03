"""Length repair preserves the answer and touches only affected variants."""

import json

import pytest

from app.modules.ai.v3.models import V3Course
from app.modules.ai.v3.option_repair import repair_distractor_feedback, repair_length_shortcuts


def _lesson():
    variants = [{"variant_id": f"v{i}", "prompt": "question", "source_quote": "source",
                 "correct_option": {"text": "correct answer"},
                 "distractor_pool": [{"text": text} for text in
                                     (("a", "b", "c") if i < 3 else ("a", "b", "very long answer"))]}
                for i in range(4)]
    return V3Course.from_dict({"course_id": "c", "title": "t", "lessons": [
        {"lesson_id": "l", "content": "lesson", "cases": [{"case_id": "c", "variants": variants}]}]}).lessons[0]


def _response(ids):
    return {"repairs": [{"variant_id": variant_id, "distractors": [
        {"text": f"wrong {variant_id} long answer", "category": "procedural_confusion"},
        {"text": f"wrong {variant_id}", "category": "role_confusion"},
        {"text": f"no {variant_id}", "category": "unauthorized_action"}]} for variant_id in ids]}


@pytest.mark.asyncio
async def test_targets_only_shortcuts_and_preserves_all_correct_answers():
    lesson = _lesson()

    async def invoke(messages, _format):
        request = json.loads(messages[1]["content"])
        assert [row["variant_id"] for row in request["questions"]] == ["v0", "v1", "v2"]
        assert all(row["correct_original"] == "correct answer" for row in request["questions"])
        return _response(["v0", "v1", "v2"])

    repaired = await repair_length_shortcuts(lesson, ["Invariant 4: correct answer is longest"], ["source"], invoke)
    assert repaired.cases[0].variants[-1] == lesson.cases[0].variants[-1]
    assert all(v.correct_option.text == "correct answer" for v in repaired.cases[0].variants)
    assert repaired.content == lesson.content


@pytest.mark.asyncio
async def test_rejects_model_attempt_to_replace_correct_answer_and_does_not_retry():
    calls = []

    async def invoke(_messages, _format):
        calls.append(1)
        response = _response(["v0", "v1", "v2"])
        response["repairs"][0]["correct"] = "changed"
        return response

    with pytest.raises(ValueError, match="v3_targeted_repair_invalid"):
        await repair_length_shortcuts(_lesson(), ["correct answer is longest"], ["source"], invoke)
    assert calls == [1]


@pytest.mark.asyncio
async def test_unknown_provider_outcome_propagates_without_retry():
    calls = []

    async def invoke(_messages, _format):
        calls.append(1)
        raise TimeoutError("unknown")

    with pytest.raises(TimeoutError):
        await repair_length_shortcuts(_lesson(), ["correct answer is longest"], ["source"], invoke)
    assert calls == [1]


@pytest.mark.asyncio
async def test_combined_mean_bias_and_shortcut_requests_targeted_length_ranges():
    async def invoke(messages, _format):
        assert "target_average_wrong_min" in messages[0]["content"]
        payload = json.loads(messages[1]["content"])["questions"]
        assert all(item["target_average_wrong_min"] <= item["target_average_wrong_max"] for item in payload)
        return _response([item["variant_id"] for item in payload])

    original = _lesson()
    result = await repair_length_shortcuts(original,
        ["Invariant 4 failed: length bias ratio", "Invariant 4 (Shortcut Gate): correct answer is longest"],
        ["source"], invoke)
    assert all(a.correct_option == b.correct_option for a, b in
               zip(original.cases[0].variants, result.cases[0].variants, strict=True))


@pytest.mark.asyncio
async def test_critic_guided_repair_changes_only_flagged_wrong_option():
    lesson = _lesson()
    original = lesson.cases[0].variants[0]
    options = original.assemble_question(seed=111).options
    index = next(i for i, opt in enumerate(options) if not opt.is_correct)
    flagged = [{"index": index, "verdict": "UNCERTAIN", "summary": "unsupported exception"}]

    async def invoke(messages, _format):
        request = json.loads(messages[1]["content"])
        assert request["feedback"][0]["index"] == index
        return {"repairs": [{"index": index, "replacement": "contradictory action"}]}

    fixed = await repair_distractor_feedback(lesson, original.variant_id, flagged, ["source"], invoke)
    changed = fixed.cases[0].variants[0]
    assert changed.correct_option == original.correct_option
    assert fixed.cases[0].variants[1:] == lesson.cases[0].variants[1:]
    assert sum(a != b for a, b in zip(original.distractor_pool, changed.distractor_pool, strict=True)) == 1


@pytest.mark.asyncio
async def test_critic_guided_repair_rejects_correct_answer_target_without_call():
    lesson = _lesson()
    variant = lesson.cases[0].variants[0]
    options = variant.assemble_question(seed=111).options
    index = next(i for i, option in enumerate(options) if option.is_correct)
    calls = []

    async def invoke(_messages, _format):
        calls.append(1)
        return {}

    with pytest.raises(ValueError, match="v3_distractor_feedback_invalid"):
        await repair_distractor_feedback(lesson, variant.variant_id,
            [{"index": index, "verdict": "UNCERTAIN", "summary": "ambiguous"}], ["source"], invoke)
    assert not calls
