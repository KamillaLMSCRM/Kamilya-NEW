from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
)
from app.modules.ai.evidence_engine.application import (
    _escape_markdown_text,
    _narrative_fact_metadata,
    _split_narrative_chunk,
    build_evidence_source,
    generate_evidence_course,
    to_generation_artifacts,
)
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import (
    CourseIntent,
    SourceDocument,
    SourceFact,
    SourceSection,
)
from app.modules.ai.ingestion import DocumentChunker
from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    ValidatedCallFailureReason,
    ValidatedLLMResult,
)


def _spreadsheet_corpus() -> DirectSourceCorpus:
    primary = DirectSourceChunk(
        chunk_id="chunk-primary",
        doc_id="doc-plus",
        doc_name="plus.xlsx",
        title="plus.xlsx",
        headings=("[Worksheet] Коллекции",),
        text=(
            "# [Worksheet] Коллекции\n\n"
            "| Поле | Феникс | Чикаго Нео | Чикаго Стрит |\n"
            "| --- | --- | --- | --- |\n"
            "| Назначение | Для хранения | Для спальни | Для прихожей |\n"
            "| Материал | ЛДСП | ЛДСП и металл | МДФ |\n"
            "| Цвета | Белый | Кашемир | Бетон |"
        ),
        source_revision="document:plus-sha",
        chunk_index=0,
    )
    supporting_rows = "\n".join(
        f"| SKU-{index:03d} | Феникс модуль {index} | {index + 1} | Карточка товара |"
        for index in range(24)
    )
    supporting = DirectSourceChunk(
        chunk_id="chunk-supporting",
        doc_id="doc-plus",
        doc_name="plus.xlsx",
        title="plus.xlsx",
        headings=("[Worksheet] Номенклатура",),
        text=(
            "# [Worksheet] Номенклатура\n\n"
            "| Артикул | Наименование | Вес | Описание |\n"
            "| --- | --- | --- | --- |\n"
            f"{supporting_rows}"
        ),
        source_revision="document:plus-sha",
        chunk_index=1,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(
            DirectSourceDocument(
                doc_id="doc-plus",
                title="Империал Феникс Чикаго",
                filename="plus.xlsx",
                category="training_material",
                source_revision="document:plus-sha",
                chunks=(primary, supporting),
            ),
        ),
        total_chars=len(primary.text) + len(supporting.text),
        total_chunks=2,
    )


def _narrative_corpus() -> DirectSourceCorpus:
    chunk = DirectSourceChunk(
        chunk_id="chunk-rules",
        doc_id="doc-rules",
        doc_name="rules.pdf",
        title="Правила",
        headings=("2. ПОРЯДОК РАССМОТРЕНИЯ",),
        text=(
            "2.1. Заявление рассматривается в течение 15 рабочих дней.\n\n"
            "2.2. Ответ направляется не позднее 30 календарных дней."
        ),
        source_revision="document:rules-sha",
        chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-rules",
            title="Правила",
            filename="rules.pdf",
            category="training_material",
            source_revision="document:rules-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(chunk.text),
        total_chunks=1,
    )


def _sentence_heading_narrative_corpus() -> DirectSourceCorpus:
    chunk = DirectSourceChunk(
        chunk_id="chunk-sentence-heading",
        doc_id="doc-sentence-heading",
        doc_name="warehouse-policy.pdf",
        title="Правила склада",
        headings=(
            "3. Проверять каждый SKU смешанной паллеты, если нет условий для выборочного пересчета.",
        ),
        text=(
            "Каждую товарную позицию смешанной паллеты сверяют с накладной.\n\n"
            "Расхождения фиксируют в акте приемки."
        ),
        source_revision="document:sentence-heading-sha",
        chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-sentence-heading",
            title="Правила склада",
            filename="warehouse-policy.pdf",
            category="training_material",
            source_revision="document:sentence-heading-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(chunk.text),
        total_chunks=1,
    )


def _plain_numbered_policy_corpus() -> DirectSourceCorpus:
    text = (
        "1. Назначение и область применения\n"
        "Правила определяют порядок работы склада.\n\n"
        "2. Роли и ответственность\n"
        "Ответственный сотрудник проверяет документы поставки.\n"
        "3. Не смешивать поставки до окончания приемки.\n\n"
        "3. Подготовка к прибытию транспорта\n"
        "До прибытия транспорта сотрудник освобождает зону разгрузки."
    )
    chunk = DirectSourceChunk(
        chunk_id="chunk-plain-numbered",
        doc_id="doc-plain-numbered",
        doc_name="warehouse-policy.pdf",
        title="Правила склада",
        headings=(),
        text=text,
        source_revision="document:plain-numbered-sha",
        chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-plain-numbered",
            title="Правила склада",
            filename="warehouse-policy.pdf",
            category="training_material",
            source_revision="document:plain-numbered-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(text),
        total_chunks=1,
    )


