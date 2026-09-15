"""Run the production-shaped Evidence V2 seam without DB, queue, or deploy."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def _load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip().replace("_", "").isalnum():
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configure_local_embedding_route() -> None:
    url = os.environ.get("EMBEDDING_URL", "").rstrip("/")
    if not url:
        return
    if not url.endswith("/v1"):
        url += "/v1"
    # The locally reachable gx10-4 endpoint publishes the unnamespaced ID.
    # Production keeps replica-specific IDs in its own ordered route.
    model = os.environ.get("EMBEDDING_MODEL", "Qwen3-Embedding-8B")
    os.environ["ASUS_EMBEDDINGS_ENABLED"] = "true"
    for suffix in ("GX10_12_URL", "URL", "GX10_4_URL"):
        os.environ[f"ASUS_EMBEDDINGS_{suffix}"] = url
    for suffix in ("GX10_12_MODEL", "MODEL", "GX10_4_MODEL"):
        os.environ[f"ASUS_EMBEDDINGS_{suffix}"] = model


async def _xlsx_corpus(path: Path):
    from app.modules.ai.direct_source import (
        DirectSourceChunk,
        DirectSourceCorpus,
        DirectSourceDocument,
    )
    from app.modules.ai.ingestion import DocumentChunker, DocumentConverter

    digest = _sha256(path)
    doc_id = str(uuid5(NAMESPACE_URL, f"local-simulation:{digest}"))
    converter = DocumentConverter()
    converter.base_url = ""
    converted = await converter.convert(str(path))
    raw_chunks = DocumentChunker().chunk_markdown(converted["markdown"], doc_id, path.name)
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"direct:{doc_id}:{index}",
            doc_id=doc_id,
            doc_name=path.name,
            title=path.stem,
            headings=tuple(json.loads(chunk["metadata"].get("headings", "[]"))),
            text=chunk["text"],
            source_revision=f"document:{digest}",
            chunk_index=index,
            table_fragment=chunk["metadata"].get("worksheet_table_fragment"),
        )
        for index, chunk in enumerate(raw_chunks)
    )
    return DirectSourceCorpus(
        tenant_id="local-simulation",
        documents=(DirectSourceDocument(
            doc_id=doc_id,
            title=path.stem,
            filename=path.name,
            category="training_material",
            source_revision=f"document:{digest}",
            chunks=chunks,
        ),),
        total_chars=len(converted["markdown"]),
        total_chunks=len(chunks),
    )


async def _converted_pdf_corpus(path: Path):
    """Use the configured Docling route, matching the production upload path."""
    from app.modules.ai.direct_source import (
        DirectSourceChunk,
        DirectSourceCorpus,
        DirectSourceDocument,
    )
    from app.modules.ai.ingestion import DocumentChunker, DocumentConverter

    digest = _sha256(path)
    doc_id = str(uuid5(NAMESPACE_URL, f"local-simulation:{digest}"))
    converted = await DocumentConverter().convert(str(path))
    markdown = str(converted.get("markdown") or "")
    engine = str((converted.get("metadata") or {}).get("engine") or "")
    if not markdown.strip() or engine == "pypdf":
        raise RuntimeError("configured Docling route did not return OCR text")
    raw_chunks = DocumentChunker().chunk_markdown(markdown, doc_id, path.name)
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"direct:{doc_id}:{index}",
            doc_id=doc_id,
            doc_name=path.name,
            title=path.stem,
            headings=tuple(json.loads(chunk["metadata"].get("headings", "[]"))),
            text=chunk["text"],
            source_revision=f"document:{digest}",
            chunk_index=index,
        )
        for index, chunk in enumerate(raw_chunks)
    )
    return DirectSourceCorpus(
        tenant_id="local-simulation",
        documents=(DirectSourceDocument(
            doc_id=doc_id,
            title=path.stem,
            filename=path.name,
            category="training_material",
            source_revision=f"document:{digest}",
            chunks=chunks,
        ),),
        total_chars=len(markdown),
        total_chunks=len(chunks),
    )


def _pdf_corpus(path: Path, ocr_json: Path):
    from app.modules.ai.direct_source import (
        DirectSourceChunk,
        DirectSourceCorpus,
        DirectSourceDocument,
    )
    from app.modules.ai.evidence_engine.adapters import narrative_document_from_pages

    digest = _sha256(path)
    doc_id = str(uuid5(NAMESPACE_URL, f"local-simulation:{digest}"))
    payload = json.loads(ocr_json.read_text(encoding="utf-8"))
    source = narrative_document_from_pages(path=path, pages=payload["pages"])
    chunks = []
    index = 0
    for section in source.sections:
        for fact in section.facts:
            chunks.append(DirectSourceChunk(
                chunk_id=f"direct:{doc_id}:{index}",
                doc_id=doc_id,
                doc_name=path.name,
                title=path.stem,
                headings=(section.title,),
                text=fact.value,
                source_revision=f"document:{digest}",
                chunk_index=index,
            ))
            index += 1
    return DirectSourceCorpus(
        tenant_id="local-simulation",
        documents=(DirectSourceDocument(
            doc_id=doc_id,
            title=path.stem,
            filename=path.name,
            category="training_material",
            source_revision=f"document:{digest}",
            chunks=tuple(chunks),
        ),),
        total_chars=sum(len(chunk.text) for chunk in chunks),
        total_chunks=len(chunks),
    )


def _render(output) -> str:
    result = output.result
    by_lesson = {}
    for question in result.realized_assessment.questions:
        by_lesson.setdefault(question.lesson_id, []).append(question)
    lines = [f"# {result.realized_course.title}", "", result.realized_course.description, ""]
    current_module = ""
    for lesson in result.realized_course.lessons:
        if lesson.module_title != current_module:
            current_module = lesson.module_title
            lines.extend([f"# Модуль: {current_module}", ""])
        lines.extend([f"## {lesson.title}", "", lesson.content, "", "### Тест", ""])
        for question in by_lesson.get(lesson.lesson_id, []):
            lines.append(f"- {question.prompt}")
            lines.extend(f"  - {option}" for option in question.options)
            lines.append(f"  - Правильный ответ: {question.correct_answer}")
        lines.append("")
    return "\n".join(lines)


async def _run(label: str, corpus, output_dir: Path, runs: int) -> list[dict]:
    from app.modules.ai.evidence_engine.application import generate_evidence_course
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.llm_client import ResilientEmbeddingsClient, ResilientLLMClient

    rows = []
    for run_number in range(1, runs + 1):
        llm = await ResilientLLMClient.from_settings_async()
        embeddings = await ResilientEmbeddingsClient.from_settings_async()
        events = []

        async def progress(
            stage: str,
            current: int,
            total: int,
            provider: str | None,
            attempt: int | None,
        ) -> None:
            events.append({
                "stage": stage,
                "current": current,
                "total": total,
                "provider": provider,
                "attempt": attempt,
                "at": time.time(),
            })
            provider_suffix = f" provider={provider}" if provider else ""
            attempt_suffix = f" attempt={attempt}" if attempt else ""
            print(
                f"[{label}/run-{run_number}] {stage} {current}/{total}{provider_suffix}{attempt_suffix}",
                flush=True,
            )

        started = time.perf_counter()
        output = await generate_evidence_course(
            corpus,
            intent=CourseIntent(
                purpose="Подготовить сотрудника к правильному применению сведений источника без домыслов.",
                audience="Сотрудник организации, применяющий материал в ежедневной работе.",
            ),
            generation_client=llm,
            embedding_client=embeddings,
            progress_callback=progress,
        )
        wall = time.perf_counter() - started
        result = output.result
        run_dir = output_dir / label / f"run-{run_number}"
        run_dir.mkdir(parents=True, exist_ok=True)
        rendered = _render(output)
        (run_dir / "course-and-assessment.md").write_text(rendered, encoding="utf-8")
        metrics = {
            "wall_seconds": round(wall, 3),
            "stage_seconds": {item.stage: round(item.seconds, 3) for item in result.timings},
            "lessons": len(result.realized_course.lessons),
            "questions": len(result.realized_assessment.questions),
            "publishable": result.publishability.publishable,
            "reasons": list(result.publishability.reasons),
            "embedding_model": result.embedding_model,
            "embedding_degraded": result.embedding_degraded,
            "embedding_error": result.embedding_error,
            "chat_model": result.chat_model,
            "quality_status": (
                "degraded_needs_review"
                if result.embedding_degraded or result.deterministic_fallback_count > 0
                else "validated_draft"
            ),
            "provider_fallback_count": result.provider_fallback_count,
            "deterministic_fallback_count": result.deterministic_fallback_count,
            "chat_attempt_count": result.chat_attempt_count,
            "validation_errors": list(dict.fromkeys(result.validation_errors))[:50],
            "semantic_fingerprint": result.evidence_result.semantic_fingerprint,
            "output_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            "events": events,
        }
        (run_dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows.append(metrics)
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--excel", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--ocr-json", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--source", choices=("both", "excel", "pdf"), default="both")
    args = parser.parse_args()
    _load_env(args.env_file)
    _configure_local_embedding_route()
    summary = {}
    if args.source in {"both", "excel"}:
        excel = await _xlsx_corpus(args.excel)
        summary["excel"] = await _run("plus-excel", excel, args.output_dir, args.runs)
    if args.source in {"both", "pdf"}:
        pdf = (
            _pdf_corpus(args.pdf, args.ocr_json)
            if args.ocr_json is not None
            else await _converted_pdf_corpus(args.pdf)
        )
        summary["pdf"] = await _run("lombard-pdf", pdf, args.output_dir, args.runs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"complete": True, "runs": args.runs}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
