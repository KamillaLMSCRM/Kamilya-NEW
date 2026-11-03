"""Source-unit extraction and same-job replay without provider calls."""

import json

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.models import RuleEntity, V3Course
from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model
from app.modules.ai.v3.service import (
    _bind_rendered_quote_candidates,
    _review_source_unit_fragments,
    find_quote_occurrences_in_corpus,
    generate_v3_course_from_corpus,
)


class Journal:
    tenant_id = "tenant-1"
    job_id = "job-1"

    def __init__(self):
        self.plans = {}
        self.values = {}

    async def prepare(self, key, plan):
        assert key not in self.plans or self.plans[key] == plan
        self.plans[key] = plan
        return self.values.get(key)

    async def save_value(self, key, value):
        assert key not in self.values or self.values[key] == value
        self.values[key] = value

    async def read_owned_value(self, key, expected_plan):
        return self.values.get(key) if self.plans.get(key) == expected_plan else None


def corpus():
    source = "Правило первое.\n\nПравило второе."
    chunk = DirectSourceChunk(chunk_id="c1", doc_id="d1", doc_name="s", title="s", headings=(),
                              text=source, source_revision="revision", chunk_index=0)
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="revision", chunks=(chunk,), source_text=source)
    return DirectSourceCorpus(tenant_id="tenant-1", documents=(document,), total_chars=len(source), total_chunks=1)


def test_quote_binding_requires_unique_match_in_owned_revision_and_keeps_review_signal():
    source = "Начало: условие<br>действие. Конец."
    doc = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                               source_revision="rev1", chunks=(), source_text=source)
    input_corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=0)
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "lessons": [{"lesson_id": "l", "title": "t",
        "cases": [{"case_id": "c1", "rule_id": "r1", "variants": [{"variant_id": "v1",
            "scenario_premise": "ситуация", "prompt": "вопрос", "correct_option": {"text": "верно"},
            "distractor_pool": [{"text": "1"}, {"text": "2"}, {"text": "3"}],
            "source_quote": "условие действие"}]}]}]}).lessons[0]
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="текст", doc_id="d1",
                      source_revision="rev1", source_start=0, source_end=len(source))
    bound, warnings = _bind_rendered_quote_candidates(lesson, [rule], input_corpus)
    assert bound.cases[0].variants[0].source_quote == "условие<br>действие"
    assert warnings and "провер" in warnings[0].lower()
    stale, warnings = _bind_rendered_quote_candidates(lesson, [RuleEntity(
        rule_id="r1", section="s", title="t", statement="текст", doc_id="d1",
        source_revision="old", source_start=0, source_end=len(source))], input_corpus)
    assert stale == lesson and not warnings
    duplicated = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
        source_revision="rev1", chunks=(), source_text=source + source)
    other = DirectSourceCorpus(tenant_id="tenant-1", documents=(duplicated,), total_chars=2*len(source), total_chunks=0)
    unchanged, warnings = _bind_rendered_quote_candidates(lesson, [rule], other)
    assert unchanged == lesson and not warnings


@pytest.mark.parametrize(("source", "quote"), [
    ("| Категория А | 100 |\n| Категория Б | 200 |", "100 Категория Б"),
    ("| A | B C |", "A B | C"),
])
def test_quote_binding_does_not_merge_distinct_table_rows(source, quote):
    doc = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                               source_revision="rev1", chunks=(), source_text=source)
    input_corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=0)
    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "lessons": [{"lesson_id": "l", "title": "t",
        "cases": [{"case_id": "c1", "rule_id": "r1", "variants": [{"variant_id": "v1",
            "scenario_premise": "ситуация", "prompt": "вопрос", "correct_option": {"text": "верно"},
            "distractor_pool": [{"text": "1"}, {"text": "2"}, {"text": "3"}],
            "source_quote": quote}]}]}]}).lessons[0]
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="текст", doc_id="d1",
                      source_revision="rev1", source_start=0, source_end=len(source))
    unchanged, warnings = _bind_rendered_quote_candidates(lesson, [rule], input_corpus)
    assert unchanged == lesson and not warnings


def test_source_occurrences_reject_missing_table_delimiter_even_if_quote_has_one():
    source = "| A |\n| B |"
    chunk = DirectSourceChunk(chunk_id="c1", doc_id="d1", doc_name="s", title="s", headings=(),
                              text=source, source_revision="rev1", chunk_index=0)
    doc = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                               source_revision="rev1", chunks=(chunk,), source_text=source)
    input_corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    assert not find_quote_occurrences_in_corpus("A | B", input_corpus)
    exact = find_quote_occurrences_in_corpus("| A |", input_corpus)
    assert len(exact) == 1 and exact[0].matched_text == "| A |"