def _production_smoke_narrative_corpus() -> DirectSourceCorpus:
    source = (
        Path(__file__).parents[1]
        / "fixtures"
        / "ai"
        / "production_smoke_client_service.txt"
    ).read_text(encoding="utf-8")
    raw_chunks = DocumentChunker().chunk_markdown(
        source,
        "doc-production-smoke",
        "production-smoke.txt",
    )
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"direct:doc-production-smoke:{index}",
            doc_id="doc-production-smoke",
            doc_name="production-smoke.txt",
            title="Smoke: безопасное обслуживание клиента",
            headings=(),
            text=str(chunk["text"]),
            source_revision="document:production-smoke-sha",
            chunk_index=index,
        )
        for index, chunk in enumerate(raw_chunks)
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-production-smoke",
            title="Smoke: безопасное обслуживание клиента",
            filename="production-smoke.txt",
            category="training_material",
            source_revision="document:production-smoke-sha",
            chunks=chunks,
        ),),
        total_chars=len(source),
        total_chunks=len(chunks),
    )


def _ambiguous_guides_corpus() -> DirectSourceCorpus:
    chunk = DirectSourceChunk(
        chunk_id="chunk-guides",
        doc_id="doc-guides",
        doc_name="guides.xlsx",
        title="guides.xlsx",
        headings=("[Worksheet] Коллекции",),
        text=(
            "# [Worksheet] Коллекции\n\n"
            "| Поле | Чикаго Стрит | Феникс | Чикаго Нео |\n"
            "| --- | --- | --- | --- |\n"
            "| Направляющие | Роликовые направляющие: плавный бесшумный ход ящиков. "
            "| Роликовые направляющие на комодах, прикроватных тумбах и ящиках шкафов: "
            "плавный ровный ход. | Шариковые направляющие полного выдвижения. |"
        ),
        source_revision="document:guides-sha",
        chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-guides",
            title="Коллекции мебели",
            filename="guides.xlsx",
            category="training_material",
            source_revision="document:guides-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(chunk.text),
        total_chunks=1,
    )


def _source_style_phrase_corpus() -> DirectSourceCorpus:
    chunk = DirectSourceChunk(
        chunk_id="chunk-style",
        doc_id="doc-style",
        doc_name="style.xlsx",
        title="style.xlsx",
        headings=("[Worksheet] Коллекции",),
        text=(
            "# [Worksheet] Коллекции\n\n"
            "| Поле | Чикаго Нео |\n"
            "| --- | --- |\n"
            "| Основная идея | Дорогая матовая эстетика и полноценные габариты, "
            "не компакт с маркетплейса. |\n"
            "| Кому рекомендовать | Кто хочет современный look без ручек и нормальные, "
            "не «игрушечные» габариты. |"
        ),
        source_revision="document:style-sha",
        chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-style",
            title="Коллекции мебели",
            filename="style.xlsx",
            category="training_material",
            source_revision="document:style-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(chunk.text),
        total_chunks=1,
    )


def _overlong_fallback_spreadsheet_corpus() -> DirectSourceCorpus:
    rows = "\n".join(
        f"| Правило {index} | "
        + " ".join(f"условие{index}" for _ in range(125))
        + " |"
        for index in range(1, 7)
    )
    text = (
        "# [Worksheet] Правила\n\n"
        "| Поле | Основной порядок |\n"
        "| --- | --- |\n"
        f"{rows}"
    )
    chunk = DirectSourceChunk(
        chunk_id="chunk-overlong-fallback",
        doc_id="doc-overlong-fallback",
        doc_name="rules.xlsx",
        title="rules.xlsx",
        headings=("[Worksheet] Правила",),
        text=text,
        source_revision="document:overlong-fallback-sha",
        chunk_index=0,
    )
    return DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-overlong-fallback",
            title="Основной порядок",
            filename="rules.xlsx",
            category="training_material",
            source_revision="document:overlong-fallback-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(text),
        total_chunks=1,
    )


class _EmbeddingClient:
    def __init__(self, *, fail: bool = False, query_space: str = "test-space") -> None:
        self.fail = fail
        self.query_space = query_space
        self.documents: list[str] = []
        self.queries: list[str] = []

    async def embed_documents_with_provenance(self, texts: list[str], *, on_progress=None):
        self.documents = list(texts)
        if self.fail:
            raise AllProvidersFailedError("embedding chain exhausted")
        if on_progress is not None:
            await on_progress(len(texts), len(texts), "test-doc-provider")
        vectors = tuple((1.0, float(index + 1), 0.5) for index, _ in enumerate(texts))
        return SimpleNamespace(vectors=vectors, model="test-embedding", space="test-space")

    async def embed_queries_with_provenance(self, texts: list[str], *, on_progress=None):
        self.queries.extend(texts)
        if on_progress is not None:
            await on_progress(len(texts), len(texts), "test-query-provider")
        return SimpleNamespace(
            vectors=tuple((1.0, 1.0, 0.5) for _ in texts),
            model="test-embedding",
            space=self.query_space,
        )


