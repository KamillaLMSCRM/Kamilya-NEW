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
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def _load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip().replace("_", "").isalnum():
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _validate_pdf_conversion_config(
    source: str,
    ocr_json: Path | None,
    converter_json: Path | None,
) -> None:
    """Fail before a live PDF run can silently fall back to a local parser."""
    if source not in {"both", "pdf"} or ocr_json is not None or converter_json is not None:
        return
    required = ("DOCLING_URL", "DOCLING_API_KEY")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("live_docling_not_configured:" + ",".join(missing))


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


def _dev_generation_config(policy: str):
    """Build one explicit DEV provider without DB routing or hidden failover."""
    from app.modules.ai.llm_client import LLMProviderConfig

    if policy == "asus-glm":
        return LLMProviderConfig(
            name="asus-glm",
            base_url="http://10.66.66.28:8888/v1",
            api_key="local-no-key",
            model="GLM-5.3-Flash-EXL3",
            timeout=600,
            max_retries=0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    if policy == "deepseek-flash":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("deepseek_api_key_required")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        return LLMProviderConfig(
            name="deepseek-flash-dev",
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model="deepseek-flash",
            timeout=180,
            max_retries=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
    raise ValueError(f"unsupported_dev_generation_policy:{policy}")


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


async def _converted_pdf_corpus(path: Path, converter_json: Path | None = None):
    """Use the configured Docling route, matching the production upload path."""
    from app.modules.ai.direct_source import (
        DirectSourceChunk,
        DirectSourceCorpus,
        DirectSourceDocument,
    )
    from app.modules.ai.ingestion import DocumentChunker, DocumentConverter

    digest = _sha256(path)
    doc_id = str(uuid5(NAMESPACE_URL, f"local-simulation:{digest}"))
    if converter_json is None:
        converted = await DocumentConverter().convert(str(path))
    else:
        capture = json.loads(converter_json.read_text(encoding="utf-8"))
        if (capture.get("capture_mode") != "deployed_application_converter"
                or capture.get("source_sha256") != digest
                or capture.get("source_bytes") != path.stat().st_size):
            raise ValueError("production_converter_capture_identity_mismatch")
        converted = capture["converted"]
        metadata = converted.get("metadata", {})
        if metadata.get("engine") != "docling" or metadata.get("fallback_used"):
            raise ValueError("production_docling_capture_required")
    markdown = str(converted.get("markdown") or "")
    if not markdown.strip():
        raise RuntimeError("configured document converter returned no PDF text")
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


def _filter_corpus_by_headings(corpus, heading_terms: tuple[str, ...]):
    """Build a bounded DEV corpus from production-converted heading regions.

    The source document and chunk identities stay unchanged so the generated
    evidence remains traceable to the exact production conversion.  This is a
    diagnostic cost/time bound, not a production document transformation.
    """
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument

    normalized_terms = tuple(
        term.strip().casefold() for term in heading_terms if term.strip()
    )
    if not normalized_terms:
        return corpus

    documents = []
    for document in corpus.documents:
        chunks = tuple(
            chunk
            for chunk in document.chunks
            if any(
                term in " ".join(chunk.headings).casefold()
                for term in normalized_terms
            )
        )
        if chunks:
            documents.append(DirectSourceDocument(
                doc_id=document.doc_id,
                title=document.title,
                filename=document.filename,
                category=document.category,
                source_revision=document.source_revision,
                chunks=chunks,
            ))
    if not documents:
        raise ValueError("no_source_chunks_match_heading_filter")
    return DirectSourceCorpus(
        tenant_id=corpus.tenant_id,
        documents=tuple(documents),
        total_chars=sum(len(chunk.text) for document in documents for chunk in document.chunks),
        total_chunks=sum(len(document.chunks) for document in documents),
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


async def _run(
    label: str,
    corpus,
    output_dir: Path,
    runs: int,
    *,
    generation_provider: str = "runtime",
    replay_trace: tuple[Path, ...] | None = None,
    max_provider_calls: int = 64,
) -> list[dict]:
    from app.modules.ai.evidence_engine.application import generate_evidence_course
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.llm_client import (
        ResilientEmbeddingsClient,
        ResilientLLMClient,
    )

    rows = []
    for run_number in range(1, runs + 1):
        # Match the production Evidence V2 route: this is source-grounded
        # realization, not creative writing.
        if generation_provider in {"asus-glm", "deepseek-flash"}:
            from scripts.dev.objective_alignment.run import Recorder
            from scripts.dev.run_axis_owned_assessment_smoke import _CapturedReplay

            llm = ResilientLLMClient(
                [_dev_generation_config(generation_provider)],
                temperature=0.2,
                max_tokens=8192,
            )
            recorder = Recorder(llm, max_calls=max_provider_calls, thinking=None)
            replay_router = (
                _CapturedReplay(replay_trace, fallback=recorder)
                if replay_trace is not None
                else None
            )
            generation_client = replay_router or recorder
        else:
            if replay_trace is not None:
                raise ValueError("replay_trace_requires_explicit_dev_provider")
            generation_client = await ResilientLLMClient.from_settings_async(temperature=0.2)
            recorder = None
            replay_router = None
        embeddings = await ResilientEmbeddingsClient.from_settings_async()
        events = []

        async def progress(
            stage: str,
            current: int,
            total: int,
            provider: str | None,
            attempt: int | None,
            _events: list[dict[str, object]] = events,
            _run_number: int = run_number,
            _label: str = label,
        ) -> None:
            _events.append({
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
                f"[{_label}/run-{_run_number}] {stage} {current}/{total}{provider_suffix}{attempt_suffix}",
                flush=True,
            )

        started = time.perf_counter()
        run_dir = output_dir / label / f"run-{run_number}"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            output = await generate_evidence_course(
                corpus,
                intent=CourseIntent(
                    purpose="Подготовить сотрудника к правильному применению сведений источника без домыслов.",
                    audience="Сотрудник организации, применяющий материал в ежедневной работе.",
                ),
                generation_client=generation_client,
                embedding_client=embeddings,
                progress_callback=progress,
            )
        except Exception as exc:
            failure = {
                "wall_seconds": round(time.perf_counter() - started, 3),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "events": events,
            }
            (run_dir / "failure.json").write_text(
                json.dumps(failure, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if recorder is not None:
                (run_dir / "trace.json").write_text(
                    json.dumps(recorder.trace, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (run_dir / "requests.json").write_text(
                    json.dumps(recorder.requests, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if replay_router is not None:
                (run_dir / "replay-routing.json").write_text(
                    json.dumps(replay_router.trace, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            raise
        wall = time.perf_counter() - started
        result = output.result
        rendered = _render(output)
        (run_dir / "course-and-assessment.md").write_text(rendered, encoding="utf-8")
        (run_dir / "result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if recorder is not None:
            (run_dir / "trace.json").write_text(
                json.dumps(recorder.trace, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "requests.json").write_text(
                json.dumps(recorder.requests, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if replay_router is not None:
            (run_dir / "replay-routing.json").write_text(
                json.dumps(replay_router.trace, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
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
            "generation_provider_policy": generation_provider,
            "quality_status": (
                "degraded_needs_review"
                if result.embedding_degraded or result.deterministic_fallback_count > 0
                else "assessment_needs_review" if (
                    not result.realized_assessment.questions
                    or result.assessment_review.get("terminal_status") == "review_required"
                    or result.assessment_review.get("coverage", {}).get("requires_review", False)
                )
                else "validated_draft"
            ),
            "assessment_review": result.assessment_review,
            "provider_fallback_count": result.provider_fallback_count,
            "deterministic_fallback_count": result.deterministic_fallback_count,
            "chat_attempt_count": result.chat_attempt_count,
            "recorded_provider_calls": recorder.calls if recorder is not None else None,
            "recorded_usage": recorder.usage if recorder is not None else None,
            "captured_replay_calls": (
                replay_router.captured_calls if replay_router is not None else None
            ),
            "live_replay_fallback_calls": (
                replay_router.live_fallback_calls if replay_router is not None else None
            ),
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
    parser.add_argument("--converter-json", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--source", choices=("both", "excel", "pdf"), default="both")
    parser.add_argument(
        "--generation-provider",
        choices=("runtime", "asus-glm", "deepseek-flash"),
        default="runtime",
        help=(
            "DEV-only explicit generator route; asus-glm and deepseek-flash "
            "disable runtime/provider fallback."
        ),
    )
    parser.add_argument(
        "--replay-trace",
        type=Path,
        action="append",
        help="Replay captured raw responses and call explicit ASUS GLM only for missing stages.",
    )
    parser.add_argument(
        "--include-heading",
        action="append",
        default=[],
        help=(
            "DEV-only repeatable case-insensitive heading fragment. Keep only production-"
            "converted chunks under matching headings before running generation."
        ),
    )
    parser.add_argument(
        "--max-provider-calls",
        type=int,
        default=64,
        help="DEV-only hard ceiling for recorded live generation calls.",
    )
    args = parser.parse_args()
    if args.ocr_json and args.converter_json:
        parser.error("Choose one conversion input")
    if args.max_provider_calls < 1:
        parser.error("--max-provider-calls must be positive")
    _load_env(args.env_file)
    try:
        _validate_pdf_conversion_config(
            args.source,
            args.ocr_json,
            args.converter_json,
        )
    except ValueError as exc:
        parser.error(str(exc))
    _configure_local_embedding_route()
    summary = {}
    if args.source in {"both", "excel"}:
        excel = await _xlsx_corpus(args.excel)
        summary["excel"] = await _run(
            "plus-excel",
            excel,
            args.output_dir,
            args.runs,
            generation_provider=args.generation_provider,
            replay_trace=tuple(args.replay_trace) if args.replay_trace else None,
            max_provider_calls=args.max_provider_calls,
        )
    if args.source in {"both", "pdf"}:
        pdf = (
            _pdf_corpus(args.pdf, args.ocr_json)
            if args.ocr_json is not None
            else await _converted_pdf_corpus(args.pdf, args.converter_json)
        )
        pdf = _filter_corpus_by_headings(pdf, tuple(args.include_heading))
        summary["pdf"] = await _run(
            "lombard-pdf",
            pdf,
            args.output_dir,
            args.runs,
            generation_provider=args.generation_provider,
            replay_trace=tuple(args.replay_trace) if args.replay_trace else None,
            max_provider_calls=args.max_provider_calls,
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"complete": True, "runs": args.runs}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