def test_source_units_for_review_are_exact_owned_revision_and_deduplicated():
    original = corpus()
    good = RuleEntity(rule_id="r1", section="s", title="t", statement="x", doc_id="d1",
                      source_revision="revision", source_start=0, source_end=15)
    duplicate = RuleEntity(rule_id="r2", section="s", title="t", statement="x", doc_id="d1",
                           source_revision="revision", source_start=0, source_end=15)
    stale = RuleEntity(rule_id="r3", section="s", title="t", statement="x", doc_id="d1",
                       source_revision="wrong", source_start=0, source_end=15)
    invalid = RuleEntity(rule_id="r4", section="s", title="t", statement="x", doc_id="d1",
                         source_revision="revision", source_start=0, source_end=9999)
    fragments = _review_source_unit_fragments([good, duplicate, stale, invalid], original)
    assert len(fragments) == 1
    assert fragments[0].endswith(original.documents[0].source_text[:15])


@pytest.mark.asyncio
async def test_partitioned_extraction_keeps_every_unit_and_replays_without_calls():
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        calls.append(messages)
        if "Правило второе." in messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1]:
            quote = "Правило второе."
        else:
            quote = "Правило первое."
        return {"rules": [{"rule_id": f"r{len(calls)}", "statement": quote, "source_quote": quote}]}

    first, warnings = await extract_partitioned_rule_model(corpus(), journal, "a" * 64, invoke)
    assert len(first.rules) == 2
    assert {rule.source_quote for rule in first.rules} == {"Правило первое.", "Правило второе."}
    assert len(calls) == 2
    second, _ = await extract_partitioned_rule_model(corpus(), journal, "a" * 64, invoke)
    assert second == first
    assert len(calls) == 2
    assert warnings  # Mechanical partitioning is not proof of dependency closure.


@pytest.mark.asyncio
async def test_table_topic_is_derived_from_source_row_on_cached_replay():
    source = "| Категория | Правило |\n| --- | --- |\n| А | Условие А |\n| Б | Условие Б |\n"
    original = corpus()
    doc = original.documents[0]
    document = DirectSourceDocument(doc_id=doc.doc_id, title=doc.title, filename=doc.filename,
                                    category=doc.category, source_revision=doc.source_revision,
                                    chunks=doc.chunks, source_text=source)
    input_corpus = DirectSourceCorpus(tenant_id=original.tenant_id, documents=(document,),
                                       total_chars=len(source), total_chunks=1)
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
        calls.append(target)
        return {"rules": [{"rule_id": f"r{len(calls)}", "statement": target,
                            "source_quote": target, "source_topic": "выдуманная тема"}]}

    model, _ = await extract_partitioned_rule_model(input_corpus, journal, "a" * 64, invoke)
    assert [r.source_topic for r in model.rules] == ["А", "Б"]
    replayed, _ = await extract_partitioned_rule_model(input_corpus, journal, "a" * 64, invoke)
    assert replayed == model and len(calls) == 2


@pytest.mark.asyncio
async def test_source_sections_override_inconsistent_model_labels_without_dropping_rules():
    from app.modules.ai.v3.service import _build_curriculum_groups

    source = "1. Первый раздел\nНорма А.\n\n| Имя | Норма |\n| --- | --- |\n| А | Действие А |\n\n2. Второй раздел\nНорма Б."
    original = corpus()
    doc = original.documents[0]
    doc = DirectSourceDocument(doc_id=doc.doc_id, title=doc.title, filename=doc.filename,
                               category=doc.category, source_revision=doc.source_revision,
                               chunks=doc.chunks, source_text=source)
    input_corpus = DirectSourceCorpus(tenant_id=original.tenant_id, documents=(doc,),
                                      total_chars=len(source), total_chunks=1)
    calls = []

    async def invoke(messages, response_format):
        target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
        calls.append(target)
        return {"rules": [{"rule_id": f"r{len(calls)}", "section": f"название-{len(calls)}",
                            "statement": target, "source_quote": target}]}

    model, _ = await extract_partitioned_rule_model(input_corpus, Journal(), "a" * 64, invoke)
    groups = _build_curriculum_groups(model)
    assert len(model.rules) == 3
    assert [g.section for g in groups] == ["Раздел 1", "Раздел 2"]
    assert [len(g.primary_rules) for g in groups] == [2, 1]
    assert sum(bool(r.source_family) for r in model.rules) == 1


@pytest.mark.asyncio
async def test_missing_canonical_source_text_fails_before_any_model_call():
    old = corpus()
    doc = old.documents[0]
    legacy = DirectSourceDocument(doc_id=doc.doc_id, title=doc.title, filename=doc.filename,
                                  category=doc.category, source_revision=doc.source_revision, chunks=doc.chunks)
    old = DirectSourceCorpus(tenant_id=old.tenant_id, documents=(legacy,), total_chars=old.total_chars, total_chunks=1)
    calls = []

    async def invoke(messages, response_format):
        calls.append(1)
        return {"rules": []}

    with pytest.raises(ValueError, match="source_text_missing"):
        await extract_partitioned_rule_model(old, Journal(), "a" * 64, invoke)
    assert not calls