class _GenerationClient:
    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        if request.get("task", "").startswith("assessment_"):
            # Contract transport fake, not a semantic quality oracle. Semantic
            # negatives and live-provider acceptance have separate fixtures.
            if request["task"] == "assessment_constraints":
                payload = {"rules": [{"fact_id": f["fact_id"], "quote": f["value"], "kind": "attribute"}
                                     for f in request["facts"]],
                           "reviews": [{"question_id": q["question_id"], "reason": "Fixture contract", "distinct_errors": True,
                                        "options": [{"index": i, "relation": "entailed" if i == 0 else "contradicted",
                                                     "invented_constraint": False, "realistic_error": True} for i in range(len(q["options"]))]}
                                       for q in request["questions"]]}
            elif request["task"] == "assessment_review":
                payload = {"reviews": [
                    {"question_id": q["question_id"], "question_supported": True,
                     "educational": True, "explanation_supported": True, "options_distinct": True,
                     "options": [{"index": i, "answers_question": True,
                                  "correct": i == 0, "plausible_error": i != 0,
                                  "contradicted_by_source": i != 0, "same_practical_task": True}
                                 for i in range(len(q["options"]))]}
                    for q in request["questions"]]}
            else:
                payload = {"questions": [
                    {"prompt": f"Как применять правило для «{axis['subject']}»?",
                     "axis_id": axis["axis_id"],
                     "distractors": ["Применять обратный порядок действий.",
                                     "Не учитывать установленные условия применения."]}
                    for axis in request["axes"]]}
            return ValidatedLLMResult(provider="test-generation", model_id="test-model",
                value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1, failure_reasons=())
        payload = {
            "title": request["lesson_title"],
            "objective": request["objective"],
            "blocks": [
                {
                    "heading": "Подтверждённые сведения",
                    "text": fact["value"],
                    "fact_ids": [fact["fact_id"]],
                }
                for fact in request["facts"]
            ],
            "questions": [
                {
                    "prompt": seed["prompt"],
                    "explanation": "Ответ подтверждён исходным материалом.",
                    "fact_ids": [seed["fact_id"]],
                }
                for seed in request["question_seeds"]
            ],
        }
        return ValidatedLLMResult(
            provider="test-generation",
            model_id="test-model",
            value=parser(json.dumps(payload, ensure_ascii=False)),
            attempt_count=2,
            failure_reasons=(ValidatedCallFailureReason.PROVIDER_TIMEOUT,),
        )


class _AdversarialAnswerKeyGenerationClient(_GenerationClient):
    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        if request.get("task") == "assessment_generate":
            payload = {"questions": [
                {
                    "axis_id": axis["axis_id"],
                    "prompt": "Какое правило необходимо применить?",
                    "distractors": [
                        "Применить противоположное правило.",
                        "Игнорировать условие исходного документа.",
                    ],
                    "correct_index": 1,
                    "correct_answer": "Игнорировать условие исходного документа.",
                }
                for axis in request["axes"]
            ]}
            return ValidatedLLMResult(
                provider="adversarial-fixture",
                model_id="adversarial-fixture",
                value=parser(json.dumps(payload, ensure_ascii=False)),
                attempt_count=1,
                failure_reasons=(),
            )
        return await super().ainvoke_validated(messages, parser, **kwargs)


class _ProductionDefectNeutralizingGenerationClient(_GenerationClient):
    def __init__(self) -> None:
        self.neutralized_production_defects = 0

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        if request.get("task", "").startswith("assessment_"):
            return await super().ainvoke_validated(messages, parser, **_kwargs)
        bad_payload = {
            "title": request["lesson_title"],
            "objective": request["objective"],
            "blocks": [
                {
                    "heading": "Позиционирование",
                    "text": (
                        "Полноценные габариты, а не компакт с маркетплейса."
                        if index == 0
                        else fact["value"]
                    ),
                    "fact_ids": [fact["fact_id"]],
                }
                for index, fact in enumerate(request["facts"])
            ],
            "questions": [],
        }
        value = parser(json.dumps(bad_payload, ensure_ascii=False))
        assert "маркетплейса" not in value[0].content.casefold()
        self.neutralized_production_defects += 1
        return ValidatedLLMResult(
            provider="test-generation",
            model_id="test-model",
            value=value,
        )


def test_direct_corpus_adapter_uses_passport_and_retains_source_identity() -> None:
    bundle = build_evidence_source(_spreadsheet_corpus())

    assert bundle.document.kind == "spreadsheet"
    assert [section.title for section in bundle.document.sections if section.role == "primary"] == [
        "Коллекции"
    ]
    assert [section.title for section in bundle.document.sections if section.role == "supporting"] == [
        "Номенклатура"
    ]
    assert all("doc_id=doc-plus" in fact.source_locator for fact in bundle.all_facts)
    assert all("source_revision=document:plus-sha" in fact.source_locator for fact in bundle.all_facts)


