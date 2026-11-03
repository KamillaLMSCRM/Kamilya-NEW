"""Strict citation support contracts; source provenance is checked separately."""

import json
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.citation_review import (
    bind_displayed_citation,
    build_citation_review_items,
    review_displayed_citations,
    validate_citation_review,
)
from app.modules.ai.v3.models import RuleEntity, V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase


def row(key, verdict="COMPLETE", unsupported=None):
    return {"id": key, "verdict": verdict, "unsupported": unsupported or [], "summary": "Проверено"}


@pytest.mark.parametrize("value", [
    {}, {"items": []}, {"items": [row("a"), row("a")]}, {"items": [row("a"), row("c")]},
    {"items": [row("a"), {**row("b"), "verdict": {}}]},
    {"items": [row("a"), {**row("b"), "unsupported": [""]}]},
    {"items": [row("a"), row("b", "COMPLETE", ["нет действия"])]},
    {"items": [row("a"), row("b", "PARTIAL")]},
    {"items": [row("a"), {**row("b"), "extra": "unexpected"}]},
])
def test_invalid_batches_do_not_certify_any_citation(value):
    with pytest.raises(ValueError):
        validate_citation_review(value, ("a", "b"))


@pytest.mark.asyncio
async def test_partial_and_complete_quotes_are_reviewed_independently():
    items = [{"id": key, "scenario": "Филиал A", "question": "Что делать?", "answer": "Подписать и записать",
              "explanation": "Нужны оба действия", "displayed_quote": quote, "source_identity": "doc:rev:sha:0:10"}
             for key, quote in (("short", "Подписать"), ("full", "Подписать и записать"))]
    calls = []

    async def invoke(messages, response_format):
        calls.append((messages, response_format))
        payload = json.loads(messages[1]["content"])
        assert payload == {"items": items}
        return {"items": [row("short", "PARTIAL", ["записать"]), row("full")]}

    result = await review_displayed_citations(items, invoke)
    assert result["short"]["verdict"] == "PARTIAL" and result["full"]["verdict"] == "COMPLETE"
    assert len(calls) == 1

    for missing in ("scenario", "source_identity"):
        bad = dict(items[0])
        bad[missing] = ""
        with pytest.raises(ValueError):
            await review_displayed_citations([bad], invoke)
    assert len(calls) == 1


def test_citation_identity_requires_exact_unique_owned_source_span_and_revision():
    source = "Начало. Подписать и записать. Конец."
    doc = DirectSourceDocument(doc_id="d1", title="d", filename="d", category="general",
                               source_revision="r1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant1", documents=(doc,), total_chars=len(source), total_chunks=0)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", doc_id="d1",
                      source_revision="r1", source_start=0, source_end=len(source))
    quote = "Подписать и записать."
    identity = bind_displayed_citation(corpus, rule, quote)
    assert identity and len(identity) == 64
    assert bind_displayed_citation(replace(corpus, tenant_id="tenant2"), rule, quote) != identity
    revised_doc = replace(doc, source_revision="r2")
    assert bind_displayed_citation(replace(corpus, documents=(revised_doc,)),
                                   replace(rule, source_revision="r2"), quote) != identity
    relocated_doc = replace(doc, source_text="X" + source)
    relocated_rule = replace(rule, source_start=1, source_end=len(source) + 1)
    assert bind_displayed_citation(replace(corpus, documents=(relocated_doc,)), relocated_rule, quote) != identity
    assert bind_displayed_citation(corpus, replace(rule, source_revision="stale"), quote) is None
    assert bind_displayed_citation(corpus, replace(rule, source_end=5), quote) is None
    assert bind_displayed_citation(corpus, rule, "Подписать и  записать.") is None
    duplicated = replace(doc, source_text=source + quote)
    assert bind_displayed_citation(replace(corpus, documents=(duplicated,)), rule, quote) is None
    other = replace(doc, doc_id="d2")
    assert bind_displayed_citation(replace(corpus, documents=(doc, other)), rule, quote) == identity
    changed_doc = replace(doc, source_text=source + " Новое условие.")
    assert bind_displayed_citation(replace(corpus, documents=(changed_doc,)), rule, quote) != identity
    overlapping = replace(doc, source_text="аааа")
    assert bind_displayed_citation(replace(corpus, documents=(overlapping,)),
                                   replace(rule, source_end=4), "ааа") is None