@pytest.mark.asyncio
async def test_interruption_between_units_restores_completed_unit_only():
    journal = Journal()
    calls = []
    checkpoints = []

    async def invoke(messages, response_format):
        target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
        calls.append(target)
        return {"rules": [{"rule_id": target, "statement": target, "source_quote": target}]}

    async def interrupt():
        checkpoints.append(1)
        if len(checkpoints) == 2:
            raise RuntimeError("interrupted before second request")

    with pytest.raises(RuntimeError, match="interrupted"):
        await extract_partitioned_rule_model(corpus(), journal, "a" * 64, invoke, interrupt)
    assert calls == ["Правило первое."]
    result, _ = await extract_partitioned_rule_model(corpus(), journal, "a" * 64, invoke)
    assert len(result.rules) == 2
    assert calls == ["Правило первое.", "Правило второе."]


@pytest.mark.asyncio
async def test_v3_service_uses_partitioned_checkpoint_and_preserves_review_signal():
    journal = Journal()
    extraction_calls = []
    other_calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            extraction_calls.append(target)
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Проверь каждое фактическое утверждение" in system:
            assert "Правило первое." in messages[1]["content"]
            assert "Правило второе." in messages[1]["content"]
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "yes" else "CONTRADICTED"),
                                  "claims": [{"claim": "x", "status": status, "reason": "source"}],
                                  "summary": "Проверено по источнику."} for item in values]}
        if "независимый контролер" in system:
            other_calls.append("review")
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5,
                    "didactic_score": 5, "summary": "Проверка выполнена.", "defects": []}
        other_calls.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль",
                "content": "Правило первое. Правило второе.", "cases": []}

    first = await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64)
    assert extraction_calls == ["Правило первое.", "Правило второе."]
    assert first.diagnostics["requires_source_review"]
    assert any("связи между фрагментами" in warning for warning in first.content.source_warnings)
    before = list(other_calls)
    assert before
    await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                         extraction_journal=journal, route_fingerprint="a" * 64)
    assert extraction_calls == ["Правило первое.", "Правило второе."]
    assert other_calls == before


@pytest.mark.asyncio
async def test_review_timeout_stops_course_and_does_not_repeat_completed_lesson():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    phases = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            phases.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "независимый контролер" in system:
            phases.append("review")
            raise TimeoutError("unknown outcome")
        phases.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль",
                "content": "Правило первое. Правило второе.", "cases": []}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64)

    with pytest.raises(TimeoutError):
        await generate()
    assert phases == ["extract", "extract", "lesson", "review"]
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    assert phases == ["extract", "extract", "lesson", "review"]

    # Explicit QA continuation can preserve the completed lesson as unreviewed
    # without retrying an unknown review or claiming semantic acceptance.
    partial = await generate_v3_course_from_corpus(
        corpus(), intent=CourseIntent(), generation_client=invoke, extraction_journal=journal,
        route_fingerprint="a" * 64, allow_unreviewed_on_unknown=True,
    )
    assert phases == ["extract", "extract", "lesson", "review"]
    assert partial.diagnostics["requires_source_review"]
    assert "неизвест" in " ".join(partial.diagnostics["violations"]).lower()


@pytest.mark.asyncio
async def test_qa_unknown_review_retains_prior_review_and_never_calls_provider_twice():
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            calls.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "независимый контролер" in system:
            case = "case-a" if "case-a" in messages[1]["content"] else "case-b"
            calls.append(case)
            if case == "case-b":
                raise TimeoutError("unknown")
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": []}
        calls.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": f"case-{key}", "rule_id": f"Правило {word}.", "variants": [{
                    "variant_id": f"v-{key}", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "right"},
                    "source_quote": f"Правило {word}.",
                    "distractor_pool": [{"text": "wrong"}, {"text": "other"}, {"text": "false"}]}]}
                    for key, word in (("a", "первое"), ("b", "второе"))]}

    async def generate(**kwargs):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64, **kwargs)

    with pytest.raises(TimeoutError):
        await generate()
    before = list(calls)
    result = await generate(allow_unreviewed_on_unknown=True)
    assert calls == before
    review = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]
    assert review["verdict"] == "ERROR" and review["parts"][0]["verdict"] == "PASS"
    assert result.diagnostics["requires_source_review"]
    assert "неизвест" in " ".join(result.diagnostics["violations"]).lower()


