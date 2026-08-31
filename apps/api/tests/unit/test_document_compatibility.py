import hashlib
from dataclasses import asdict
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ai.architect_schema import (
    CourseStructure,
    LearningObjective,
)
from app.modules.ai.architect_schema import (
    Lesson as ArchitectLesson,
)
from app.modules.ai.architect_schema import (
    Module as ArchitectModule,
)
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.ai.source_analysis import (
    DocumentVectorProfile,
    analyze_profiles,
    cosine_similarity,
)
from app.modules.ai.writer import (
    UnsupportedLessonSourceError,
    _retrieve_and_rerank,
    resolve_lesson_doc_ids,
    write_course,
    write_lesson,
)
from app.modules.ai.writer_schema import LessonContent
from app.modules.lessons.models import Lesson
from app.modules.lessons.schemas import LessonUpdate
from app.modules.lessons.service import update_lesson


def _profile(title: str, vector: list[float]) -> DocumentVectorProfile:
    return DocumentVectorProfile(
        doc_id=uuid4(),
        title=title,
        filename=f"{title}.pdf",
        vector=vector,
    )


def test_cosine_similarity_handles_zero_vector() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_related_documents_form_one_complete_link_cluster() -> None:
    result = analyze_profiles(
        [
            _profile("Пожарная безопасность", [1.0, 0.0, 0.0]),
            _profile("Инструкция по эвакуации", [0.95, 0.1, 0.0]),
            _profile("План противопожарных действий", [0.9, 0.15, 0.0]),
        ]
    )

    assert result.status == "compatible"
    assert result.requires_decision is False
    assert len(result.clusters) == 1


def test_unrelated_documents_are_split_and_require_decision() -> None:
    result = analyze_profiles(
        [
            _profile("Пожарная безопасность", [1.0, 0.0, 0.0]),
            _profile("Бренд и реклама", [0.0, 1.0, 0.0]),
            _profile("Продажи", [0.0, 0.9, 0.1]),
        ]
    )

    assert result.status == "incompatible"
    assert result.requires_decision is True
    assert len(result.clusters) == 2
    assert sorted(len(cluster.documents) for cluster in result.clusters) == [1, 2]


def test_complete_link_does_not_bridge_distant_documents() -> None:
    result = analyze_profiles(
        [
            _profile("A", [1.0, 0.0]),
            _profile("B", [0.8, 0.6]),
            _profile("C", [0.0, 1.0]),
        ],
        cluster_threshold=0.7,
    )

    assert len(result.clusters) == 2


def test_lesson_source_scope_keeps_only_selected_documents() -> None:
    assert resolve_lesson_doc_ids(["doc-b", "foreign-doc"], ["doc-a", "doc-b"]) == ["doc-b"]


def test_lesson_without_sources_uses_only_single_selected_document() -> None:
    assert resolve_lesson_doc_ids([], ["doc-a"]) == ["doc-a"]


def test_lesson_without_sources_is_rejected_for_multi_document_course() -> None:
    try:
        resolve_lesson_doc_ids([], ["doc-a", "doc-b"])
    except ValueError as error:
        assert "source_doc_ids" in str(error)
    else:
        raise AssertionError("multi-document lessons must have explicit sources")


def test_intentional_combination_requires_meaningful_goal() -> None:
    with pytest.raises(ValidationError):
        AIGenerateRequest(
            documents=[uuid4(), uuid4()],
            source_strategy="intentional_combination",
            combination_goal="слишком кратко",
        )


class _Embeddings:
    async def embed_query_with_provenance(self, text):
        return object()


def _verified_metadata(tenant_id: str, *, chunk_id: str, doc_id: str = "doc-1") -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "tenant_id": tenant_id,
        "doc_name": "Инструкция.pdf",
        "headings": '["Раздел 1"]',
        "embedding_provider": "synthetic",
        "embedding_model": "synthetic-model",
        "embedding_revision": "synthetic-r1",
        "embedding_native_dimensions": 3,
        "embedding_storage_dimensions": 4,
        "embedding_content_sha256": hashlib.sha256(chunk_id.encode("utf-8")).hexdigest(),
        "embedding_source_revision": "document:" + "a" * 64,
        "embedding_indexed_at": "2026-08-23T00:00:00+00:00",
        "chunk_index": 0,
    }


class _Store:
    def __init__(self, distance: float):
        self.distance = distance

    async def query(self, **kwargs):
        return {
            "documents": [["Подтвержденный фрагмент"]],
            "metadatas": [
                [
                    {
                        **_verified_metadata(
                            kwargs["tenant_id"],
                            chunk_id="chunk-1",
                        ),
                    }
                ]
            ],
            "distances": [[self.distance]],
        }


