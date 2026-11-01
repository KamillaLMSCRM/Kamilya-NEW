"""Scoped repair cannot lose variants, sources, or lesson identity."""

from dataclasses import replace

import pytest

from app.modules.ai.v3.models import V3Course, V3Option
from app.modules.ai.v3.option_repair import repair_options
from app.modules.ai.v3.service import _repair_option_shortcuts
from app.modules.ai.v3.validator import validate_v3_course


def saved_lesson():
    case = {"case_id": "c", "rule_id": "r", "variants": [
        {"variant_id": "v1", "scenario_premise": "ситуация", "prompt": "вопрос?",
         "correct_option": {"text": "правильно"}, "source_quote": "точная цитата",
         "distractor_pool": [{"text": "а"}, {"text": "б"}, {"text": "в"}]},
        {"variant_id": "v2", "scenario_premise": "другая ситуация", "prompt": "вопрос?",
         "correct_option": {"text": "достоверно"}, "source_quote": "другая цитата",
         "distractor_pool": [{"text": "г"}, {"text": "д"}, {"text": "е"}]},
    ]}
    return V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
                               "lessons": [{"lesson_id": "l", "title": "урок", "content": "текст",
                                            "cases": [case]}]}).lessons[0]


def payload(variant_id):
    return {"variant_id": variant_id, "correct": "новый ответ", "explanation": "объяснение",
            "distractors": [{"text": text, "category": "procedural_confusion"} for text in ("один", "два", "три")]}


@pytest.mark.parametrize(("shortest", "expected"), [(5, True), (3, False)])
def test_reverse_length_shortcut_is_detected_without_treating_ties_as_shortest(shortest, expected):
    lesson = saved_lesson()
    original = lesson.cases[0].variants[0]
    variants = tuple(replace(original, variant_id=f"v{i}",
                             correct_option=V3Option(text="x" * (10 if i < shortest else 12), is_correct=True),
                             distractor_pool=tuple(V3Option(text="y" * n, is_correct=False) for n in (11, 12, 13)))
                     for i in range(7))
    lesson = replace(lesson, cases=(replace(lesson.cases[0], variants=variants),))
    course = V3Course(course_id="c", title="t", document_sha256="a" * 64, lessons=(lesson,))
    report = validate_v3_course(course, source_document_text="точная цитата")
    assert report.metrics.shortest_correct_count == shortest
    assert any("correct answer is shortest" in violation for violation in report.violations) is expected


@pytest.mark.asyncio
async def test_repair_keeps_every_question_context_and_original_source():
    async def invoke(messages, response_format):
        assert "точный исходный текст" in messages[1]["content"]
        return {"repairs": [payload("v1"), payload("v2")]}

    before = saved_lesson()
    after = await repair_options(before, ["ошибка длины"], ["точный исходный текст"], invoke)
    assert after.content == before.content and after.lesson_id == before.lesson_id
    for old, new in zip(before.cases[0].variants, after.cases[0].variants, strict=True):
        assert (new.variant_id, new.scenario_premise, new.prompt, new.source_quote) == (
            old.variant_id, old.scenario_premise, old.prompt, old.source_quote)
        assert len(new.distractor_pool) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [[payload("v1")], [payload("v1"), payload("v1")],
                                    [payload("v1"), payload("unknown")]])
async def test_partial_duplicate_or_foreign_variant_repairs_fail_closed(items):
    async def invoke(messages, response_format):
        return {"repairs": items}

    with pytest.raises(ValueError, match="v3_option_repair_"):
        await repair_options(saved_lesson(), ["ошибка"], ["источник"], invoke)