@pytest.mark.asyncio
async def test_qa_unknown_answer_review_retains_completed_checks_without_retry():
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            calls.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "независимый контролер" in system:
            calls.append("case-review")
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": []}
        if "Проверь каждое фактическое утверждение" in system or "Проверь совместимость описанного" in system:
            calls.append("answer-review")
            if "scenario-b" in messages[1]["content"]:
                raise TimeoutError("unknown answer review")
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "right" else "CONTRADICTED"),
                                "claims": [{"claim": "x", "status": status, "reason": "source"}],
                                "summary": "Проверено по источнику."} for item in values]}
        calls.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": f"case-{key}", "rule_id": f"Правило {word}.", "variants": [{
                    "variant_id": f"v-{key}", "scenario_premise": f"scenario-{key}", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question",
                    "correct_option": {"text": "right"}, "source_quote": f"Правило {word}.",
                    "distractor_pool": [{"text": "wrong"}, {"text": "other"}, {"text": "false"}]}]}
                    for key, word in (("a", "первое"), ("b", "второе"))]}

    async def generate(**kwargs):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64, **kwargs)

    with pytest.raises(TimeoutError):
        await generate()
    before = list(calls)
    result = await generate(allow_unreviewed_on_unknown=True)
    assert calls == before
    review = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]
    assert review["verdict"] == "ERROR" and len(review["parts"]) == 2 and len(review["answer_checks"]) == 1
    assert result.diagnostics["requires_source_review"]


@pytest.mark.asyncio
async def test_qa_unknown_repair_preserves_original_critic_defect_without_retry():
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            calls.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "независимый контролер" in system:
            calls.append("review")
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": [
                        {"scope": "question", "question_id": "case-a", "issue": "неоднозначный вариант"}]}
        if "Исправь только варианты" in system:
            calls.append("repair")
            raise TimeoutError("unknown repair")
        calls.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "case-a", "rule_id": "Правило первое.", "variants": [{
                    "variant_id": "v-a", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "right"},
                    "source_quote": "Правило первое.",
                    "distractor_pool": [{"text": "wrong"}, {"text": "other"}, {"text": "false"}]}]}]}

    async def generate(**kwargs):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64, **kwargs)

    with pytest.raises(TimeoutError):
        await generate()
    before = list(calls)
    result = await generate(allow_unreviewed_on_unknown=True)
    assert calls == before
    review = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]
    assert review["verdict"] == "ERROR" and review["parts"][0]["defects"][0]["issue"] == "неоднозначный вариант"
    assert result.diagnostics["requires_source_review"]


@pytest.mark.asyncio
async def test_qa_unknown_recheck_keeps_repair_history_and_original_defect():
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            calls.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "независимый контролер" in system:
            calls.append("review")
            if "newww" in messages[1]["content"]:
                raise TimeoutError("unknown recheck")
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": [
                        {"scope": "question", "question_id": "case-a", "issue": "неоднозначный вариант"}]}
        if "Исправь только варианты" in system:
            calls.append("repair")
            return {"repairs": [{"variant_id": "v-a", "correct": "right", "explanation": "объяснение",
                    "distractors": [{"text": value, "category": "procedural_confusion"}
                                    for value in ("newww", "other", "false")]}]}
        calls.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "case-a", "rule_id": "Правило первое.", "variants": [{
                    "variant_id": "v-a", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "right"},
                    "source_quote": "Правило первое.",
                    "distractor_pool": [{"text": "wrong"}, {"text": "other"}, {"text": "false"}]}]}]}

    async def generate(**kwargs):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64, **kwargs)

    with pytest.raises(TimeoutError):
        await generate()
    before = list(calls)
    result = await generate(allow_unreviewed_on_unknown=True)
    assert calls == before
    report = result.diagnostics["validation_report"]
    assert report["semantic_reviews"]["l1"]["verdict"] == "ERROR"
    assert report["semantic_repairs"][0]["original_review"]["defects"][0]["issue"] == "неоднозначный вариант"
    assert report["semantic_repairs"][0]["recheck"] is None
    assert result.diagnostics["requires_source_review"]


@pytest.mark.asyncio
async def test_qa_mode_still_stops_when_lesson_generation_outcome_is_unknown():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        if "Карту регламента" in messages[0]["content"]:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            calls.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        calls.append("lesson")
        raise TimeoutError("unknown lesson")

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint="a" * 64, allow_unreviewed_on_unknown=True)

    with pytest.raises(TimeoutError):
        await generate()
    before = list(calls)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    assert calls == before


@pytest.mark.asyncio
async def test_case_reviews_keep_all_defects_and_replay_without_provider_calls():
    journal = Journal()
    reviews = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Проверь каждое фактическое утверждение" in system:
            assert "Правило первое." in messages[1]["content"]
            assert "Правило второе." in messages[1]["content"]
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "yes" else "CONTRADICTED"),
                                  "claims": [{"claim": "x", "status": status, "reason": "source"}],
                                  "summary": "Проверено по источнику."} for item in values]}
        if "независимый контролер" in system:
            text = messages[1]["content"]
            marker = "case-a" if "case-a" in text else "case-b"
            reviews.append(marker)
            return {"verdict": "NEEDS_REVISION", "factual_score": 4, "alignment_score": 4,
                    "didactic_score": 3, "summary": "Выявлены существенные замечания.",
                    "defects": [{"issue": f"defect-{marker}"}]}
        variants = [{"variant_id": "v", "explanation": "Источник подтверждает правильный ответ.", "prompt": "?", "correct_option": {"text": "yes"},
                     "distractor_pool": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}]
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "case-a", "rule_id": "Правило первое.", "variants": variants},
                          {"case_id": "case-b", "rule_id": "Правило второе.", "variants": variants}]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64)

    first = await generate()
    violations = " ".join(first.diagnostics["violations"])
    assert "defect-case-a" in violations and "defect-case-b" in violations
    assert reviews == ["case-a", "case-b"]
    await generate()
    assert reviews == ["case-a", "case-b"]