@pytest.mark.asyncio
async def test_retrieval_requires_tenant_before_embedding_or_store_access() -> None:
    class _NeverEmbeds:
        async def embed(self, texts):
            raise AssertionError("embedding must not run")

    with pytest.raises(ValueError, match="tenant_id_required"):
        await _retrieve_and_rerank(
            _Store(0.2),
            ["эвакуация"],
            "Порядок эвакуации",
            doc_ids=["doc-1"],
            embeddings_provider=_NeverEmbeds(),
        )


@pytest.mark.asyncio
async def test_retrieval_returns_traceable_relevant_fragment() -> None:
    chunks = await _retrieve_and_rerank(
        _Store(0.2),
        ["эвакуация"],
        "Порядок эвакуации",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        embeddings_provider=_Embeddings(),
    )

    assert len(chunks) == 1
    assert chunks[0].doc_id == "doc-1"
    assert chunks[0].chunk_id == "chunk-1"
    assert chunks[0].headings == ["Раздел 1"]
    assert chunks[0].retrieval_sources == ("semantic",)
    assert chunks[0].rrf_score > 0


@pytest.mark.asyncio
async def test_retrieval_does_not_fallback_to_irrelevant_fragment() -> None:
    chunks = await _retrieve_and_rerank(
        _Store(0.9),
        ["эвакуация"],
        "Порядок эвакуации",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        embeddings_provider=_Embeddings(),
    )

    assert chunks == []


@pytest.mark.asyncio
async def test_retrieval_uses_lexical_fallback_inside_selected_ocr_document() -> None:
    class _OcrStore(_Store):
        async def get_all_chunks(self, **kwargs):
            return [
                (
                    "Порядок предоставления микрокредита и заключения договора.",
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="chunk-ocr-1"),
                        "doc_name": "Правила.pdf",
                        "headings": '["ПОРЯДОК ПРЕДОСТАВЛЕНИЯ МИКРОКРЕДИТА"]',
                    },
                ),
                (
                    "Текст о внутреннем распорядке.",
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="chunk-ocr-2"),
                        "doc_name": "Правила.pdf",
                        "headings": '["ПРОЧЕЕ"]',
                    },
                ),
            ]

    chunks = await _retrieve_and_rerank(
        _OcrStore(0.96),
        ["Общие положения правил предоставления микрокредитов"],
        "Общие положения правил предоставления микрокредитов",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        embeddings_provider=_Embeddings(),
    )

    assert chunks[0].doc_id == "doc-1"
    assert chunks[0].chunk_id == "chunk-ocr-1"
    assert chunks[0].query == "lexical_source_fallback"
    assert chunks[0].retrieval_sources == ("lexical",)


@pytest.mark.asyncio
async def test_hybrid_retrieval_boosts_chunk_confirmed_by_both_channels() -> None:
    class _HybridStore(_Store):
        async def query(self, **kwargs):
            return {
                "documents": [["Совпадающий фрагмент", "Только semantic"]],
                "metadatas": [[
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="consensus"),
                        "doc_name": "Правила.pdf",
                        "headings": '["Раздел"]',
                    },
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="semantic-only"),
                        "doc_name": "Правила.pdf",
                        "headings": '["Раздел"]',
                    },
                ]],
                "distances": [[0.2, 0.25]],
            }

        async def get_all_chunks(self, **kwargs):
            return [
                (
                    "Совпадающий фрагмент",
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="consensus"),
                        "doc_name": "Правила.pdf",
                        "headings": '["Раздел"]',
                    },
                ),
                (
                    "Только lexical эвакуация",
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="lexical-only"),
                        "doc_name": "Правила.pdf",
                        "headings": '["Раздел"]',
                    },
                ),
            ]

    chunks = await _retrieve_and_rerank(
        _HybridStore(0.2),
        ["совпадающий фрагмент эвакуация"],
        "Порядок эвакуации",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        embeddings_provider=_Embeddings(),
    )

    assert chunks[0].chunk_id == "consensus"
    assert chunks[0].retrieval_sources == ("lexical", "semantic")
    assert set(chunks[0].contributing_queries) == {
        "lexical_source_fallback",
        "совпадающий фрагмент эвакуация",
    }
    assert asdict(chunks[0])["contributing_queries"] == chunks[0].contributing_queries
    assert chunks[0].rrf_score > chunks[1].rrf_score


