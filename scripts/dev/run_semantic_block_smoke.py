"""Bounded local production-seam replay; synthetic input, no DB or deployment."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from scripts.dev.run_evidence_course_application import _load_env, _render  # noqa: E402

SOURCES = {
    "synthetic-collections": (
        "# [Worksheet] Коллекции\n\n"
        "| Поле | Север | Берег | Линия |\n"
        "| --- | --- | --- | --- |\n"
        "| Назначение | Для спальни | Для прихожей | Для гостиной |\n"
        "| Материал фасада | МДФ | ЛДСП | Массив дерева |\n"
        "| Уход | Протирать мягкой сухой тканью; абразивные средства запрещены | "
        "Удалять загрязнения слегка влажной тканью и сразу вытирать насухо | "
        "Протирать сухой мягкой тканью; беречь от длительного воздействия воды |\n"
    ),
    "single-rule": (
        "Персональные данные передаются только по разрешённым каналам. "
        "Если клиент просит отправить их в личный мессенджер сотрудника, "
        "сотрудник отказывает в таком способе передачи и предлагает разрешённый канал. "
        "Срочность обращения не отменяет это правило."
    ),
    "independent-sections": (
        "1. Защита данных\n"
        "Персональные данные нельзя передавать в личные мессенджеры. "
        "Используется только разрешённый канал; срочность не является исключением.\n\n"
        "2. Первый ответ\n"
        "Первый ответ подтверждает приём обращения и сообщает следующий шаг. "
        "Окончательное решение в первом ответе не требуется.\n\n"
        "3. Эскалация\n"
        "Сотрудник продолжает отслеживать обращение после эскалации. "
        "Ответственность переходит только после явного подтверждения принимающей стороны."
    ),
}


def corpus_for(text: str, label: str):
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.ingestion import DocumentChunker

    digest = hashlib.sha256(text.encode()).hexdigest()
    doc_id = f"synthetic-{label}"
    filename = f"{label}.xlsx" if label == "synthetic-collections" else f"{label}.txt"
    chunks = tuple(DirectSourceChunk(
        chunk_id=f"{doc_id}:{i}", doc_id=doc_id, doc_name=filename,
        title="Рабочие правила", headings=tuple(json.loads(c["metadata"].get("headings", "[]"))),
        text=str(c["text"]), source_revision=f"document:{digest}", chunk_index=i,
        table_fragment=c["metadata"].get("worksheet_table_fragment"),
    ) for i, c in enumerate(DocumentChunker().chunk_markdown(text, doc_id, filename)))
    return DirectSourceCorpus(tenant_id="synthetic-local-only", documents=(DirectSourceDocument(
        doc_id=doc_id, title="Рабочие правила", filename=filename, category="training_material",
        source_revision=f"document:{digest}", chunks=chunks,
    ),), total_chars=sum(len(c.text) for c in chunks), total_chunks=len(chunks))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", choices=[*SOURCES, "all"], default="all")
    args = parser.parse_args()
    _load_env(args.env_file)
    from app.modules.ai.evidence_engine.application import generate_evidence_course
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.llm_client import ResilientEmbeddingsClient, ResilientLLMClient

    for label, text in SOURCES.items():
        if args.source not in {label, "all"}:
            continue
        client = await ResilientLLMClient.from_settings_async(temperature=0.2)
        embeddings = await ResilientEmbeddingsClient.from_settings_async()
        trace = []

        class SyntheticTrace:
            async def ainvoke_validated(self, messages, parser, **kwargs):
                def capture(raw):
                    # Explicit synthetic-only DEV harness, never production logs.
                    trace.append({"task": json.loads(messages[-1]["content"]).get("task", "writer"),
                                  "response": raw})
                    return parser(raw)
                return await client.ainvoke_validated(messages, parser=capture, **kwargs)

        started = time.perf_counter()
        output = await generate_evidence_course(corpus_for(text, label), intent=CourseIntent(),
            generation_client=SyntheticTrace(), embedding_client=embeddings)
        elapsed = round(time.perf_counter() - started, 3)
        folder = args.output_dir / label / "run-1"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "result.json").write_text(json.dumps(output.result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "synthetic-trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "course-and-assessment.md").write_text(_render(output), encoding="utf-8")
        metrics = {"source": label, "lessons": len(output.result.realized_course.lessons),
                   "questions": len(output.result.realized_assessment.questions), "seconds": elapsed,
                   "stages": {t.stage: round(t.seconds, 3) for t in output.result.timings},
                   "audit": output.result.assessment_review}
        (folder / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