def test_direct_corpus_adapter_splits_numbered_narrative_clauses() -> None:
    bundle = build_evidence_source(_narrative_corpus())

    assert bundle.document.kind == "narrative"
    assert bundle.document.sections[0].role == "primary"
    assert [fact.attribute for fact in bundle.all_facts] == ["срок", "срок"]
    assert all("doc_id=doc-rules" in fact.source_locator for fact in bundle.all_facts)


def test_plain_numbered_policy_keeps_instruction_items_inside_major_sections() -> None:
    bundle = build_evidence_source(_plain_numbered_policy_corpus())

    assert [section.title for section in bundle.document.sections] == [
        "1. Назначение и область применения",
        "2. Роли и ответственность",
        "3. Подготовка к прибытию транспорта",
    ]
    roles = next(
        section for section in bundle.document.sections if section.title == "2. Роли и ответственность"
    )
    assert any("Не смешивать поставки" in fact.value for fact in roles.facts)


def test_plain_numbered_policy_supports_parentheses_and_finite_verb_items() -> None:
    text = (
        "1) Назначение и область применения\n"
        "Правила определяют порядок работы склада.\n\n"
        "2) К условиям хранения\n"
        "Описание условий хранения для каждой поставки.\n"
        "3) Сотрудник проверяет документы\n"
        "4) Check the label before unloading\n\n"
        "5) Подготовка к прибытию транспорта\n"
        "До прибытия транспорта сотрудник освобождает зону разгрузки."
    )
    chunk = DirectSourceChunk(
        chunk_id="chunk-plain-parenthesized",
        doc_id="doc-plain-parenthesized",
        doc_name="warehouse-policy.pdf",
        title="Правила склада",
        headings=(),
        text=text,
        source_revision="document:plain-parenthesized-sha",
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-plain-parenthesized",
            title="Правила склада",
            filename="warehouse-policy.pdf",
            category="training_material",
            source_revision="document:plain-parenthesized-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(text),
        total_chunks=1,
    )

    bundle = build_evidence_source(corpus)

    assert [section.title for section in bundle.document.sections] == [
        "1) Назначение и область применения",
        "2) К условиям хранения",
        "5) Подготовка к прибытию транспорта",
    ]
    storage = next(
        section for section in bundle.document.sections if section.title == "2) К условиям хранения"
    )
    assert any("Сотрудник проверяет документы" in fact.value for fact in storage.facts)
    assert any("Check the label before unloading" in fact.value for fact in storage.facts)


def test_narrative_preamble_and_appendices_are_supporting_context() -> None:
    chunks = (
        DirectSourceChunk(
            chunk_id="chunk-preamble",
            doc_id="doc-policy",
            doc_name="policy.pdf",
            title="Политика склада",
            headings=(),
            text="Версия 1.0. Документ для сотрудников склада.",
            source_revision="document:policy-sha",
            chunk_index=0,
        ),
        DirectSourceChunk(
            chunk_id="chunk-main",
            doc_id="doc-policy",
            doc_name="policy.pdf",
            title="Политика склада",
            headings=("1. Порядок приемки",),
            text="Сотрудник проверяет документы до разгрузки.",
            source_revision="document:policy-sha",
            chunk_index=1,
        ),
        DirectSourceChunk(
            chunk_id="chunk-appendix",
            doc_id="doc-policy",
            doc_name="policy.pdf",
            title="Политика склада",
            headings=("1. Порядок приемки",),
            text="Приложение A. Контрольные сроки. Уведомить руководителя за 15 минут.",
            source_revision="document:policy-sha",
            chunk_index=2,
        ),
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-policy",
            title="Политика склада",
            filename="policy.pdf",
            category="training_material",
            source_revision="document:policy-sha",
            chunks=chunks,
        ),),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=len(chunks),
    )

    bundle = build_evidence_source(corpus)
    roles = {section.title: section.role for section in bundle.document.sections}

    assert roles == {
        "Политика склада": "supporting",
        "1. Порядок приемки": "primary",
        "Приложение A": "supporting",
    }


def test_narrative_fact_split_drops_page_markers_but_keeps_appendix_markers() -> None:
    parts = _split_narrative_chunk(
        "Политика склада Страница 2\n\n"
        "Сотрудник проверяет документы до разгрузки.\n\n"
        "Политика склада Страница 19 Приложение A. Контрольные сроки."
    )

    assert all("Страница 2" not in part for part in parts)
    assert any("Приложение A" in part for part in parts)