@pytest.mark.asyncio
async def test_shortcut_repair_rechecks_complete_lesson_without_claiming_semantics():
    calls = []

    async def invoke(messages, response_format):
        calls.append(1)
        repairs = []
        for variant_id, words in (("v1", ("неверныйxx", "ложноxx", "ошибкаxx")),
                                  ("v2", ("неверныйyyy", "ложноyyy", "ошибкаyyy"))):
            repairs.append({"variant_id": variant_id,
                            "distractors": [{"text": word, "category": "procedural_confusion"} for word in words]})
        return {"repairs": repairs}

    source = "точная цитата и другая цитата"
    before = saved_lesson()
    after, changed = await _repair_option_shortcuts(before, source, "a" * 64, [source], invoke)
    assert changed and len(calls) == 1
    assert after.content == before.content
    assert [v.source_quote for v in after.cases[0].variants] == [v.source_quote for v in before.cases[0].variants]

    untouched, changed = await _repair_option_shortcuts(before, source, "a" * 64, [], invoke)
    assert not changed and untouched == before and len(calls) == 1

@pytest.mark.asyncio
async def test_partial_repair_requests_only_missing_variant_once_and_keeps_existing_repairs():
    before = saved_lesson()
    calls = []

    async def invoke(messages, response_format):
        calls.append(messages[1]["content"])
        if len(calls) == 1:
            return {"repairs": [payload("v1")]}
        assert '"variant_id":"v2"' in calls[-1]
        assert '"variant_id":"v1"' not in calls[-1]
        return {"repairs": [payload("v2")]}

    after = await repair_options(before, ["ошибка длины"], ["источник"], invoke)
    assert len(calls) == 2
    assert [v.variant_id for v in after.cases[0].variants] == ["v1", "v2"]
    assert [v.source_quote for v in after.cases[0].variants] == ["точная цитата", "другая цитата"]


@pytest.mark.asyncio
async def test_partial_repair_cannot_loop_or_accept_missing_variant():
    calls = []

    async def invoke(messages, response_format):
        calls.append(1)
        return {"repairs": [payload("v1")]} if len(calls) == 1 else {"repairs": []}

    with pytest.raises(ValueError, match="v3_option_repair_incomplete"):
        await repair_options(saved_lesson(), ["ошибка"], ["источник"], invoke)
    assert len(calls) == 2

@pytest.mark.asyncio
async def test_partial_repair_unknown_target_is_not_reissued_after_resume():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_partitioned_extraction import Journal

    journal = Journal()
    calls = []

    async def checkpointed(messages, response_format):
        async def provider():
            calls.append(1)
            if len(calls) == 1:
                return {"repairs": [payload("v1")]}
            raise TimeoutError("unknown targeted outcome")
        return await stage_once(journal=journal, stage="repair", group_id="group-1", source_sha256="a" * 64,
                                route_fingerprint="b" * 64, messages=messages, response_format=response_format,
                                invoke=provider)

    with pytest.raises(TimeoutError):
        await repair_options(saved_lesson(), ["error"], ["source"], checkpointed)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await repair_options(saved_lesson(), ["error"], ["source"], checkpointed)
    assert len(calls) == 2

@pytest.mark.asyncio
async def test_partial_repair_can_keep_original_missing_variant_when_complete_lesson_passes():
    before = saved_lesson()
    calls = []
    inspected = []

    async def invoke(messages, response_format):
        calls.append(1)
        return {"repairs": [payload("v1")]}

    def accept(candidate):
        inspected.append(candidate)
        return True

    after = await repair_options(before, ["length error"], ["source"], invoke, accept_partial=accept)
    assert len(calls) == 1 and inspected == [after]
    assert after.cases[0].variants[1] == before.cases[0].variants[1]
    assert after.cases[0].variants[0] != before.cases[0].variants[0]


@pytest.mark.asyncio
async def test_failed_whole_lesson_check_requests_missing_variant():
    calls = []

    async def invoke(messages, response_format):
        calls.append(1)
        return {"repairs": [payload("v1" if len(calls) == 1 else "v2")]}

    await repair_options(saved_lesson(), ["length error"], ["source"], invoke, accept_partial=lambda _: False)
    assert len(calls) == 2