def test_items_use_actual_branch_and_hold_wrong_source_or_duplicate_question():
    source = "В филиале А подписать и записать."
    doc = DirectSourceDocument(doc_id="d", title="d", filename="d", category="general",
                               source_revision="r", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(doc,), total_chars=len(source), total_chunks=0)
    rule = RuleEntity(rule_id="rule", section="s", title="t", statement="x", doc_id="d",
                      source_revision="r", source_start=0, source_end=len(source), source_quote=source)
    variant = V3QuestionVariant(variant_id="v1", branch_context="Филиал А", scenario_premise="Проверка",
        prompt="Что делать?", correct_option=V3Option(text="Подписать и записать", is_correct=True),
        distractor_pool=(V3Option(text="Только подписать", is_correct=False),
                         V3Option(text="Только записать", is_correct=False), V3Option(text="Ничего", is_correct=False)),
        explanation="Нужны оба действия.", source_quote="подписать и записать.")
    case = V3ScenarioCase(case_id="c1", rule_id="rule", learning_objective="Процедура", variants=(variant,))
    lesson = V3Lesson(lesson_id="l", title="t", module_title="m", content="", covered_rule_ids=("rule",),
                      cases=(case,))
    items, issues = build_citation_review_items(lesson, [rule], corpus)
    assert not issues and len(items) == 1 and "Филиал А" in items[0]["scenario"]
    assert items[0]["displayed_quote"] == variant.source_quote
    assert build_citation_review_items(lesson, [replace(rule, source_revision="stale")], corpus)[1]
    duplicate = replace(lesson, cases=(replace(case, variants=(variant, variant)),))
    assert build_citation_review_items(duplicate, [rule], corpus) == ([], ["duplicate_or_empty_question_id"])
    empty = replace(lesson, cases=(), questions=())
    assert build_citation_review_items(empty, [rule], corpus) == ([], ["no_questions"])
    fallback_question = replace(variant.assemble_question(seed=42), rule_id="rule")
    fallback = replace(lesson, cases=(), questions=(fallback_question,))
    fallback_items, fallback_issues = build_citation_review_items(fallback, [rule], corpus)
    assert not fallback_issues and fallback_items[0]["id"] == fallback_question.question_id
    foreign_case = replace(case, case_id="other", rule_id="unknown", variants=(replace(variant, variant_id="v2"),))
    mixed = replace(lesson, cases=(case, foreign_case))
    valid_items, mixed_issues = build_citation_review_items(mixed, [rule], corpus)
    assert len(valid_items) == 1 and mixed_issues == ["v2-assembled:unresolved_rule"]


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["PARTIAL", "UNKNOWN", "MALFORMED", "TIMEOUT", "FIXABLE",
                                     "FIXABLE_PARTIAL", "FIXABLE_UNKNOWN", "FIXABLE_MALFORMED", "FIXABLE_TIMEOUT"])
