"""A case candidate must pass all semantic checks before promotion."""

from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.case_repair_gate import (
    answer_review_fingerprint,
    case_compatibility_identity_matches,
    review_staged_case,
)
from app.modules.ai.v3.models import RuleEntity, V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase


def fixture():
    source = "Обязательна проверка документа."
    doc = DirectSourceDocument(doc_id="d", title="d", filename="d", category="general",
                               source_revision="r", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(doc,), total_chars=len(source), total_chunks=0)
    rule = RuleEntity(rule_id="rule", section="s", title="t", statement=source, doc_id="d",
                      source_revision="r", source_start=0, source_end=len(source), source_quote=source)
    variant = V3QuestionVariant(variant_id="v1", branch_context="Филиал А", scenario_premise="Ситуация",
        prompt="Что делать?", correct_option=V3Option(text="Проверить", is_correct=True),
        distractor_pool=(V3Option(text="Пропустить", is_correct=False), V3Option(text="Отказать", is_correct=False),
                         V3Option(text="Отложить", is_correct=False)), explanation="Нужна проверка.", source_quote=source)
    case = V3ScenarioCase(case_id="c1", rule_id="rule", learning_objective="Проверка", variants=(variant,))
    lesson = V3Lesson(lesson_id="l", title="t", module_title="m", content="", covered_rule_ids=("rule",), cases=(case,))
    return lesson, rule, corpus, source


def test_compatibility_projection_cannot_be_unrelated_or_duplicate():
    lesson, _, _, _ = fixture()
    variant = lesson.cases[0].variants[0]
    question = variant.assemble_question(seed=42)
    assert case_compatibility_identity_matches(replace(lesson, questions=(question,)), "c1")
    assert not case_compatibility_identity_matches(replace(lesson, questions=(replace(question, prompt="Другое"),)), "c1")
    repeated = replace(question, options=(question.options[0], question.options[1], question.options[1], question.options[3]))
    assert not case_compatibility_identity_matches(replace(lesson, questions=(repeated,)), "c1")


def test_cached_answer_review_is_bound_to_order_and_source_context():
    options = [("correct", True), ("first", False), ("second", False), ("third", False)]
    original = answer_review_fingerprint("branch", "question", options, "rule", ["source"], ("reference",))
    assert answer_review_fingerprint("branch", "question", list(reversed(options)), "rule", ["source"], ("reference",)) != original
    assert answer_review_fingerprint("other branch", "question", options, "rule", ["source"], ("reference",)) != original
    assert answer_review_fingerprint("branch", "question", options, "rule", ["new source"], ("reference",)) != original


class FakeReview:
    def __init__(self, failure):
        self.failure = failure
        self.explanation_consistency = True
        self.calls = []

    async def review_lesson(self, *args, **kwargs):
        self.calls.append("critic")
        return {"verdict": "NEEDS_REVISION" if self.failure == "critic" else "PASS", "factual_score": 5,
                "alignment_score": 5, "didactic_score": 5, "summary": "Проверка выполнена.",
                "defects": [{"issue": "Ошибка"}] if self.failure == "critic" else []}

    def options(self, texts, failure):
        return {"options": [{"index": i, "verdict": status,
            "claims": [{"claim": "Факт", "status": status, "reason": "Источник"}],
            "summary": "Проверено.", "omitted_required_elements": []}
            for i, text in enumerate(texts)
            for status in ["UNCERTAIN" if failure and text == "Проверить" else
                           ("SUPPORTED" if text == "Проверить" else "CONTRADICTED")]]}

    async def review_question_options(self, scenario, prompt, texts, units, context):
        assert "Филиал А" in scenario
        self.calls.append("options")
        return self.options(texts, self.failure == "option")

    async def review_question_compatibility(self, scenario, prompt, texts, units, context):
        self.calls.append("compatibility")
        if self.failure == "timeout":
            raise TimeoutError("unknown")
        return self.options(texts, self.failure == "compatibility")

    async def review_answer_completeness(self, scenario, prompt, answer, units, context, *, explanation, options):
        assert explanation and len(options) == 4
        self.calls.append("completeness")
        return {"answers": [{"index": 0, "omissions": ["объект"] if self.failure == "completeness" else []}],
                "explanation_review": {"verdict": "SUPPORTED", "claims": [{"claim": "Проверить", "status": "SUPPORTED", "reason": "Источник"}], "summary": "Проверено"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["critic", "option", "compatibility", "completeness", "timeout", None])
async def test_candidate_passes_every_stage_or_remains_unpromoted(failure):
    lesson, rule, corpus, source = fixture()
    pipeline = FakeReview(failure)
    record = {"original_review": {"defects": ["first failure"]}, "recheck": None}
    args = (lesson, "c1", [rule], corpus, [source], [source], (), False, pipeline, record)
    if failure == "timeout":
        with pytest.raises(TimeoutError):
            await review_staged_case(*args)
        assert record["original_review"]["defects"] and record["recheck"]
        assert record["answer_rechecks"][0]["review"]
        return
    accepted, cache = await review_staged_case(*args)
    assert accepted is (failure is None)
    if failure is None:
        assert set(cache) == {"v1"} and pipeline.calls == ["critic", "options", "compatibility", "completeness"]
    else:
        assert not cache and record["rejected"].startswith("candidate_")
    assert record["original_review"]["defects"] and record["recheck"]


@pytest.mark.asyncio
async def test_one_failed_variant_rejects_the_entire_multi_variant_candidate():
    lesson, rule, corpus, source = fixture()
    case = lesson.cases[0]
    second = replace(case.variants[0], variant_id="v2")
    lesson = replace(lesson, cases=(replace(case, variants=(*case.variants, second)),))

    class SecondFails(FakeReview):
        async def review_question_options(self, scenario, prompt, texts, units, context):
            self.calls.append("options")
            return self.options(texts, self.calls.count("options") == 2)

    record = {"original_review": {"defects": ["first failure"]}, "recheck": None}
    accepted, cache = await review_staged_case(lesson, "c1", [rule], corpus, [source], [source], (),
                                              False, SecondFails(None), record)
    assert not accepted and not cache and record["rejected"] == "candidate_option_review_failed"
    assert len(record["answer_rechecks"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("explanation", ["", "   "])
async def test_blank_candidate_explanation_holds_before_review(explanation):
    lesson, rule, corpus, source = fixture()
    case = lesson.cases[0]
    variant = replace(case.variants[0], explanation=explanation)
    lesson = replace(lesson, cases=(replace(case, variants=(variant,)),))
    pipeline = FakeReview(None)
    record = {}
    accepted, cache = await review_staged_case(lesson, "c1", [rule], corpus, [source], [source], (), False, pipeline, record)
    assert not accepted and not cache and not pipeline.calls
    assert record["rejected"] == "candidate_explanation_identity_invalid"