@pytest.mark.asyncio
async def test_lexical_fallback_prefers_authoritative_heading_boundary() -> None:
    class _OcrStore(_Store):
        async def get_all_chunks(self, **kwargs):
            return [
                (
                    "Общие положения и порядок выплаты вознаграждения " * 20,
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="wrong-long-chunk"),
                        "doc_name": "Правила.pdf",
                        "headings": '["5. ПОРЯДОК ВЫПЛАТЫ ВОЗНАГРАЖДЕНИЯ"]',
                    },
                ),
                (
                    "Общие положения определяют область применения правил.",
                    {
                        **_verified_metadata(kwargs["tenant_id"], chunk_id="right-section-chunk"),
                        "doc_name": "Правила.pdf",
                        "headings": '["1. ОБЩИЕ ПОЛОЖЕНИЯ"]',
                    },
                ),
            ]

    chunks = await _retrieve_and_rerank(
        _OcrStore(0.96),
        ["Общие положения"],
        "Общие положения",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        embeddings_provider=_Embeddings(),
        preferred_headings=["1. ОБЩИЕ ПОЛОЖЕНИЯ"],
    )

    assert [chunk.chunk_id for chunk in chunks] == ["right-section-chunk"]


@pytest.mark.asyncio
async def test_retrieval_rejects_untraceable_lexical_fallback() -> None:
    class _UntraceableOcrStore(_Store):
        async def get_all_chunks(self, **kwargs):
            return [
                (
                    "Порядок предоставления микрокредита и заключения договора.",
                    {
                        "doc_id": "doc-1",
                        "doc_name": "Правила.pdf",
                        "headings": '["ПОРЯДОК ПРЕДОСТАВЛЕНИЯ МИКРОКРЕДИТА"]',
                    },
                )
            ]

    chunks = await _retrieve_and_rerank(
        _UntraceableOcrStore(0.96),
        ["Порядок предоставления микрокредита"],
        "Порядок предоставления микрокредита",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        embeddings_provider=_Embeddings(),
    )

    assert chunks == []


@pytest.mark.asyncio
async def test_document_grounded_lesson_never_uses_general_knowledge_fallback() -> None:
    class _NeverCalledLLM:
        async def ainvoke(self, messages):
            raise AssertionError("LLM must not be called without relevant sources")

    with pytest.raises(
        UnsupportedLessonSourceError,
        match="No relevant source fragments",
    ) as exc_info:
        await write_lesson(
            llm=_NeverCalledLLM(),
            store=_Store(0.9),
            lesson_title="Порядок эвакуации",
            objectives=["Знать порядок"],
            module_title="Безопасность",
            course_title="Пожарная безопасность",
            doc_ids=["doc-1"],
            tenant_id=str(uuid4()),
            embeddings_provider=_Embeddings(),
            require_sources=True,
        )
    assert exc_info.value.lesson_title == "Порядок эвакуации"


@pytest.mark.asyncio
async def test_selected_documents_imply_required_sources_for_direct_callers() -> None:
    class _NeverCalledLLM:
        async def ainvoke(self, messages):
            raise AssertionError("general-knowledge fallback must not run")

    with pytest.raises(UnsupportedLessonSourceError):
        await write_lesson(
            llm=_NeverCalledLLM(),
            store=_Store(0.9),
            lesson_title="Порядок эвакуации",
            objectives=["Знать порядок"],
            module_title="Безопасность",
            course_title="Пожарная безопасность",
            doc_ids=["doc-1"],
            tenant_id=str(uuid4()),
            embeddings_provider=_Embeddings(),
        )


@pytest.mark.asyncio
async def test_write_lesson_exposes_heading_and_course_wide_scope_to_writer() -> None:
    class _CapturingLLM:
        def __init__(self) -> None:
            self.prompt = ""

        async def ainvoke(self, messages):
            self.prompt = messages[0]["content"]
            return type("Response", (), {"content": "# Заключительные положения"})()

    llm = _CapturingLLM()
    await write_lesson(
        llm=llm,
        store=_Store(0.2),
        lesson_title="Заключительные положения",
        objectives=["Применять заключительные положения"],
        module_title="Завершение",
        course_title="Правила",
        doc_ids=["doc-1"],
        tenant_id=str(uuid4()),
        relevant_headings=["13. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ"],
        sibling_lessons=["Общие положения", "Порядок обращений"],
        embeddings_provider=_Embeddings(),
        require_sources=True,
    )

    assert "AUTHORITATIVE SOURCE HEADING BOUNDARIES" in llm.prompt
    assert "13. ЗАКЛЮЧИТЕЛЬНЫЕ ПОЛОЖЕНИЯ" in llm.prompt
    assert "OTHER LESSONS IN COURSE" in llm.prompt
    assert "Общие положения" in llm.prompt
    assert "Порядок обращений" in llm.prompt