def test_narrative_fact_split_removes_ocr_title_page_and_inline_glyph_noise() -> None:
    parts = _split_narrative_chunk(
        '„т«УТВЕРЖДЕНО» © Протоколом №5. '
        "ПРАВИЛА ПРЕДОСТАВЛЕНИЯ МИКРОКРЕДИТОВ.\n\n"
        "Получение залогового имущества подтверждается подписью Клиента "
        "в соответствующей ® т строке Залогового билета.\n\n"
        "Ломбард отвечает за сохранность залога (ст."
    )

    assert len(parts) == 2
    assert all("УТВЕРЖДЕНО" not in part for part in parts)
    assert all(not any(marker in part for marker in ("®", "©", "°", "™")) for part in parts)
    assert "в соответствующей строке" in parts[0]
    assert parts[1].endswith("сохранность залога")


def test_narrative_fact_split_drops_non_textual_ocr_fragments() -> None:
    parts = _split_narrative_chunk(
        "Сотрудник проверяет документ до выдачи.\n\n`\n\n| -- |"
    )

    assert parts == ["Сотрудник проверяет документ до выдачи."]


@pytest.mark.parametrize(
    ("value", "uncertainty"),
    [
        (") Ломбарда, с учетом условий и ограничений, установленных законодательством.",
         "truncated_source_boundary"),
        ("14: При получении заявления Ломбард вправе оставить его без ответа.",
         "ocr_numbering_prefix"),
        ("Ломбард обязан письменно известить уполномоченный орган путем опубликования соответствующей",
         "incomplete_source_clause"),
        ("Условие | Описание", "table_header_fragment"),
        (
            "Перечень имущества не является исчерпывающим. др. ) Ломбарда, "
            "с учетом условий, установленных законодательством.",
            "truncated_source_boundary",
        ),
    ],
)
def test_narrative_adapter_rejects_observed_ocr_boundary_artifacts(
    value: str,
    uncertainty: str,
) -> None:
    metadata = _narrative_fact_metadata(value)

    assert metadata == {"confidence": 0.0, "uncertainty": uncertainty}


def test_narrative_adapter_keeps_complete_numbered_rule() -> None:
    metadata = _narrative_fact_metadata(
        "14. Ломбард вправе оставить заявление без ответа по существу."
    )

    assert metadata == {"confidence": 1.0, "uncertainty": ""}


def test_narrative_adapter_marks_truncated_lowercase_boundary_unusable() -> None:
    chunk = DirectSourceChunk(
        chunk_id="chunk-truncated",
        doc_id="doc-truncated",
        doc_name="policy.pdf",
        title="Политика",
        headings=("7. Расчёт ставки",),
        text=(
            "и микрокредита не допускаются в период рассмотрения обращения.\n\n"
            "Клиент вправе получить расчёт ставки."
        ),
        source_revision="document:truncated-sha",
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-one",
        documents=(DirectSourceDocument(
            doc_id="doc-truncated",
            title="Политика",
            filename="policy.pdf",
            category="training_material",
            source_revision="document:truncated-sha",
            chunks=(chunk,),
        ),),
        total_chars=len(chunk.text),
        total_chunks=1,
    )

    bundle = build_evidence_source(corpus)
    facts = list(bundle.all_facts)

    assert facts[0].confidence == 0.0
    assert facts[0].uncertainty == "truncated_source_boundary"
    assert facts[1].confidence == 1.0


def test_zero_confidence_narrative_fragment_is_not_admitted_to_course() -> None:
    source = SourceDocument(
        source_id="source",
        title="Политика",
        kind="narrative",
        sections=(SourceSection(
            section_id="section",
            title="7. Расчёт ставки",
            role="primary",
            facts=(
                SourceFact(
                    "broken", "7. Расчёт ставки", "положение",
                    "и микрокредита не допускаются в период рассмотрения обращения.",
                    "doc_id=d1;section=7;part=1", 0.0, "truncated_source_boundary",
                ),
                SourceFact(
                    "valid", "7. Расчёт ставки", "право",
                    "Клиент вправе получить расчёт ставки.",
                    "doc_id=d1;section=7;part=2",
                ),
            ),
        ),),
    )

    result = EvidenceCourseEngine().generate_from_document(source)

    assert len(result.admitted_facts) == 1
    assert result.admitted_facts[0].value == "Клиент вправе получить расчёт ставки."


def test_production_smoke_plain_text_reconstructs_sections_without_overlap_duplicates() -> None:
    bundle = build_evidence_source(_production_smoke_narrative_corpus())

    assert [section.title for section in bundle.document.sections] == [
        "1. Цель и область применения",
        "2. Начало разговора",
        "3. Уточнение потребности",
        "4. Приоритеты",
        "5. Фиксация обращения",
        "6. Срок первого ответа",
        "7. Эскалация",
        "8. Завершение",
        "9. Контрольные правила",
        "10. Краткий пример",
    ]
    # Paragraphs preserve conditions/exceptions instead of 34 isolated sentences.
    assert len(bundle.all_facts) == 10
    assert sum("15 минут" in fact.value for fact in bundle.all_facts) == 2


