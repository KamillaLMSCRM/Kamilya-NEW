"""A failed complete repair is held, not a fatal course or a quality pass."""
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.v3 import option_repair
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.models import V3Course, V3Option
from app.modules.ai.v3.service import _repair_option_shortcuts
from app.modules.ai.v3.validator import validate_v3_course
from tests.unit.test_v3_option_repair import saved_lesson

SOURCE = "точная цитата и другая цитата"


def lesson_with_lengths(lengths):
    lesson = saved_lesson()
    variants = tuple(replace(
        lesson.cases[0].variants[0], variant_id=f"v{i}",
        correct_option=V3Option(text="правильный ответ", is_correct=True),
        distractor_pool=tuple(V3Option(text=char * size, is_correct=False)
                              for char, size in zip("абв", sizes, strict=True)),
    ) for i, sizes in enumerate(lengths))
    # Separate cases make the cross-variant diversity invariant independent.
    return replace(lesson, cases=tuple(replace(lesson.cases[0], case_id=f"c{i}", variants=(v,))
                                        for i, v in enumerate(variants)))


def report(lesson):
    return validate_v3_course(V3Course(course_id="c", title="t", document_sha256="a" * 64,
                                      lessons=(lesson,)), source_document_text=SOURCE)


@pytest.mark.asyncio
async def test_saved_failure_class_gets_one_narrow_progress_based_followup(monkeypatch):
    original = lesson_with_lengths([(3, 4, 5)] * 6)
    # Correct length is 16: mean becomes balanced, but 4/6 remain longest.
    intermediate = lesson_with_lengths([(14, 14, 15)] * 4 + [(15, 17, 18)] * 2)
    resolved = lesson_with_lengths([(15, 17, 18)] * 6)
    assert report(original).structural_verdict == "FAIL"
    assert report(intermediate).metrics.longest_correct_count == 4
    assert report(resolved).structural_verdict == "PASS"
    repair = AsyncMock(side_effect=[intermediate, resolved])
    monkeypatch.setattr(option_repair, "repair_length_shortcuts", repair)
    after, changed = await _repair_option_shortcuts(original, SOURCE, "a" * 64, [SOURCE], AsyncMock(), convergent_repair=True)
    assert changed and after == resolved and repair.await_count == 2
    second = repair.await_args_list[1]
    assert second.args[0] == intermediate
    assert all("correct answer is longest" in issue for issue in second.args[1])
    assert original.cases[0].variants[0].distractor_pool[0].text == "а" * 3


@pytest.mark.asyncio
async def test_remaining_defect_is_held_without_a_third_request(monkeypatch):
    original = lesson_with_lengths([(3, 4, 5)] * 6)
    intermediate = lesson_with_lengths([(14, 14, 15)] * 4 + [(15, 17, 18)] * 2)
    repair = AsyncMock(side_effect=[intermediate, intermediate])
    monkeypatch.setattr(option_repair, "repair_length_shortcuts", repair)
    after, changed = await _repair_option_shortcuts(original, SOURCE, "a" * 64, [SOURCE], AsyncMock(), convergent_repair=True)
    assert after is original and not changed and repair.await_count == 2
    assert report(after).structural_verdict == "FAIL"
    assert report(after).metrics.longest_correct_percent == 100


@pytest.mark.asyncio
async def test_no_measurable_progress_does_not_repeat_repair(monkeypatch):
    original = lesson_with_lengths([(3, 4, 5)] * 6)
    repair = AsyncMock(return_value=original)
    monkeypatch.setattr(option_repair, "repair_length_shortcuts", repair)
    after, changed = await _repair_option_shortcuts(original, SOURCE, "a" * 64, [SOURCE], AsyncMock(), convergent_repair=True)
    assert after is original and not changed and repair.await_count == 1


@pytest.mark.asyncio
async def test_unknown_followup_outcome_is_preserved_and_not_turned_into_safe_hold(monkeypatch):
    original = lesson_with_lengths([(3, 4, 5)] * 6)
    intermediate = lesson_with_lengths([(14, 14, 15)] * 4 + [(15, 17, 18)] * 2)
    repair = AsyncMock(side_effect=[intermediate, ExtractionOutcomeUnknownError("unknown")])
    monkeypatch.setattr(option_repair, "repair_length_shortcuts", repair)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await _repair_option_shortcuts(original, SOURCE, "a" * 64, [SOURCE], AsyncMock(), convergent_repair=True)
    assert repair.await_count == 2


@pytest.mark.asyncio
async def test_historical_protocol_keeps_request_arguments_and_failure_without_followup(monkeypatch):
    original = lesson_with_lengths([(3, 4, 5)] * 6)
    repair = AsyncMock(return_value=original)
    monkeypatch.setattr(option_repair, "repair_length_shortcuts", repair)
    with pytest.raises(ValueError, match="v3_option_repair_failed_validation"):
        await _repair_option_shortcuts(original, SOURCE, "a" * 64, [SOURCE], AsyncMock())
    assert repair.await_count == 1 and "measured_feedback" not in repair.await_args.kwargs


def test_v4_is_still_readable_and_fresh_jobs_choose_v5():
    from app.modules.ai.v3.revision_policy import (
        AUXILIARY_REVIEW_POLICY, REVIEW_KEY, REVIEW_POLICY, read_review_policy, stamp_policy,
    )
    assert AUXILIARY_REVIEW_POLICY == "v3-batched-decision-review-v4"
    assert read_review_policy({REVIEW_KEY: AUXILIARY_REVIEW_POLICY}) == AUXILIARY_REVIEW_POLICY
    assert REVIEW_POLICY == "v3-batched-decision-review-v5"
    assert stamp_policy({})[REVIEW_KEY] == REVIEW_POLICY