@pytest.mark.asyncio
async def test_answer_contradiction_cannot_be_hidden_by_passing_case_review():
    journal = Journal()
    checks = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Проверь каждое фактическое утверждение" in system:
            contradicted = "bad-answer" in messages[1]["content"]
            checks.append("bad" if contradicted else "good")
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "good-answer" else "CONTRADICTED"),
                                  "claims": [{"claim": "claim", "status": status, "reason": "source"}],
                                  "summary": "Проверено по источнику."} for item in values]}
        if "независимый контролер" in system:
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": []}
        variants = [
            {"variant_id": name, "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": answer},
             "distractor_pool": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}
            for name, answer in (("good", "good-answer"), ("bad", "bad-answer"))
        ]
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "c", "rule_id": "Правило первое.", "variants": variants}]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64)

    result = await generate()
    assert "ожидался SUPPORTED, получен CONTRADICTED" in " ".join(result.diagnostics["violations"])
    assert result.diagnostics["requires_source_review"]
    assert checks == ["good", "bad"]
    await generate()
    assert checks == ["good", "bad"]


@pytest.mark.asyncio
async def test_unlinked_answer_cannot_borrow_unrelated_source_unit():
    answer_calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Проверь каждое фактическое утверждение" in system:
            answer_calls.append(1)
            raise AssertionError("unrelated source must not be sent as proof")
        if "независимый контролер" in system:
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": []}
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "c", "rule_id": "missing-rule", "variants": [
                    {"variant_id": "v", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "answer"},
                     "distractor_pool": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}]}]}

    result = await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                  extraction_journal=Journal(), route_fingerprint="a" * 64)
    assert not answer_calls
    assert "нет однозначного исходного блока" in " ".join(result.diagnostics["violations"])
    assert any("вне основных правил" in item for item in result.content.source_warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("omissions", [[], ["обязательное действие"]])
async def test_worker_repairs_shortcuts_then_reviews_all_options_and_replays(overlap, omissions):
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            calls.append("extract")
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Для каждого вопроса замени только три неверных варианта" in system:
            calls.append("repair")
            return {"repairs": [{"variant_id": v,
                                 "distractors": [{"text": x, "category": "procedural_confusion"}
                                                 for x in ("ложно", "неверно подробно очень", "ошибочно и неправильно")]}
                                for v in ("v1", "v2")]}
        if "Проверь каждое фактическое утверждение" in system:
            calls.append("options")
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "очень длинный ответ" else "CONTRADICTED"),
                                  "claims": [{"claim": "x", "status": status, "reason": "source"}],
                                  "summary": "Проверено по источнику."} for item in values]}
        if "Проверь совместимость описанного" in system:
            calls.append("compatibility")
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "очень длинный ответ" else ("UNCERTAIN" if overlap and item["text"] == "ложно" else "CONTRADICTED")),
                                  "claims": [{"claim": "x", "status": status, "reason": "source"}],
                                  "summary": "Проверено по источнику."} for item in values]}
        if "Сравни каждый ответ с источником и вопросом" in system:
            calls.append("completeness")
            payload = json.loads(messages[1]["content"])
            assert payload["answers"] == ["очень длинный ответ"]
            assert "is_correct" not in messages[1]["content"]
            return {"answers": [{"index": 0, "omissions": omissions}], "explanation_review": {"verdict": "SUPPORTED", "claims": [{"claim": "Fact", "status": "SUPPORTED", "reason": "Source"}], "summary": "Checked"}}
        if "независимый контролер" in system:
            calls.append("review")
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": []}
        calls.append("lesson")
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": f"c{i}", "rule_id": f"Правило {word}.", "variants": [
                    {"variant_id": f"v{i}", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "очень длинный ответ"},
                     "source_quote": f"Правило {word}.",
                     "distractor_pool": [{"text": "а"}, {"text": "б"}, {"text": "в"}]}]}
                    for i, word in ((1, "первое"), (2, "второе"))]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64)

    result = await generate()
    assert calls.count("repair") == 1 and calls.count("review") == 2 and calls.count("options") == 2
    assert calls.count("compatibility") == 2
    # Legacy completeness requests still share their original identity.
    assert calls.count("completeness") == (0 if overlap else 1)
    assert any("отредактированы" in item for item in result.content.source_warnings)
    assert result.diagnostics["requires_source_review"]
    assert ("проверка совместимости" in " ".join(result.diagnostics["violations"])) is overlap
    assert ("проверка полноты" in " ".join(result.diagnostics["violations"])) is (bool(omissions) and not overlap)
    before = list(calls)
    await generate()
    assert calls == before


