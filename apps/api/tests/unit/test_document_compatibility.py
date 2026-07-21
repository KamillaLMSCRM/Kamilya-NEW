from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ai.schemas import AIGenerateRequest
from app.modules.ai.source_analysis import (
    DocumentVectorProfile,
    analyze_profiles,
    cosine_similarity,
)
from app.modules.ai.writer import _retrieve_and_rerank, resolve_lesson_doc_ids, write_lesson
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
    result = analyze_profiles([
        _profile("Пожарная безопасность", [1.0, 0.0, 0.0]),
        _profile("Инструкция по эвакуации", [0.95, 0.1, 0.0]),
        _profile("План противопожарных действий", [0.9, 0.15, 0.0]),
    ])

    assert result.status == "compatible"
    assert result.requires_decision is False
    assert len(result.clusters) == 1


def test_unrelated_documents_are_split_and_require_decision() -> None:
    result = analyze_profiles([
        _profile("Пожарная безопасность", [1.0, 0.0, 0.0]),
        _profile("Бренд и реклама", [0.0, 1.0, 0.0]),
        _profile("Продажи", [0.0, 0.9, 0.1]),
    ])

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
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _Store:
    def __init__(self, distance: float):
        self.distance = distance

    async def query(self, **kwargs):
        return {
            "documents": [["Подтвержденный фрагмент"]],
            "metadatas": [[{
                "chunk_id": "chunk-1",
                "doc_id": "doc-1",
                "doc_name": "Инструкция.pdf",
                "headings": '["Раздел 1"]',
            }]],
            "distances": [[self.distance]],
        }


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
async def test_document_grounded_lesson_never_uses_general_knowledge_fallback() -> None:
    class _NeverCalledLLM:
        async def ainvoke(self, messages):
            raise AssertionError("LLM must not be called without relevant sources")

    with pytest.raises(ValueError, match="No relevant source fragments"):
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
        async def execute(self, statement):
            return _Result()

        async def flush(self):
            return None

    updated = await update_lesson(
        _DB(),
        lesson.id,
        lesson.tenant_id,
        LessonUpdate(content="Текст после ручной правки"),
    )

    assert updated.source_validation_status == "needs_review"
