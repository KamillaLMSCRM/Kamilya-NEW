from __future__ import annotations

import json
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
    build_evidence_source,
    generate_evidence_course,
    to_generation_artifacts,
)
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import CourseIntent
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


class _ProductionDefectThenCleanGenerationClient(_GenerationClient):
    def __init__(self) -> None:
        self.rejected_production_defects = 0

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
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
        with pytest.raises(ValueError, match="learner-visible language"):
            parser(json.dumps(bad_payload, ensure_ascii=False))
        self.rejected_production_defects += 1
        result = await super().ainvoke_validated(messages, parser, **_kwargs)
        return ValidatedLLMResult(
            provider=result.provider,
            model_id=result.model_id,
            value=result.value,
            attempt_count=result.attempt_count + 1,
            failure_reasons=(
                ValidatedCallFailureReason.VALIDATION_BLOCKED,
                *result.failure_reasons,
            ),
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
    assert len(bundle.all_facts) == 34
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
    assert 4 <= len(lessons) <= 6
    assert len(questions) >= 3
    assert all(question.question not in {"О чём этот урок?", "Что именно разберём в этом уроке?"} for question in questions)
    assert {"15 минут", "1 час", "4 рабочих часов"} <= {
        next(option.text for option in question.options if option.is_correct)
        for question in questions
    }
    correct_answers = [
        next(option.text for option in question.options if option.is_correct).casefold()
        for question in questions
    ]
    assert len(correct_answers) == len(set(correct_answers))


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
async def test_active_v2_rejects_production_style_defect_before_persistence() -> None:
    generation = _ProductionDefectThenCleanGenerationClient()

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

    assert generation.rejected_production_defects == len(generated.result.realized_course.lessons)
    assert "маркетплейса" not in learner_text
    assert generated.result.publishability.publishable is True


@pytest.mark.asyncio
async def test_active_v2_drops_ambiguous_same_attribute_question_without_padding() -> None:
    generated = await generate_evidence_course(
        _ambiguous_guides_corpus(),
        intent=CourseIntent(purpose="Обучить продавцов ассортименту"),
        generation_client=_GenerationClient(),
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
    assert len(questions) < len(generated.result.evidence_result.assessment.questions)


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
    assert generation.calls == 2


@pytest.mark.asyncio
async def test_generation_provider_exhaustion_uses_grounded_deterministic_lesson_fallback() -> None:
    generated = await generate_evidence_course(
        _spreadsheet_corpus(),
        intent=CourseIntent(),
        generation_client=_GenerationFailure(),
        embedding_client=_EmbeddingClient(),
    )

    assert generated.result.publishability.publishable is True
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

    assert generated.result.publishability.publishable is True
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
