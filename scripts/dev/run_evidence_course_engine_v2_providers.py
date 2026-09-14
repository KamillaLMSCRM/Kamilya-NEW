"""Run production-like V2 simulations against Qwen embeddings and DeepSeek.

The script is deliberately local-only. It reads secrets process-locally, never
prints them, does not use the application database, and does not publish output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.modules.ai.evidence_engine import CourseIntent, ProviderBackedEvidenceEngine  # noqa: E402
from app.modules.ai.evidence_engine.adapters import narrative_document_from_pages  # noqa: E402
from app.modules.ai.evidence_engine.provider_models import (  # noqa: E402
    ChatCompletion,
    ProviderBackedResult,
)
from app.modules.ai.evidence_engine.providers import (  # noqa: E402
    DeepSeekJsonProvider,
    OpenAICompatibleEmbeddingProvider,
    discover_models,
)


def _load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "").isalnum():
            os.environ[key] = value.strip().strip('"').strip("'")


def _with_v1(url: str) -> str:
    resolved = url.rstrip("/")
    return resolved if resolved.endswith("/v1") else f"{resolved}/v1"


class _ProgressChat:
    def __init__(self, delegate: DeepSeekJsonProvider, *, label: str, total: int) -> None:
        self._delegate = delegate
        self._label = label
        self._total = total
        self._current = 0

    def complete_json(self, request: dict[str, Any]) -> ChatCompletion:
        self._current += 1
        started = time.perf_counter()
        try:
            return self._delegate.complete_json(request)
        finally:
            elapsed = time.perf_counter() - started
            title = str(request.get("lesson_title") or "")[:55]
            print(
                f"[{self._label}] DeepSeek call {self._current} (max {self._total}): "
                f"{elapsed:.2f}s — {title}",
                flush=True,
            )


def _course_markdown(result: ProviderBackedResult) -> str:
    questions: dict[str, list[Any]] = {}
    for question in result.realized_assessment.questions:
        questions.setdefault(question.lesson_id, []).append(question)
    lines = [f"# {result.realized_course.title}", "", result.realized_course.description, ""]
    module = ""
    for lesson in result.realized_course.lessons:
        if lesson.module_title != module:
            module = lesson.module_title
            lines.extend([f"# Модуль: {module}", ""])
        lines.extend(
            [
                f"## {lesson.title}",
                "",
                f"**Цель:** {lesson.objective}",
                f"**Расчётное время:** {lesson.duration_minutes} мин.",
                "",
                lesson.content,
                "",
                "### Проверка",
                "",
            ]
        )
        lesson_questions = questions.get(lesson.lesson_id, [])
        if not lesson_questions:
            lines.append("Проверочный вопрос не сформирован: безопасного seed-вопроса нет.")
        for index, question in enumerate(lesson_questions, start=1):
            lines.append(f"{index}. {question.prompt}")
            for option in question.options:
                lines.append(f"   - {option}")
            lines.append(f"   - **Правильный ответ:** {question.correct_answer}")
            lines.append(f"   - **Объяснение:** {question.explanation}")
        lines.append("")
    return "\n".join(lines)


def _metrics(result: ProviderBackedResult, wall_seconds: float, output_text: str) -> dict[str, Any]:
    recall_values = [measurement.recall_at_k for measurement in result.retrieval]
    return {
        "source_sha256": result.evidence_result.document_plan.source_sha256,
        "wall_seconds": wall_seconds,
        "stage_seconds": {item.stage: item.seconds for item in result.timings},
        "embedding_model": result.embedding_model,
        "embedding_dimension": result.embedding_dimension,
        "chat_model": result.chat_model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "modules": len({lesson.module_title for lesson in result.realized_course.lessons}),
        "lessons": len(result.realized_course.lessons),
        "questions": len(result.realized_assessment.questions),
        "provider_fallbacks": result.provider_fallback_count,
        "chat_attempts": result.chat_attempt_count,
        "validation_errors": list(result.validation_errors),
        "retrieval_recall_mean": sum(recall_values) / len(recall_values) if recall_values else 0.0,
        "retrieval_recall_min": min(recall_values, default=0.0),
        "semantic_fingerprint": result.evidence_result.semantic_fingerprint,
        "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
    }


def _run_source(
    *,
    label: str,
    run_number: int,
    output_dir: Path,
    embedding_url: str,
    embedding_model: str,
    deepseek_url: str,
    deepseek_key: str,
    deepseek_model: str,
    generate,
    lesson_count: int,
) -> dict[str, Any]:
    embedding = OpenAICompatibleEmbeddingProvider(
        base_url=embedding_url,
        model=embedding_model,
        timeout_seconds=60,
        batch_size=64,
    )
    chat = _ProgressChat(
        DeepSeekJsonProvider(
            base_url=deepseek_url,
            api_key=deepseek_key,
            model=deepseek_model,
            timeout_seconds=90,
            max_tokens=5000,
        ),
        label=f"{label}/run-{run_number}",
        total=lesson_count * 2,
    )
    engine = ProviderBackedEvidenceEngine(embeddings=embedding, chat=chat, max_realizer_attempts=2)
    started = time.perf_counter()
    result = generate(engine, run_number)
    wall_seconds = time.perf_counter() - started
    run_dir = output_dir / label / f"run-{run_number}"
    run_dir.mkdir(parents=True, exist_ok=True)
    output_text = _course_markdown(result)
    (run_dir / "course-and-assessment.md").write_text(output_text, encoding="utf-8")
    (run_dir / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics = _metrics(result, wall_seconds, output_text)
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "completed": f"{label}/run-{run_number}",
                "wall_seconds": round(wall_seconds, 3),
                "fallbacks": metrics["provider_fallbacks"],
                "prompt_tokens": metrics["prompt_tokens"],
                "completion_tokens": metrics["completion_tokens"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return metrics


def _report(output: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Evidence Course Engine V2 — provider-backed simulation",
        "",
        "Статус: локальная production-like симуляция. DEV, production, БД и текущий движок не изменялись.",
        "",
        "## Провайдеры",
        "",
        f"- Embedding: `{summary['providers']['embedding_model']}` через `{summary['providers']['embedding_url']}`.",
        f"- Generation: `{summary['providers']['deepseek_model']}` через `{summary['providers']['deepseek_url']}`.",
        "- Документы индексировались без префикса; префикс Qwen добавлялся только к поисковым запросам.",
        "- Значения ключей в артефакты и логи не записывались.",
        "",
        "## Измерения",
        "",
        "| Источник | Прогонов | Уроки | Вопросы | DeepSeek calls | Среднее время | Prompt tokens | Completion tokens | Fallback | Mean recall@k | Min recall@k |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, runs in summary["results"].items():
        first = runs[0]
        average_seconds = sum(item["wall_seconds"] for item in runs) / len(runs)
        lines.append(
            f"| {label} | {len(runs)} | {first['lessons']} | {first['questions']} | "
            f"{sum(item['chat_attempts'] for item in runs)} | "
            f"{average_seconds:.2f} с | {sum(item['prompt_tokens'] for item in runs)} | "
            f"{sum(item['completion_tokens'] for item in runs)} | "
            f"{sum(item['provider_fallbacks'] for item in runs)} | "
            f"{sum(item['retrieval_recall_mean'] for item in runs) / len(runs):.1%} | "
            f"{min(item['retrieval_recall_min'] for item in runs):.1%} |"
        )
    lines.extend(
        [
            "",
            "## Повторяемость",
            "",
        ]
    )
    for label, runs in summary["results"].items():
        semantic = len({item["semantic_fingerprint"] for item in runs})
        rendered = len({item["output_sha256"] for item in runs})
        lines.append(
            f"- {label}: доказательных планов — {semantic}; уникальных модельных текстов — {rendered}."
        )
    lines.extend(
        [
            "",
            "## Примечание к решению",
            "",
            "Доказательный план должен оставаться стабильным между прогонами. Различия модельной прозы "
            "допустимы только при одинаковом наборе фактов, ответов и вариантов. Fallback означает, что "
            "DeepSeek не прошёл структурный контракт даже после повторной попытки; такой урок сохранён "
            "из детерминированного V2-черновика и не считается модельно принятым.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--excel", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--ocr-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 2:
        raise ValueError("At least two provider-backed runs are required")
    _load_env(args.env_file)
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    deepseek_url = _with_v1(os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    if not deepseek_key:
        raise RuntimeError("DEEPSEEK_API_KEY is missing")
    deepseek_models = discover_models(base_url=deepseek_url, api_key=deepseek_key)
    preferred_chat = os.environ.get("DEEPSEEK_MODEL", "")
    deepseek_model = preferred_chat if preferred_chat in deepseek_models else "deepseek-flash"
    if deepseek_model not in deepseek_models:
        raise RuntimeError("No supported DeepSeek model discovered")

    embedding_url = _with_v1(os.environ["EMBEDDING_URL"])
    embedding_models = discover_models(base_url=embedding_url)
    if not embedding_models:
        raise RuntimeError("No embedding model discovered")
    embedding_model = embedding_models[0]

    ocr = json.loads(args.ocr_json.read_text(encoding="utf-8"))
    narrative = narrative_document_from_pages(path=args.pdf, pages=ocr["pages"])
    intent = CourseIntent(
        purpose="Подготовить сотрудника к правильному применению сведений источника без домыслов.",
        audience="Сотрудник организации, который применяет материал в ежедневной работе.",
    )
    # Count once without providers so progress remains truthful and no model call is duplicated.
    from app.modules.ai.evidence_engine import EvidenceCourseEngine  # noqa: PLC0415

    base_engine = EvidenceCourseEngine()
    excel_lesson_count = len(base_engine.generate(args.excel, intent=intent).course.lessons)
    pdf_lesson_count = len(base_engine.generate_from_document(narrative, intent=intent).course.lessons)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict[str, Any]]] = {"Плюс Excel": [], "Ломбард PDF": []}
    for run_number in range(1, args.runs + 1):
        results["Плюс Excel"].append(
            _run_source(
                label="plus-excel",
                run_number=run_number,
                output_dir=args.output_dir,
                embedding_url=embedding_url,
                embedding_model=embedding_model,
                deepseek_url=deepseek_url,
                deepseek_key=deepseek_key,
                deepseek_model=deepseek_model,
                generate=lambda engine, seed: engine.generate(
                    args.excel,
                    intent=intent,
                    simulation_seed=seed,
                ),
                lesson_count=excel_lesson_count,
            )
        )
        results["Ломбард PDF"].append(
            _run_source(
                label="lombard-pdf",
                run_number=run_number,
                output_dir=args.output_dir,
                embedding_url=embedding_url,
                embedding_model=embedding_model,
                deepseek_url=deepseek_url,
                deepseek_key=deepseek_key,
                deepseek_model=deepseek_model,
                generate=lambda engine, seed: engine.generate_from_document(
                    narrative,
                    intent=intent,
                    simulation_seed=seed,
                ),
                lesson_count=pdf_lesson_count,
            )
        )
    summary = {
        "providers": {
            "embedding_url": embedding_url,
            "embedding_model": embedding_model,
            "deepseek_url": deepseek_url,
            "deepseek_model": deepseek_model,
        },
        "runs": args.runs,
        "results": results,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _report(args.output_dir / "REPORT_RU.md", summary)
    print(json.dumps({"complete": True, "runs": args.runs}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