def test_sparse_narrative_is_not_padded_to_an_arbitrary_lesson_quota() -> None:
    bundle = build_evidence_source(_narrative_corpus())
    result = EvidenceCourseEngine().generate_from_document(bundle.document)

    assert len(result.course.lessons) == 1


@pytest.mark.asyncio
async def test_production_smoke_plain_text_uses_real_v2_path_without_collapsing_course() -> None:
    """The browser smoke source must exercise the production Evidence V2 seam."""

    corpus = _production_smoke_narrative_corpus()
    generated = await generate_evidence_course(
        corpus,
        intent=CourseIntent(),
        generation_client=_GenerationClient(),
        embedding_client=_EmbeddingClient(),
    )
    artifacts = to_generation_artifacts(generated)
    lessons = [lesson for module in artifacts.structure.modules for lesson in module.lessons]
    questions = [question for item in artifacts.assessment.assessments for question in item.mcq]

    assert len(generated.result.evidence_result.document_plan.primary_sections) == 10
    assert len(lessons) == 10  # independent section boundaries, not size-only pairs
    assert len(questions) >= 3
    assert all(question.question not in {"О чём этот урок?", "Что именно разберём в этом уроке?"} for question in questions)
    assert all(question.source_quote for question in questions)
    assert any("15 минут" in question.source_quote for question in questions)
    assert artifacts.diagnostics["assessment_review"]["accepted"] == len(questions)
    correct_answers = [
        next(option.text for option in question.options if option.is_correct).casefold()
        for question in questions
    ]
    assert len(correct_answers) == len(set(correct_answers))


@pytest.mark.asyncio
async def test_invalid_deterministic_plan_fails_before_embedding_or_generation_calls() -> None:
    embeddings = _EmbeddingClient()

    with pytest.raises(ValueError, match="evidence_plan_invalid:invalid_lesson_titles"):
        await generate_evidence_course(
            _sentence_heading_narrative_corpus(),
            intent=CourseIntent(),
            generation_client=_GenerationClient(),
            embedding_client=embeddings,
        )

    assert embeddings.documents == []
    assert embeddings.queries == []


@pytest.mark.asyncio
async def test_async_application_generates_publishable_existing_pipeline_artifacts() -> None:
    embeddings = _EmbeddingClient()
    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(purpose="Обучить продавцов ассортименту"),
        generation_client=_GenerationClient(),
        embedding_client=embeddings,
    )
    artifacts = to_generation_artifacts(generated)

    assert generated.result.publishability.publishable is True
    assert embeddings.documents
    assert embeddings.queries
    assert not embeddings.queries[0].startswith("Instruct:")
    assert artifacts.structure.modules
    assert artifacts.content.modules
    assert sum(len(item.mcq) for item in artifacts.assessment.assessments) > 0
    assert {
        reference["doc_id"]
        for module in artifacts.content.modules
        for lesson in module.lessons
        for reference in lesson.source_references
    } == {"doc-plus"}
    assert generated.result.provider_fallback_count > 0
    assert generated.result.chat_attempt_count >= len(generated.result.realized_course.lessons)
    assert "provider_timeout" in generated.result.validation_errors


@pytest.mark.asyncio
async def test_active_v2_neutralizes_source_sales_style_before_persistence() -> None:
    generation = _ProductionDefectNeutralizingGenerationClient()

    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(purpose="Обучить продавцов ассортименту"),
        generation_client=generation,
        embedding_client=_EmbeddingClient(),
    )
    artifacts = to_generation_artifacts(generated)
    learner_text = "\n".join(
        lesson.content
        for module in artifacts.content.modules
        for lesson in module.lessons
    ).casefold()

    assert generation.neutralized_production_defects == len(generated.result.realized_course.lessons)
    assert "маркетплейса" not in learner_text
    assert generated.result.publishability.publishable is True