@pytest.mark.asyncio
async def test_write_lesson_expands_traceable_context_and_preserves_provenance(
    monkeypatch,
) -> None:
    revision = f"document:{'a' * 64}"

    def _metadata(index: int, *, chunk_id: str) -> dict:
        return {
            "chunk_id": chunk_id,
            "doc_id": "doc-1",
            "tenant_id": tenant_id,
            "doc_name": "Правила.pdf",
            "headings": '["Раздел 1"]',
            "embedding_provider": "provider-a",
            "embedding_model": "model-a",
            "embedding_revision": "rev-a",
            "embedding_native_dimensions": 3,
            "embedding_storage_dimensions": 4,
            "embedding_content_sha256": f"{index}" * 64,
            "embedding_source_revision": revision,
            "embedding_indexed_at": "2026-08-23T00:00:00+00:00",
            "chunk_index": index,
        }

    class _ContextStore(_Store):
        def __init__(self) -> None:
            super().__init__(0.2)
            self.context_call = None

        async def query(self, **kwargs):
            return {
                "documents": [["Опорный фрагмент"]],
                "metadatas": [[_metadata(4, chunk_id="chunk-4")]],
                "distances": [[0.2]],
            }

        async def get_context_window(self, **kwargs):
            self.context_call = kwargs
            return [
                ("Предыдущий фрагмент", _metadata(3, chunk_id="chunk-3")),
                ("Опорный фрагмент", _metadata(4, chunk_id="chunk-4")),
                ("Следующий фрагмент", _metadata(5, chunk_id="chunk-5")),
            ]

    class _CapturingLLM:
        def __init__(self) -> None:
            self.prompt = ""

        async def ainvoke(self, messages):
            self.prompt = messages[0]["content"]
            return type("Response", (), {"content": "# Урок"})()

    tenant_id = str(uuid4())
    store = _ContextStore()
    llm = _CapturingLLM()
    lesson = await write_lesson(
        llm=llm,
        store=store,
        lesson_title="Раздел 1",
        objectives=["Понять раздел"],
        module_title="Модуль",
        course_title="Правила",
        doc_ids=["doc-1"],
        tenant_id=tenant_id,
        embeddings_provider=_Embeddings(),
        require_sources=True,
    )

    assert store.context_call == {
        "tenant_id": tenant_id,
        "doc_id": "doc-1",
        "source_revision": revision,
        "chunk_index": 4,
        "radius": 1,
    }
    assert "Предыдущий фрагмент" in llm.prompt
    assert "Опорный фрагмент" in llm.prompt
    assert "Следующий фрагмент" in llm.prompt
    assert "role: ANCHOR" in llm.prompt
    assert "role: NEIGHBOR" in llm.prompt
    reference = lesson.source_references[0]
    assert set(reference) == {
        "document",
        "doc_id",
        "doc_name",
        "headings",
        "context_sections",
    }
    assert reference["document"] == "Правила.pdf"
    assert reference["doc_id"]
    assert reference["doc_name"] == "Правила.pdf"
    assert [section["is_anchor"] for section in reference["context_sections"]] == [
        False,
        True,
        False,
    ]
    serialized_reference = str(reference).lower()
    for forbidden in (
        "embedding_provider",
        "embedding_model",
        "embedding_revision",
        "content_sha256",
        "source_revision",
        "indexed_at",
        "chunk_id",
        "tenant_id",
    ):
        assert forbidden not in serialized_reference
    monkeypatch.setattr("app.modules.ai.writer.MAX_WRITER_PROMPT_CHARS", 100)
    with pytest.raises(ValueError, match="writer_prompt_budget_exceeded"):
        await write_lesson(
            llm=llm,
            store=store,
            lesson_title="Раздел 1",
            objectives=["Понять раздел"],
            module_title="Модуль",
            course_title="Правила",
            doc_ids=["doc-1"],
            tenant_id=tenant_id,
            embeddings_provider=_Embeddings(),
            require_sources=True,
        )


def test_course_preview_source_reference_accepts_legacy_document_name() -> None:
    from app.modules.courses.schemas import CoursePreviewSourceReference

    reference = CoursePreviewSourceReference.model_validate(
        {"document": "legacy-source.pdf", "headings": ["Раздел"]}
    )

    assert reference.doc_id == ""
    assert reference.doc_name == "legacy-source.pdf"
    assert reference.headings == ["Раздел"]