@pytest.mark.asyncio
@pytest.mark.parametrize("recheck_passes", [False, True])
async def test_targeted_review_repair_rechecks_case_and_answers_then_replays(recheck_passes):
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system = messages[0]["content"]
        if "Фактические утверждения текста урока" in messages[1]["content"]:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "Текст урока", "status": "SUPPORTED", "reason": "Источник"}],
                    "summary": "Текст проверен по источнику."}
        if "Карту регламента" in system:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": target, "section": "Общий раздел", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Исправь только варианты" in system:
            calls.append("repair")
            return {"repairs": [{"variant_id": "v1", "correct": "right", "explanation": "объяснение",
                    "distractors": [{"text": text, "category": "procedural_confusion"}
                                    for text in ("newww", "false", "other")]}]}
        if "независимый контролер" in system:
            calls.append("review")
            repaired = "newww" in messages[1]["content"]
            defects = [] if repaired and recheck_passes else [
                {"scope": "question", "question_id": "case-a", "issue": "неоднозначный вариант"}]
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Проверка выполнена.", "defects": defects}
        if "Сравни каждый ответ с источником" in system:
            return {"answers": [{"index": 0, "omissions": []}], "explanation_review": {"verdict": "SUPPORTED", "claims": [{"claim": "Fact", "status": "SUPPORTED", "reason": "Source"}], "summary": "Checked"}}
        if "Проверь каждое фактическое утверждение" in system or "Проверь совместимость описанного" in system:
            calls.append("answer")
            values = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
            return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "right" else "CONTRADICTED"),
                                "claims": [{"claim": "x", "status": status, "reason": "source"}],
                                "summary": "Проверено по источнику."} for item in values]}
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "case-a", "rule_id": "Правило первое.", "variants": [
                    {"variant_id": "v1", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "right"},
                     "source_quote": "Правило первое.",
                     "distractor_pool": [{"text": "wrong"}, {"text": "false"}, {"text": "other"}]}]}]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint="a" * 64)

    result = await generate()
    assert calls.count("repair") == 1 and calls.count("review") == 2 and calls.count("answer") == 2
    repairs = result.diagnostics["validation_report"]["semantic_repairs"]
    assert len(repairs) == 1 and repairs[0]["original_review"]["defects"]
    assert repairs[0].get("accepted", False) is recheck_passes
    assert bool(repairs[0]["recheck"]["defects"]) is not recheck_passes
    assert ("Противоречивый ответ" in " ".join(result.diagnostics["violations"])) is not recheck_passes
    before = list(calls)
    await generate()
    assert calls == before


@pytest.mark.asyncio
async def test_empty_extraction_cannot_produce_a_silent_empty_course():
    async def invoke(messages, response_format):
        return {"rules": []}

    with pytest.raises(ValueError, match="no_rules"):
        await extract_partitioned_rule_model(corpus(), Journal(), "a" * 64, invoke)


