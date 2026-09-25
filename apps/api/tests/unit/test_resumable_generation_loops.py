from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
    DirectSourceError,
    write_direct_course,
)
from app.modules.ai.lesson_quality import LESSON_QUALITY_POLICY_VERSION
from app.modules.ai.writer import write_course
from app.modules.ai.writer_schema import LessonContent


def _structure(count: int = 25):
    lessons = [
        SimpleNamespace(
            title=f"Lesson {index}",
            objectives=[SimpleNamespace(text=f"Objective {index}")],
            relevant_headings=[],
            source_doc_ids=["doc-1"],
        )
        for index in range(count)
    ]
    return SimpleNamespace(
        title="Resumable course",
        description="",
        modules=[SimpleNamespace(title="Module", lessons=lessons)],
    )


@pytest.mark.asyncio
async def test_writer_restores_completed_positions_and_calls_provider_only_for_missing(
    monkeypatch,
):
    structure = _structure()
    restored = {
        (0, index): LessonContent(
            title=f"Lesson {index}",
            content=f"restored-{index}",
        )
        for index in range(15)
    }
    provider_calls: list[int] = []
    completions: list[tuple[int, int]] = []
    claims: list[tuple[int, int]] = []

    async def fake_write_lesson(**kwargs):
        index = int(kwargs["lesson_title"].split()[-1])
        provider_calls.append(index)
        return LessonContent(title=kwargs["lesson_title"], content=f"generated-{index}")

    monkeypatch.setattr("app.modules.ai.writer.write_lesson", fake_write_lesson)

    result = await write_course(
        llm=object(),
        store=object(),
        structure=structure,
        doc_ids=["doc-1"],
        completed_lessons=restored,
        before_lesson_generate=lambda module, lesson: claims.append((module, lesson)),
        on_lesson_complete=lambda module, lesson, content: completions.append((module, lesson)),
    )

    assert provider_calls == list(range(15, 25))
    assert completions == [(0, index) for index in range(15, 25)]
    assert claims == [(0, index) for index in range(15, 25)]
    assert [lesson.content for lesson in result.modules[0].lessons] == [
        *(f"restored-{index}" for index in range(15)),
        *(f"generated-{index}" for index in range(15, 25)),
    ]
    restored_bytes = [
        json.dumps(restored[(0, index)].to_dict(), ensure_ascii=False, sort_keys=True).encode() for index in range(15)
    ]
    result_bytes = [
        json.dumps(lesson.to_dict(), ensure_ascii=False, sort_keys=True).encode()
        for lesson in result.modules[0].lessons[:15]
    ]
    assert result_bytes == restored_bytes


@pytest.mark.asyncio
async def test_direct_writer_skips_restored_positions_and_checkpoints_only_new_content():
    chunk = DirectSourceChunk(
        chunk_id="chunk-1",
        doc_id="doc-1",
        doc_name="source.txt",
        title="Source",
        headings=("Products",),
        text="Grounded product information.",
        source_revision="a" * 64,
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-1",
                title="Source",
                filename="source.txt",
                category="general",
                source_revision="a" * 64,
                chunks=(chunk,),
            ),
        ),
        total_chars=len(chunk.text),
        total_chunks=1,
    )
    structure = _structure(3)
    restored = {
        (0, 0): LessonContent(
            title="Lesson 0",
            content="Grounded product information.",
            source_chunks=["Grounded product information."],
            quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
        )
    }
    completions: list[tuple[int, int]] = []
    claims: list[tuple[int, int]] = []
    included: list[tuple[int, int]] = []

    class LLM:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            return SimpleNamespace(content="Grounded product information.")

    llm = LLM()
    result = await write_direct_course(
        llm,
        corpus,
        structure,
        completed_lessons=restored,
        completed_omissions={(0, 1): ("unsupported_relationship_claim",)},
        before_lesson_generate=lambda module, lesson: claims.append((module, lesson)),
        on_lesson_complete=lambda module, lesson, content: completions.append((module, lesson)),
        on_lesson_included=lambda module, lesson, content: included.append((module, lesson)),
    )

    assert llm.calls == 1
    assert completions == [(0, 2)]
    assert claims == [(0, 2)]
    assert included == [(0, 0), (0, 2)]
    assert [lesson.content for lesson in result.modules[0].lessons] == [
        "Grounded product information.",
        "Grounded product information.",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stale_policy_version",
    [
        "lesson-quality-v4",
        "lesson-quality-v5",
        "lesson-quality-v6",
        "lesson-quality-v7",
        "lesson-quality-v8",
        "lesson-quality-v9",
        "lesson-quality-v10",
        "lesson-quality-v11",
        "lesson-quality-v12",
        "lesson-quality-v13",
        "lesson-quality-v14",
        "lesson-quality-v15",
    ],
)
async def test_direct_writer_rejects_checkpoint_from_older_quality_policy(
    stale_policy_version: str,
) -> None:
    chunk = DirectSourceChunk(
        chunk_id="chunk-1",
        doc_id="doc-1",
        doc_name="source.txt",
        title="Source",
        headings=("Products",),
        text="Grounded product information.",
        source_revision="a" * 64,
        chunk_index=0,
    )
    corpus = DirectSourceCorpus(
        tenant_id="tenant-1",
        documents=(
            DirectSourceDocument(
                doc_id="doc-1",
                title="Source",
                filename="source.txt",
                category="general",
                source_revision="a" * 64,
                chunks=(chunk,),
            ),
        ),
        total_chars=len(chunk.text),
        total_chunks=1,
    )

    with pytest.raises(DirectSourceError, match="direct_source_checkpoint_quality_policy_stale"):
        await write_direct_course(
            SimpleNamespace(),
            corpus,
            _structure(1),
            completed_lessons={
                (0, 0): LessonContent(
                    title="Lesson 0",
                    content="legacy",
                    quality_policy_version=stale_policy_version,
                )
            },
        )