@pytest.mark.asyncio
async def test_write_lesson_rejects_duplicate_context_windows(monkeypatch) -> None:
    from app.modules.ai.context_expansion import ContextWindow

    tenant_id = str(uuid4())

    class _ContextStore(_Store):
        async def query(self, **kwargs):
            return {
                "documents": [["Опорный фрагмент"]],
                "metadatas": [[{
                    "chunk_id": "chunk-4",
                    "doc_id": "doc-1",
                    "tenant_id": tenant_id,
                    "doc_name": "Правила.pdf",
                    "headings": "[]",
                    "embedding_provider": "provider-a",
                    "embedding_model": "model-a",
                    "embedding_revision": "rev-a",
                    "embedding_native_dimensions": 3,
                    "embedding_storage_dimensions": 4,
                    "embedding_content_sha256": "4" * 64,
                    "embedding_source_revision": f"document:{'a' * 64}",
                    "embedding_indexed_at": "2026-08-23T00:00:00+00:00",
                    "chunk_index": 4,
                }]],
                "distances": [[0.2]],
            }

        async def get_context_window(self, **kwargs):
            return []

    async def _duplicate_windows(store, hits, **kwargs):
        window = ContextWindow(
            anchor_chunk_id="chunk-4",
            doc_id="doc-1",
            tenant_id=tenant_id,
            source_revision=f"document:{'a' * 64}",
            anchor_chunk_index=4,
            chunks=(),
        )
        return [window, window]

    monkeypatch.setattr(
        "app.modules.ai.writer.expand_context_windows",
        _duplicate_windows,
    )
    with pytest.raises(ValueError, match="duplicate_context_window_anchor"):
        await write_lesson(
            llm=object(),
            store=_ContextStore(0.2),
            lesson_title="Раздел",
            objectives=[],
            module_title="Модуль",
            course_title="Курс",
            doc_ids=["doc-1"],
            tenant_id=tenant_id,
            embeddings_provider=_Embeddings(),
            require_sources=True,
        )


@pytest.mark.asyncio
async def test_write_course_passes_lessons_from_other_modules_as_siblings(
    monkeypatch,
) -> None:
    captured: dict[str, list[str]] = {}

    async def _capture_write_lesson(**kwargs):
        captured[kwargs["lesson_title"]] = kwargs["sibling_lessons"]
        return LessonContent(
            title=kwargs["lesson_title"],
            objectives=kwargs["objectives"],
            content="# Content",
        )

    monkeypatch.setattr(
        "app.modules.ai.writer.write_lesson",
        _capture_write_lesson,
    )
    structure = CourseStructure(
        title="Правила",
        modules=[
            ArchitectModule(
                title="Начало",
                lessons=[
                    ArchitectLesson(
                        title="Общие положения",
                        objectives=[LearningObjective(text="Знать общие положения")],
                        source_doc_ids=["doc-1"],
                    )
                ],
            ),
            ArchitectModule(
                title="Завершение",
                lessons=[
                    ArchitectLesson(
                        title="Заключительные положения",
                        objectives=[LearningObjective(text="Применять заключительные положения")],
                        source_doc_ids=["doc-1"],
                    )
                ],
            ),
        ],
    )

    await write_course(
        llm=object(),
        store=object(),
        structure=structure,
        doc_ids=["doc-1"],
    )

    assert captured["Общие положения"] == ["Заключительные положения"]
    assert captured["Заключительные положения"] == ["Общие положения"]


@pytest.mark.asyncio
async def test_manual_edit_marks_grounded_lesson_for_source_review() -> None:
    lesson = Lesson(
        id=uuid4(),
        tenant_id=uuid4(),
        module_id=uuid4(),
        title="Исходный урок",
        content="Исходный текст",
        source_document_ids=[str(uuid4())],
        source_references=[{"doc_id": str(uuid4()), "doc_name": "source.pdf"}],
        source_validation_status="verified",
    )

    class _Result:
        def scalar_one_or_none(self):
            return lesson

    class _DB:
        refreshed = False

        async def execute(self, statement):
            return _Result()

        async def flush(self):
            return None

        async def refresh(self, instance):
            assert instance is lesson
            self.refreshed = True

    db = _DB()
    updated = await update_lesson(
        db,
        lesson.id,
        lesson.tenant_id,
        LessonUpdate(content="Текст после ручной правки"),
    )

    assert updated.source_validation_status == "needs_review"
    assert db.refreshed is True