async def test_worker_holds_partial_quote_after_all_question_repairs(verdict):
    from app.modules.ai.direct_source import DirectSourceChunk
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.service import generate_v3_course_from_corpus
    from tests.unit.test_v3_partitioned_extraction import Journal

    source = "Правило первое. Правило второе."
    chunk = DirectSourceChunk(chunk_id="c", doc_id="d", doc_name="d", title="d", headings=(),
                              text=source, source_revision="rev", chunk_index=0)
    doc = DirectSourceDocument(doc_id="d", title="d", filename="d", category="general",
                               source_revision="rev", chunks=(chunk,), source_text=source)
    owned = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    calls = []

    async def invoke(messages, _format):
        system, user = messages[0]["content"], messages[1]["content"]
        if "Карту регламента" in system:
            target = user.split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": "r1", "section": "Раздел", "title": "Правило",
                               "statement": target, "source_quote": target}]}
        if "показанная цитата" in system:
            items = json.loads(user)["items"]
            calls.append(items)
            if verdict.startswith("FIXABLE"):
                if len(calls) > 1 and verdict == "FIXABLE_TIMEOUT":
                    raise TimeoutError("unknown candidate review outcome")
                if len(calls) > 1 and verdict == "FIXABLE_MALFORMED":
                    return {"items": []}
                response = ("PARTIAL" if len(calls) == 1 or verdict == "FIXABLE_PARTIAL"
                            else ("UNKNOWN" if verdict == "FIXABLE_UNKNOWN" else "COMPLETE"))
                return {"items": [row(item["id"], response, ["часть ответа"] if response == "PARTIAL" else [])
                                  for item in items]}
            if verdict == "TIMEOUT":
                raise TimeoutError("unknown citation review outcome")
            if verdict == "MALFORMED":
                return {"items": []}
            return {"items": [row(item["id"], verdict, ["часть ответа"] if verdict == "PARTIAL" else [])
                              for item in items]}
        if "независимый контролер" in system:
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5,
                    "didactic_score": 5, "summary": "Проверка выполнена.", "defects": []}
        if "Фактические утверждения текста урока" in user:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Факт", "status": "SUPPORTED",
                    "reason": "Источник"}], "summary": "Проверено."}
        if "ВАРИАНТЫ:\n" in user:
            options = json.loads(user.split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"index": item["index"], "verdict": "SUPPORTED" if item["text"] == "верный 1" else "CONTRADICTED",
                "claims": [{"claim": "Факт", "status": "SUPPORTED" if item["text"] == "верный 1" else "CONTRADICTED",
                            "reason": "Источник"}], "summary": "Проверено", "omitted_required_elements": []}
                for item in options]}
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Правило",
                "cases": [{"case_id": "c1", "rule_id": "r1", "variants": [{"variant_id": "v1",
                    "scenario_premise": "Ситуация", "prompt": "Вопрос", "correct_option": {"text": "верный 1"},
                    "source_quote": "Правило первое." if verdict.startswith("FIXABLE") else source,
                    "explanation": "Правильное действие соответствует правилу.",
                    "distractor_pool": [{"text": "ошибка 1"}, {"text": "ошибка 2"}, {"text": "ошибка 3"}]}]}]}

    journal = Journal()
    if verdict in {"TIMEOUT", "FIXABLE_TIMEOUT"}:
        with pytest.raises(TimeoutError):
            await generate_v3_course_from_corpus(owned, intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate_v3_course_from_corpus(owned, intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64)
        assert len(calls) == (1 if verdict == "TIMEOUT" else 2)
        if verdict == "FIXABLE_TIMEOUT":
            partial = await generate_v3_course_from_corpus(
                owned, intent=CourseIntent(), generation_client=invoke, extraction_journal=journal,
                route_fingerprint="a" * 64, allow_unreviewed_on_unknown=True,
            )
            assert partial.assessment.assessments[0].mcq[0].source_quote == "Правило первое."
            checks = partial.diagnostics["validation_report"]["semantic_reviews"]["l1"]["citation_checks"]
            assert checks[0]["review"]["verdict"] == "PARTIAL" and len(calls) == 2
        return
    result = await generate_v3_course_from_corpus(owned, intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64)
    if verdict == "FIXABLE":
        assert len(calls) == 2 and calls[0][0]["displayed_quote"] == "Правило первое."
        assert calls[1][0]["displayed_quote"] == source
        assert result.assessment.assessments[0].mcq[0].source_quote == source
        checks = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]["citation_checks"]
        assert checks[0]["review"]["verdict"] == "PARTIAL" and checks[0]["candidate_review"]["verdict"] == "COMPLETE"
        replay = await generate_v3_course_from_corpus(owned, intent=CourseIntent(), generation_client=invoke,
                                                     extraction_journal=journal, route_fingerprint="a" * 64)
        assert len(calls) == 2 and replay.assessment.assessments[0].mcq[0].source_quote == source
        return
    if verdict in {"FIXABLE_PARTIAL", "FIXABLE_UNKNOWN", "FIXABLE_MALFORMED"}:
        assert len(calls) == 2 and result.assessment.assessments[0].mcq[0].source_quote == "Правило первое."
        checks = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]["citation_checks"]
        assert checks[0]["review"]["verdict"] == "PARTIAL"
        if verdict == "FIXABLE_MALFORMED":
            assert "candidate_error" in checks[0]
        else:
            assert checks[0]["candidate_review"]["verdict"] == verdict.removeprefix("FIXABLE_")
        assert result.diagnostics["requires_source_review"]
        return
    assert len(calls) == 1 and calls[0][0]["displayed_quote"] == source, result.diagnostics["violations"]
    assert result.diagnostics["requires_source_review"]
    expected = "проверка цитат не завершена" if verdict == "MALFORMED" else f"цитата подтверждает ответ не полностью: {verdict}"
    assert any(expected in x for x in result.diagnostics["violations"])
    replay = await generate_v3_course_from_corpus(owned, intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64)
    assert len(calls) == 1 and replay.diagnostics["violations"] == result.diagnostics["violations"]
