"""V3 prompts must use the actual source instead of a specific customer's rules."""

import json

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import RuleEntity, V3Course, V3Lesson, V3Question, V3ScenarioCase
from app.modules.ai.v3.prompts import LESSON_COGEN_SYSTEM_PROMPT
from app.modules.ai.v3.service import (
    _extract_corpus_text,
    _find_quote_in_corpus,
    _semantic_review_parts,
    _unassessed_primary_rule_ids,
    _validate_answer_entailment,
    _validate_question_entailment,
    _verify_rule_quote_grounding,
)


def test_lesson_prompt_requests_four_real_options_without_forced_extra_variant():
    example = json.loads(LESSON_COGEN_SYSTEM_PROMPT.split("ВЫВОД ТОЛЬКО В ФОРМАТЕ JSON:\n", 1)[1])
    variants = example["cases"][0]["variants"]
    assert len(variants) == 1
    assert len(variants[0]["distractor_pool"]) == 3
    assert "rule_id только из основных правил" in LESSON_COGEN_SYSTEM_PROMPT.lower()
    assert "один кейс может проверять несколько связанных правил" in LESSON_COGEN_SYSTEM_PROMPT.lower()
    assert "когда они действительно соответствуют разным условиям источника" in LESSON_COGEN_SYSTEM_PROMPT.lower()
    assert "не запрещают действия за их пределами" in LESSON_COGEN_SYSTEM_PROMPT.lower()
    assert "не склеивай разрозненные фрагменты" in LESSON_COGEN_SYSTEM_PROMPT.lower()


@pytest.mark.asyncio
async def test_review_uses_all_case_variants_without_duplicate_assembled_questions():
    seen = []

    async def invoke(messages, response_format):
        seen.extend(messages)
        return {"verdict": "NEEDS_REVISION"}

    case = {"case_id": "c1", "rule_id": "r1", "variants": [
        {"variant_id": "v1", "prompt": "variant-one", "correct_option": {"text": "yes"}},
        {"variant_id": "v2", "prompt": "variant-two", "correct_option": {"text": "yes"}},
    ]}
    course = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
                                 "lessons": [{"lesson_id": "l", "cases": [case],
                                              "questions": [{"question_id": "duplicate", "prompt": "redundant"}]}]})
    await V3GenerationPipeline(invoke).review_lesson(course.lessons[0], [])
    prompt = seen[1]["content"]
    assert "variant-one" in prompt and "variant-two" in prompt
    assert "redundant" not in prompt

    seen.clear()
    await V3GenerationPipeline(invoke).review_lesson(course.lessons[0], [], partial_case=True)
    assert "не делай вывод о недостатке общего покрытия" in seen[0]["content"]

    seen.clear()
    legacy = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
                                 "lessons": [{"lesson_id": "l", "cases": [],
                                              "questions": [{"question_id": "q", "prompt": "legacy-question"}]}]})
    await V3GenerationPipeline(invoke).review_lesson(legacy.lessons[0], [])
    assert "legacy-question" in seen[1]["content"]