@pytest.mark.asyncio
async def test_active_v2_drops_ambiguous_same_attribute_question_without_padding() -> None:
    class AmbiguousClient(_GenerationClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request.get("task") == "assessment_review" and any(
                "роликовые направляющие: плавный" in q["source_quote"].casefold()
                for q in request["questions"]
            ):
                # Exact negative oracle: the first TWO options describe roller
                # guides and both answer the asked attribute correctly.
                payload = {"reviews": [{"question_id": q["question_id"],
                        "question_supported": True, "educational": True, "explanation_supported": True, "options_distinct": True,
                    "options": [{"index": i, "answers_question": True, "correct": i < 2,
                                     "plausible_error": i == 2, "contradicted_by_source": i == 2, "same_practical_task": True}
                                for i in range(len(q["options"]))]}
                    for q in request["questions"]]}
                return ValidatedLLMResult(provider="fixture", model_id="fixture",
                    value=parser(json.dumps(payload)), attempt_count=1, failure_reasons=())
            if request.get("task") in {"assessment_generate", "assessment_repair"}:
                fact = next((f for f in request["facts"]
                             if "роликовые направляющие: плавный" in f["value"].casefold()), None)
                if fact:
                    axis = next(a for a in request["axes"]
                                if a["source_claim"] == fact["value"])
                    payload = {"questions": [{
                        "prompt": "Какие направляющие используются в коллекции «Чикаго Стрит»?",
                        "axis_id": axis["axis_id"],
                        "distractors": ["Роликовые направляющие на комодах", "Шариковые направляющие"],
                    }]}
                    return ValidatedLLMResult(provider="fixture", model_id="fixture",
                        value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1, failure_reasons=())
            return await super().ainvoke_validated(messages, parser, **kwargs)

    generated = await generate_evidence_course(
        _ambiguous_guides_corpus(),
        intent=CourseIntent(purpose="Обучить продавцов ассортименту"),
        generation_client=AmbiguousClient(),
        embedding_client=_EmbeddingClient(),
    )
    artifacts = to_generation_artifacts(generated)
    questions = [
        question
        for assessment in artifacts.assessment.assessments
        for question in assessment.mcq
    ]
    captured_prompt = "Какие направляющие используются в коллекции «Чикаго Стрит»?"
    original_question = next(
        question
        for question in generated.result.evidence_result.assessment.questions
        if question.prompt == captured_prompt
    )
    lesson_title = next(
        lesson.title
        for lesson in generated.result.evidence_result.course.lessons
        if lesson.lesson_id == original_question.lesson_id
    )
    retained_assessment = next(
        assessment
        for assessment in artifacts.assessment.assessments
        if assessment.lesson_title == lesson_title
    )

    assert questions
    assert all(question.question != captured_prompt for question in questions)
    assert retained_assessment.mcq == []
    assert retained_assessment.omission_reason == "no_safe_source_grounded_questions"
    assert all(
        not (
            option.is_correct
            and "роликовые направляющие: плавный бесшумный ход ящиков" in option.text.casefold()
            and any(
                "роликовые направляющие на комодах" in other.text.casefold()
                for other in question.options
            )
        )
        for question in questions
        for option in question.options
    )
    assert generated.result.assessment_review["omitted_count"] >= 1
    assert any(
        "correct_option_count_or_key" in outcome["reason"]
        for outcome in generated.result.assessment_review["axis_outcomes"]
    )
    assert len(questions) < generated.result.assessment_review["requested_axes"]


@pytest.mark.asyncio
async def test_artifacts_require_review_when_assessment_contract_audit_is_incomplete() -> None:
    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationClient(),
        embedding_client=_EmbeddingClient(),
    )
    review = {
        **generated.result.assessment_review,
        "terminal_status": "review_required",
        "coverage": {
            **generated.result.assessment_review.get("coverage", {}),
            "requires_review": False,
        },
    }
    output = replace(
        generated,
        result=replace(generated.result, assessment_review=review),
    )

    artifacts = to_generation_artifacts(output)

    assert artifacts.diagnostics["quality_status"] == "assessment_needs_review"


@pytest.mark.asyncio
async def test_embedding_progress_counts_document_and_query_units_with_provider() -> None:
    events: list[tuple[str, int, int, str | None, int | None]] = []

    async def progress(
        stage: str,
        current: int,
        total: int,
        provider: str | None,
        attempt: int | None,
    ) -> None:
        events.append((stage, current, total, provider, attempt))

    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationClient(),
        embedding_client=_EmbeddingClient(),
        progress_callback=progress,
    )

    embedding_events = [event for event in events if event[0] == "embeddings"]
    assert embedding_events
    assert embedding_events[-1][1] == embedding_events[-1][2]
    assert embedding_events[-1][3] == "test-query-provider"
    assert generated.result.embedding_degraded is False


@pytest.mark.asyncio
async def test_application_seam_ignores_provider_selected_answer_key() -> None:
    generated = await generate_evidence_course(
        _narrative_corpus(),
        intent=CourseIntent(),
        generation_client=_AdversarialAnswerKeyGenerationClient(),
        embedding_client=_EmbeddingClient(),
    )

    source_values = {fact.value for fact in generated.result.evidence_result.admitted_facts}
    questions = generated.result.realized_assessment.questions
    assert questions
    assert all(any(question.correct_answer in value for value in source_values)
               for question in questions)
    assert all(question.correct_answer != "Игнорировать условие исходного документа."
               for question in questions)
    assert all(question.fact_id in {fact.fact_id for fact in generated.result.evidence_result.admitted_facts}
               for question in questions)


@pytest.mark.asyncio
async def test_embedding_chain_failure_is_degraded_but_generation_continues() -> None:
    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationClient(),
        embedding_client=_EmbeddingClient(fail=True),
    )

    assert generated.result.embedding_degraded is True