@pytest.mark.asyncio
@pytest.mark.parametrize("recheck_passes", [False, True])
@pytest.mark.parametrize("critic_rejects", [False, True])
async def test_uncertain_distractor_repair_is_scoped_rechecked_and_replayed(recheck_passes, critic_rejects):
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system, user = messages[0]["content"], messages[1]["content"]
        if "Фактические утверждения текста урока" in user:
            return {"verdict": "SUPPORTED", "claims": [{"claim": "x", "status": "SUPPORTED", "reason": "source"}],
                    "summary": "checked"}
        if "Карту регламента" in system:
            target = user.split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": target, "section": "s", "title": target,
                               "statement": target, "source_quote": target}]}
        if "Замени только указанные неверные варианты" in system:
            calls.append("repair")
            request = json.loads(user)
            assert len(request["feedback"]) == 1
            return {"repairs": [{"index": request["feedback"][0]["index"], "replacement": "badbad"}]}
        if "независимый контролер" in system:
            if critic_rejects and "badbad" in user:
                return {"verdict": "NEEDS_REVISION", "factual_score": 5, "alignment_score": 5,
                        "didactic_score": 3, "summary": "Repeated distractor meaning.",
                        "defects": [{"scope": "question", "question_id": "v1", "issue": "duplicate mistake"}]}
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                    "summary": "Source evidence checked.", "defects": []}
        if "Проверь каждое фактическое утверждение" in system or "Проверь совместимость описанного" in system:
            values = json.loads(user.split("ВАРИАНТЫ:\n", 1)[1])
            result = []
            for item in values:
                status = ("SUPPORTED" if item["text"] == "right!" else
                          "UNCERTAIN" if item["text"] == "unclear" or (item["text"] == "badbad" and not recheck_passes)
                          else "CONTRADICTED")
                result.append({"index": item["index"], "verdict": status, "omitted_required_elements": [],
                               "claims": [{"claim": "x", "status": status, "reason": "source"}], "summary": "checked"})
            return {"options": result}
        if "Сравни каждый ответ с источником и вопросом" in system:
            return {"answers": [{"index": 0, "omissions": []}], "explanation_review": {"verdict": "SUPPORTED", "claims": [{"claim": "Fact", "status": "SUPPORTED", "reason": "Source"}], "summary": "Checked"}}
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": "Текст",
                "cases": [{"case_id": "case-a", "rule_id": "Правило первое.", "variants": [
                    {"variant_id": "v1", "explanation": "Источник подтверждает правильный ответ.", "prompt": "question", "correct_option": {"text": "right!"},
                     "source_quote": "Правило первое.",
                     "distractor_pool": [{"text": "unclear"}, {"text": "false!"}, {"text": "other!"}]}]}]}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint="9" * 64)

    result = await generate()
    checks = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]["answer_checks"]
    attempt = checks[0]["distractor_repair"]
    assert attempt["original_review"] and attempt["case_recheck"]
    assert (attempt["recheck"] is None) is critic_rejects
    assert attempt.get("accepted", False) is (recheck_passes and not critic_rejects)
    rendered = {option.text for assessment in result.assessment.assessments
                for question in assessment.mcq for option in question.options}
    assert ("badbad" in rendered) is (recheck_passes and not critic_rejects)
    assert ("unclear" in rendered) is not (recheck_passes and not critic_rejects)
    assert len(calls) == 1
    await generate()
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("finish_reason", "reasoning_only"), [("length", False), ("stop", True)])
async def test_incomplete_or_reasoning_only_provider_output_is_not_checkpointed(finish_reason, reasoning_only):
    from app.modules.ai.llm_client import _LLMResponse

    class Client:
        async def ainvoke(self, messages, response_format):
            return _LLMResponse('{"rules": []}', finish_reason=finish_reason, content_is_reasoning=reasoning_only)

    journal = Journal()
    with pytest.raises(ValueError, match="v3_provider_incomplete_response"):
        await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=Client(),
                                             extraction_journal=journal, route_fingerprint="a" * 64)
    assert not any(key.startswith("v3-result:") for key in journal.values)


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "finish", "reasoning_only"), [
    ({"content": '{"rules": []}'}, "length", False),
    ({"content": "", "reasoning": '{"rules": []}'}, "stop", True),
])
async def test_transport_preserves_finish_reason_and_reasoning_only_flag(message, finish, reasoning_only):
    from app.modules.ai.llm_client import LLMClient, LLMProviderConfig

    client = LLMClient(LLMProviderConfig(name="test", base_url="https://example.invalid",
                                         api_key="test", model="test"))

    async def request(payload):
        return {"choices": [{"message": message, "finish_reason": finish}]}

    client._request = request
    response = await client.ainvoke("test")
    assert response.finish_reason == finish
    assert response.content_is_reasoning is reasoning_only

@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', ['SUPPORTED', 'UNCERTAIN', 'CONTRADICTED'])
async def test_lesson_claim_review_is_checkpointed_and_holds_unsupported_prose(verdict):
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5,
                    'didactic_score': 5, 'summary': 'Проверка выполнена.', 'defects': []}
        if 'Фактические утверждения текста урока' in user:
            calls.append('claim_review')
            assert 'Правило первое.' in user and 'Правило второе.' in user
            return {'verdict': verdict, 'claims': [{'claim': 'Ограничение', 'status': verdict,
                    'reason': 'Проверено по источнику.'}], 'summary': 'Текст проверен по источнику.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль',
                'content': 'Правило первое. Правило второе.', 'cases': []}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint='a' * 64)

    result = await generate()
    violations = result.diagnostics.get('violations', [])
    assert any('проверка текста' in item for item in violations) is (verdict != 'SUPPORTED')
    assert calls == ['claim_review']
    await generate()
    assert calls == ['claim_review']

@pytest.mark.asyncio
async def test_lesson_claim_review_preserves_trusted_reference_as_nonquote_context():
    messages_seen = []

    async def invoke(messages, response_format):
        messages_seen.extend(messages)
        return {'verdict': 'SUPPORTED', 'claims': [{'claim': 'факт', 'status': 'SUPPORTED', 'reason': 'текст'}],
                'summary': 'Проверено по источнику.'}

    from app.modules.ai.v3.engine import V3GenerationPipeline
    await V3GenerationPipeline(invoke).review_answer('', 'Фактические утверждения текста урока', 'факт',
                                                      ['исходный текст'], ('подтверждённая отсылка',))
    text = messages_seen[1]['content']
    assert 'УТОЧНЕНИЯ ССЫЛОК, НЕ ЦИТАТЫ ИСТОЧНИКА' in text
    assert 'подтверждённая отсылка' in text