@pytest.mark.asyncio
async def test_option_semantic_check_sends_all_options_without_answer_key():
    seen = []

    async def invoke(messages, response_format):
        seen.extend(messages)
        return {"options": []}

    await V3GenerationPipeline(invoke).review_question_options("scenario", "question", ["A", "B", "C", "D"], ["source"])
    payload = json.loads(seen[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
    assert payload == [{"index": i, "text": text} for i, text in enumerate(("A", "B", "C", "D"))]
    assert all("is_correct" not in item for item in payload)


@pytest.mark.asyncio
async def test_lesson_claim_review_distinguishes_objectives_without_weakening_answer_review():
    seen = []

    async def invoke(messages, response_format):
        seen.append(messages[0]["content"])
        return {"verdict": "SUPPORTED", "claims": [{"claim": "x", "status": "SUPPORTED", "reason": "source"}],
                "summary": "checked"}

    pipeline = V3GenerationPipeline(invoke)
    await pipeline.review_answer("scenario", "question", "answer", ["source"])
    await pipeline.review_answer("scenario", "question", "answer", ["source"], lesson_claims=True)
    assert "формулировка учебной цели" not in seen[0]
    assert "формулировка учебной цели" in seen[1]
    assert "все фактические нормы" in seen[1]


def test_objective_prompt_is_limited_to_explicitly_labelled_sections():
    from app.modules.ai.v3.service import _lesson_objective_section

    assert _lesson_objective_section("## Цель урока\nНаучиться применять правило")
    assert _lesson_objective_section("### Учебные цели\nРазобрать условия")
    assert not _lesson_objective_section("## Порядок работы\nЦель — соблюсти срок")


def test_review_parts_preserve_each_case_variant_and_complete_lesson():
    cases = [
        {"case_id": "c1", "rule_id": "r1", "variants": [
            {"variant_id": "v1", "prompt": "a", "correct_option": {"text": "x"}},
            {"variant_id": "v2", "prompt": "b", "correct_option": {"text": "x"}},
        ]},
        {"case_id": "c2", "rule_id": "r2", "variants": [
            {"variant_id": "v3", "prompt": "c", "correct_option": {"text": "x"}},
        ]},
    ]
    course = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
                                 "lessons": [{"lesson_id": "l", "content": "all conditions", "cases": cases}]})
    parts = _semantic_review_parts(course.lessons[0])
    assert len(parts) == 2
    assert all(part.content == "all conditions" for part in parts)
    assert [v.variant_id for p in parts for c in p.cases for v in c.variants] == ["v1", "v2", "v3"]

    legacy = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
                                 "lessons": [{"lesson_id": "l", "questions": [
                                     {"question_id": "q1"}, {"question_id": "q2"}]}]})
    assert [p.questions[0].question_id for p in _semantic_review_parts(legacy.lessons[0])] == ["q1", "q2"]


@pytest.mark.parametrize(("verdict", "claim_status", "expected"), [
    ("SUPPORTED", "SUPPORTED", True),
    ("CONTRADICTED", "CONTRADICTED", True),
    ("UNCERTAIN", "UNCERTAIN", True),
    ("SUPPORTED", "CONTRADICTED", False),
    ("SUPPORTED", "UNCERTAIN", False),
    ("UNCERTAIN", "CONTRADICTED", False),
    ("CONTRADICTED", "SUPPORTED", False),
])
def test_answer_verdict_must_agree_with_each_claim(verdict, claim_status, expected):
    value = {"verdict": verdict, "claims": [{"claim": "x", "status": claim_status, "reason": "why"}],
             "summary": "explanation"}
    assert _validate_answer_entailment(value)[0] is expected


@pytest.mark.parametrize(("wrong_status", "expected"), [("CONTRADICTED", True), ("SUPPORTED", False), ("UNCERTAIN", False)])
def test_question_check_rejects_plausible_or_unknown_wrong_answers(wrong_status, expected):
    statuses = ["SUPPORTED", wrong_status, "CONTRADICTED", "CONTRADICTED"]
    value = {"options": [{"index": i, "verdict": status,
                          "omitted_required_elements": [],
                          "claims": [{"claim": "x", "status": status, "reason": "source"}], "summary": "checked"}
                         for i, status in enumerate(statuses)]}
    assert _validate_question_entailment(value, [True, False, False, False])[0] is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "statement"),
    [
        ("Пожарная безопасность", "При пожаре немедленно сообщите по номеру 112."),
        ("Контроль температуры", "При превышении 8 °C изолируйте продукцию."),
    ],
)
async def test_lesson_prompt_follows_passed_rules_without_foreign_business_assumptions(title, statement):
    seen = []

    async def invoke(messages, response_format):
        seen.extend(messages)
        return {"lesson_id": "lesson-1", "title": title, "content": statement, "cases": []}

    rule = RuleEntity(rule_id="r1", section=title, title=title, statement=statement)
    await V3GenerationPipeline(invoke).generate_lesson_with_scenarios(title, title, [rule])

    system = seen[0]["content"].lower()
    assert statement in seen[1]["content"]
    for foreign_term in ("ломбард", "залогов", "микрокредит", "ауп рд", "павлодар", "группа 1"):
        assert foreign_term not in system