@pytest.mark.asyncio
async def test_incompatible_query_space_is_degraded_without_comparing_vectors() -> None:
    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationClient(),
        embedding_client=_EmbeddingClient(query_space="other-space"),
    )

    assert generated.result.embedding_degraded is True
    assert generated.result.retrieval == ()
    assert generated.result.publishability.publishable is True


class _GenerationFailure:
    async def ainvoke_validated(self, *_args, **_kwargs):
        raise AllProvidersFailedError("generation chain exhausted")


class _TransientGenerationFailure(_GenerationClient):
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke_validated(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise AllProvidersFailedError("first chain attempt rejected")
        return await super().ainvoke_validated(*args, **kwargs)


@pytest.mark.asyncio
async def test_generation_contract_gets_one_bounded_retry_before_failing_job() -> None:
    generation = _TransientGenerationFailure()

    generated = await generate_evidence_course(
        _narrative_corpus(),
        intent=CourseIntent(),
        generation_client=generation,
        embedding_client=_EmbeddingClient(),
    )

    assert generated.result.publishability.publishable is True
    # Writer retry plus one bounded author/review/constraint batch for the lesson.
    assert generation.calls == 5


@pytest.mark.asyncio
async def test_generation_provider_exhaustion_uses_grounded_deterministic_lesson_fallback() -> None:
    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationFailure(),
        embedding_client=_EmbeddingClient(),
    )

    assert generated.result.publishability.publishable is False
    assert generated.result.publishability.reasons == ("assessment_no_valid_questions",)
    assert generated.result.provider_fallback_count > 0
    assert generated.result.validation_errors
    assert all(lesson.content for lesson in generated.result.realized_course.lessons)
    artifacts = to_generation_artifacts(generated)
    assert artifacts.diagnostics["quality_status"] == "degraded_needs_review"
    assert artifacts.diagnostics["deterministic_fallback_count"] > 0
    assert artifacts.diagnostics["provider_fallback_count"] > 0
    assert artifacts.diagnostics["chat_attempt_count"] > 0
    assert artifacts.diagnostics["validation_errors"]
    assert artifacts.content.source_warnings
    assert all(
        lesson.source_validation_status == "needs_review"
        for module in artifacts.content.modules
        for lesson in module.lessons
    )
    planned = {
        fact_id
        for plan in generated.result.evidence_result.evidence_plan
        for fact_id in plan.fact_ids
    }
    covered = {
        fact_id
        for block in generated.result.grounded_blocks
        for fact_id in block.fact_ids
    }
    assert covered == planned


@pytest.mark.asyncio
async def test_grounded_fallback_splits_only_overlong_lesson_and_preserves_all_facts() -> None:
    generated = await generate_evidence_course(
        _overlong_fallback_spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationFailure(),
        embedding_client=_EmbeddingClient(),
    )

    lessons = generated.result.realized_course.lessons
    assert len(lessons) > 1
    assert len({lesson.lesson_id for lesson in lessons}) == len(lessons)
    assert all(len(lesson.content.split()) <= 650 for lesson in lessons)
    planned = {
        fact_id
        for plan in generated.result.evidence_result.evidence_plan
        for fact_id in plan.fact_ids
    }
    covered = {
        fact_id
        for block in generated.result.grounded_blocks
        for fact_id in block.fact_ids
    }
    assert covered == planned
    assert generated.result.publishability.reasons == ("assessment_no_valid_questions",)


@pytest.mark.asyncio
async def test_grounded_fallback_neutralizes_source_style_without_inventing_replacement_facts() -> None:
    generated = await generate_evidence_course(
        _source_style_phrase_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationFailure(),
        embedding_client=_EmbeddingClient(),
    )
    artifacts = to_generation_artifacts(generated)
    content = "\n".join(
        lesson.content
        for module in artifacts.content.modules
        for lesson in module.lessons
    ).casefold()

    assert generated.result.publishability.publishable is False
    assert generated.result.publishability.reasons == ("assessment_no_valid_questions",)
    assert "маркетплейс" not in content
    assert "игрушечн" not in content
    assert " look" not in content
    assert "полноценные габариты" in content
    assert "современный внешний вид" in content
    assert "дорогая матовая эстетика" in content
    assert "без ручек" in content


@pytest.mark.asyncio
async def test_grounded_fallback_escapes_hostile_markdown_and_html() -> None:
    content = _escape_markdown_text(
        "# Заголовок | *курсив* _подчёркивание_ `код` ![рисунок](x) ~тильда~\n"
        "- элемент <script>alert(1)</script> [Нажмите](javascript:alert(1))"
    )
    assert "<script>" not in content
    assert "[Нажмите](javascript:" not in content
    assert "\\# Заголовок \\| \\*курсив\\* \\_подчёркивание\\_ \\`код\\`" in content
    assert "\\!\\[рисунок\\]\\(x\\) \\~тильда\\~" in content
    assert "\\- элемент" in content