@pytest.mark.asyncio
async def test_unknown_lesson_claim_review_is_not_retried_and_keeps_prior_review():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    claim_calls = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5,
                    'didactic_score': 5, 'summary': 'Проверка выполнена.', 'defects': []}
        if 'Фактические утверждения текста урока' in user:
            claim_calls.append(1)
            raise TimeoutError('unknown outcome')
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль',
                'content': 'Правило первое. Правило второе.', 'cases': []}

    async def generate(allow_unreviewed=False):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint='a' * 64, allow_unreviewed_on_unknown=allow_unreviewed)

    with pytest.raises(TimeoutError):
        await generate()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    partial = await generate(True)
    review = partial.diagnostics['validation_report']['semantic_reviews']['l1']
    assert review['verdict'] == 'ERROR' and review['parts'][0]['verdict'] == 'PASS'
    assert partial.diagnostics['requires_source_review']
    assert claim_calls == [1]

@pytest.mark.parametrize('text', [
    '# Общий заголовок\n\n## Первый\nПервый факт.\n\n## Второй\nВторой факт.',
    'Вступление.\n\n## Первый\nФакт.\n\n## Второй\nЕщё факт.',
    '# Курс\n```text\n## Это не заголовок раздела\n```\n\n## Раздел\nФакт.',
    'Текст без заголовков.\n\nВторой абзац без заголовка.',
])
def test_lesson_claim_sections_are_lossless_and_keep_title_with_first_section(text):
    from app.modules.ai.v3.service import _lesson_claim_sections
    parts = _lesson_claim_sections(text)
    assert ''.join(parts) == text
    assert all(part.strip() for part in parts)
    if text.startswith('# Общий заголовок'):
        assert len(parts) == 2 and '## Первый' in parts[0] and '## Второй' in parts[1]
    if '```text' in text:
        assert len(parts) == 2 and '## Это не заголовок раздела' in parts[0]


@pytest.mark.asyncio
async def test_each_lesson_section_is_checked_once_and_a_later_uncertainty_holds_course():
    journal = Journal()
    seen = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5,
                    'didactic_score': 5, 'summary': 'Проверка выполнена.', 'defects': []}
        if 'Фактические утверждения текста урока' in user:
            seen.append(user)
            status = 'UNCERTAIN' if 'Второй факт' in user else 'SUPPORTED'
            return {'verdict': status, 'claims': [{'claim': 'Факт', 'status': status,
                    'reason': 'Проверено по источнику.'}], 'summary': 'Сверено с источником.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль',
                'content': '# Урок\n\n## Первый\nПервый факт.\n\n## Второй\nВторой факт.', 'cases': []}

    async def generate():
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                    extraction_journal=journal, route_fingerprint='a' * 64)

    result = await generate()
    review = result.diagnostics['validation_report']['semantic_reviews']['l1']
    assert len(seen) == 2 and len(review['lesson_claim_reviews']) == 2
    assert any('UNCERTAIN (часть 2)' in item for item in result.diagnostics['violations'])
    assert any('зависимости между частями' in item for item in result.content.source_warnings)
    await generate()
    assert len(seen) == 2

@pytest.mark.asyncio
async def test_unknown_second_lesson_section_keeps_first_result_without_repeating_either():
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    journal = Journal()
    seen = []

    async def invoke(messages, response_format):
        system, user = messages[0]['content'], messages[1]['content']
        if 'Карту регламента' in system:
            target = user.split('ЦЕЛЕВОЙ ФРАГМЕНТ:', 1)[1].strip()
            return {'rules': [{'rule_id': target, 'section': 'Общий раздел', 'title': target,
                               'statement': target, 'source_quote': target}]}
        if 'независимый контролер' in system:
            return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5,
                    'didactic_score': 5, 'summary': 'Проверка выполнена.', 'defects': []}
        if 'Фактические утверждения текста урока' in user:
            seen.append(user)
            if 'Второй факт' in user:
                raise TimeoutError('unknown outcome')
            return {'verdict': 'SUPPORTED', 'claims': [{'claim': 'Факт', 'status': 'SUPPORTED',
                    'reason': 'Источник.'}], 'summary': 'Сверено с источником.'}
        return {'lesson_id': 'l1', 'title': 'Урок', 'module_title': 'Модуль',
                'content': '# Урок\n\n## Первый\nПервый факт.\n\n## Второй\nВторой факт.', 'cases': []}

    async def generate(allow_unreviewed=False):
        return await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint='a' * 64, allow_unreviewed_on_unknown=allow_unreviewed)

    with pytest.raises(TimeoutError):
        await generate()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate()
    partial = await generate(True)
    review = partial.diagnostics['validation_report']['semantic_reviews']['l1']
    assert review['verdict'] == 'ERROR'
    assert len(review['lesson_claim_reviews']) == 1
    assert review['lesson_claim_reviews'][0]['review']['verdict'] == 'SUPPORTED'
    assert partial.diagnostics['requires_source_review'] and len(seen) == 2