@pytest.mark.asyncio
async def test_neighbor_rules_are_explicit_context_not_primary_assignment():
    seen = []

    async def invoke(messages, response_format):
        seen.extend(messages)
        return {"lesson_id": "l", "title": "t", "content": "text", "cases": []}

    primary = RuleEntity(rule_id="threshold", section="s", title="threshold", statement="Порог задан таблицей.")
    context = RuleEntity(rule_id="approval", section="s", title="approval", statement="Обе категории требуют согласования.")
    await V3GenerationPipeline(invoke).generate_lesson_with_scenarios("Модуль", "Пороги", [primary], neighbor_rules=[context])
    user = seen[1]["content"]
    assert "СОСЕДНИЙ КОНТЕКСТ ТОГО ЖЕ РАЗДЕЛА" in user
    assert "Обе категории требуют согласования" in user
    assert user.index("Порог задан таблицей") < user.index("СОСЕДНИЙ КОНТЕКСТ")


def test_claimed_rules_without_assessment_remain_visible():
    rules = [
        RuleEntity(rule_id="r1", section="s", title="a", statement="a"),
        RuleEntity(rule_id="r2", section="s", title="b", statement="b"),
    ]
    lesson = V3Lesson(
        lesson_id="l1", title="t", module_title="m", content="текст",
        covered_rule_ids=("r1", "r2"),
        cases=(V3ScenarioCase(case_id="c1", rule_id="r1", learning_objective="x", variants=()),),
        questions=(),
    )
    # Merely assigning a rule to the lesson or to an empty case is not assessment.
    assert _unassessed_primary_rule_ids(lesson, rules) == ["r1", "r2"]


def test_direct_question_link_suppresses_only_its_own_missing_link():
    rules = [
        RuleEntity(rule_id="r1", section="s", title="a", statement="a"),
        RuleEntity(rule_id="r2", section="s", title="b", statement="b"),
    ]
    question = V3Question(question_id="q1", scenario_premise="x", prompt="?", options=(),
                          explanation="", rule_id="r1", source_quote="")
    lesson = V3Lesson(lesson_id="l1", title="t", module_title="m", content="x",
                      covered_rule_ids=("r1", "r2"), questions=(question,))
    assert _unassessed_primary_rule_ids(lesson, rules) == ["r2"]


def test_coverage_review_signal_survives_adapter_without_becoming_a_failure():
    signal = "Нет прямой связи с правилом r2; проверить связанные вопросы"
    course = V3Course(course_id="c1", title="Курс", document_sha256="a" * 64,
                      lessons=(), quality_verdict="needs_review",
                      validation_report={"verdict": "PASS", "coverage_review_signals": [signal]})
    artifacts = v3_course_to_generation_artifacts(course)
    assert signal in artifacts.content.source_warnings
    assert artifacts.diagnostics["validation_report"]["verdict"] == "PASS"


def test_v3_uses_canonical_source_instead_of_joining_overlapping_chunks():
    repeated = "Первое условие. Повтор. Повтор. Последнее условие."
    common = {"doc_id": "d1", "doc_name": "source", "title": "source", "headings": (),
              "source_revision": "revision"}
    chunks = (
        DirectSourceChunk(chunk_id="c0", text="Первое условие. Повтор. Повтор.", chunk_index=0, **common),
        DirectSourceChunk(chunk_id="c1", text="Повтор. Повтор. Последнее условие.", chunk_index=1, **common),
    )
    document = DirectSourceDocument(doc_id="d1", title="source", filename="source", category="general",
                                    source_revision="revision", chunks=chunks, source_text=repeated)
    corpus = DirectSourceCorpus(tenant_id="t1", documents=(document,), total_chars=len(repeated), total_chunks=2)
    assert _extract_corpus_text(corpus)[0] == repeated


def test_format_only_candidate_does_not_automatically_verify_quote():
    source = "Не выдавать<br>без **согласования**."
    chunk = DirectSourceChunk(chunk_id="c0", doc_id="d1", doc_name="s", title="s", headings=(),
                              text=source, source_revision="revision", chunk_index=0)
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="revision", chunks=(chunk,), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="t1", documents=(document,), total_chars=len(source), total_chunks=1)
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="Не выдавать без согласования",
                      source_quote="Не выдавать без согласования.", doc_id="d1", source_revision="revision")
    verified, message, _ = _verify_rule_quote_grounding(rule, corpus)
    assert not verified
    assert "формат" in message.lower()
    assert "d1" in message


@pytest.mark.parametrize("chunk_revision", ["revision", "other-revision", ""])
def test_quote_spanning_chunks_uses_document_offsets_without_bypassing_revisions(chunk_revision):
    source = "Перед выдачей проверьте состояние оборудования."
    common = {"doc_id": "d1", "doc_name": "s", "title": "s", "headings": (),
              "source_revision": chunk_revision}
    chunks = (
        DirectSourceChunk(chunk_id="c0", text=source[:28], chunk_index=0, **common),
        DirectSourceChunk(chunk_id="c1", text=source[20:], chunk_index=1, **common),
    )
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="revision", chunks=chunks, source_text=source)
    corpus = DirectSourceCorpus(tenant_id="t1", documents=(document,), total_chars=len(source), total_chunks=2)
    quote = "проверьте состояние оборудования"
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement=quote,
                      source_quote=quote, doc_id="d1", source_revision="revision")
    verified, message, occurrences = _verify_rule_quote_grounding(rule, corpus)
    if chunk_revision == "revision":
        assert verified
        assert len(occurrences) == 1
        occurrence = occurrences[0]
        assert occurrence.scope == "document"
        assert source[occurrence.char_start:occurrence.char_end] == quote
        assert "Чанк" not in message
        assert _find_quote_in_corpus(quote, corpus)[2] is None
    else:
        assert not verified


def test_document_offset_match_does_not_resolve_identical_quotes_across_documents():
    source = "Перед выдачей проверьте состояние оборудования."
    docs = []
    for doc_id in ("d1", "d2"):
        common = {"doc_id": doc_id, "doc_name": "s", "title": "s", "headings": (),
                  "source_revision": "revision"}
        chunks = (
            DirectSourceChunk(chunk_id=f"{doc_id}-c0", text=source[:28], chunk_index=0, **common),
            DirectSourceChunk(chunk_id=f"{doc_id}-c1", text=source[20:], chunk_index=1, **common),
        )
        docs.append(DirectSourceDocument(doc_id=doc_id, title="s", filename="s", category="general",
                                         source_revision="revision", chunks=chunks, source_text=source))
    corpus = DirectSourceCorpus(tenant_id="t1", documents=tuple(docs), total_chars=2 * len(source), total_chunks=4)
    quote = "проверьте состояние оборудования"
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement=quote,
                      source_quote=quote, source_revision="revision")
    verified, message, occurrences = _verify_rule_quote_grounding(rule, corpus)
    assert not verified
    assert "Неоднозначная" in message
    assert {item.doc_id for item in occurrences} == {"d1", "d2"}


def test_document_fallback_does_not_join_table_cells_into_a_fabricated_quote():
    source = "| Группа А | не выдавать |"
    chunks = (
        DirectSourceChunk(chunk_id="c0", doc_id="d1", doc_name="s", title="s", headings=(),
                          text=source[:13], source_revision="revision", chunk_index=0),
        DirectSourceChunk(chunk_id="c1", doc_id="d1", doc_name="s", title="s", headings=(),
                          text=source[13:], source_revision="revision", chunk_index=1),
    )
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="revision", chunks=chunks, source_text=source)
    corpus = DirectSourceCorpus(tenant_id="t1", documents=(document,), total_chars=len(source), total_chunks=2)
    rule = RuleEntity(rule_id="r1", section="s", title="t", statement="Группа А не выдавать",
                      source_quote="Группа А не выдавать", doc_id="d1", source_revision="revision")
    verified, _, _ = _verify_rule_quote_grounding(rule, corpus)
    assert not verified
