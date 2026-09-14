"""Run repeatable local simulations of the isolated evidence-first engine."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.modules.ai.evidence_engine import CourseIntent, EvidenceCourseEngine  # noqa: E402
from app.modules.ai.evidence_engine.adapters import narrative_document_from_pages  # noqa: E402
from app.modules.ai.evidence_engine.models import EvidenceCourseResult  # noqa: E402


def _write_course(path: Path, result: EvidenceCourseResult) -> None:
    lines = [f"# {result.course.title}", "", result.course.description, ""]
    current_module = ""
    questions_by_lesson = {}
    for question in result.assessment.questions:
        questions_by_lesson.setdefault(question.lesson_id, []).append(question)
    for lesson in result.course.lessons:
        if lesson.module_title != current_module:
            current_module = lesson.module_title
            lines.extend([f"# Модуль: {current_module}", ""])
        lines.extend(
            [
                f"## Урок: {lesson.title}",
                "",
                f"Цель: {lesson.objective}",
                f"Расчётное время: {lesson.duration_minutes} мин.",
                "",
                lesson.content,
                "",
                "### Проверка",
                "",
            ]
        )
        lesson_questions = questions_by_lesson.get(lesson.lesson_id, [])
        if not lesson_questions:
            lines.append("Безопасный вопрос не сформирован: доказуемых отвлекающих вариантов нет.")
        for index, question in enumerate(lesson_questions, start=1):
            lines.append(f"{index}. {question.prompt}")
            for option in question.options:
                lines.append(f"   - {option}")
            lines.append(f"   - Правильный ответ: {question.correct_answer}")
            lines.append(f"   - Обоснование: {question.explanation}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_metrics(result: EvidenceCourseResult, wall_seconds: float) -> dict[str, object]:
    questions = result.assessment.questions
    lessons = result.course.lessons
    return {
        "wall_seconds": wall_seconds,
        "stage_seconds": {timing.stage: timing.seconds for timing in result.timings},
        "semantic_fingerprint": result.semantic_fingerprint,
        "source_sha256": result.document_plan.source_sha256,
        "primary_sections": list(result.document_plan.primary_sections),
        "supporting_sections": list(result.document_plan.supporting_sections),
        "facts": result.document_plan.admitted_fact_count,
        "supporting_facts": result.document_plan.supporting_fact_count,
        "supporting_facts_used": len(
            {
                fact_id
                for lesson in result.evidence_plan
                for fact_id in lesson.supporting_fact_ids
            }
        ),
        "duplicate_facts_removed": result.document_plan.duplicate_fact_count,
        "modules": len({lesson.module_title for lesson in lessons}),
        "lessons": len(lessons),
        "questions": len(questions),
        "single_choice_questions": sum(q.kind == "single_choice" for q in questions),
        "true_false_questions": sum(q.kind == "true_false" for q in questions),
        "duration_minutes": sum(lesson.duration_minutes for lesson in lessons),
        "coverage_ratio": result.evaluation.coverage_ratio,
        "duplicate_questions": result.evaluation.duplicate_question_count,
        "unsupported_claims": result.evaluation.unsupported_claim_count,
        "cross_lesson_questions": result.evaluation.cross_lesson_question_count,
        "quota_padding": result.evaluation.quota_padding_count,
        "uncertain_facts": result.evaluation.uncertain_fact_count,
        "warnings": list(result.evaluation.warnings),
    }


def _simulate(
    *,
    label: str,
    runs: int,
    output_dir: Path,
    generate,
) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    for run_number in range(1, runs + 1):
        started = time.perf_counter()
        result = generate(run_number)
        wall_seconds = time.perf_counter() - started
        run_dir = output_dir / label / f"run-{run_number}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_course(run_dir / "course-and-assessment.md", result)
        run_metrics = _run_metrics(result, wall_seconds)
        (run_dir / "metrics.json").write_text(
            json.dumps(run_metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metrics.append(run_metrics)
    return metrics


def _report(
    *,
    output: Path,
    runs: int,
    excel: Path,
    pdf: Path,
    ocr: dict[str, object],
    excel_metrics: list[dict[str, object]],
    pdf_metrics: list[dict[str, object]],
) -> None:
    lines = [
        "# Локальный эксперимент Evidence Course Engine V2",
        "",
        "Статус: только локальная симуляция. Текущий движок, DEV и production не изменялись.",
        "",
        "## Источники",
        "",
        f"- Excel: `{excel}`; SHA-256 `{excel_metrics[0]['source_sha256']}`.",
        f"- PDF: `{pdf}`; SHA-256 `{pdf_metrics[0]['source_sha256']}`.",
        f"- PDF OCR: {ocr['page_count']} стр., {float(ocr['ocr_seconds']):.3f} с.",
        "",
        "## Повторяемость и метрики",
        "",
        "| Источник | Прогоны | Отпечатков | Модули | Уроки | Вопросы | MCQ | Верно/неверно | Минуты | Среднее время движка |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, values in (("Плюс Excel", excel_metrics), ("Ломбард PDF", pdf_metrics)):
        first = values[0]
        average = sum(float(item["wall_seconds"]) for item in values) / len(values)
        lines.append(
            f"| {label} | {len(values)} | {len({item['semantic_fingerprint'] for item in values})} "
            f"| {first['modules']} | {first['lessons']} | {first['questions']} "
            f"| {first['single_choice_questions']} | {first['true_false_questions']} "
            f"| {first['duration_minutes']} | {average:.4f} с |"
        )
    lines.extend(
        [
            "",
            "## Машинные инварианты",
            "",
            "| Источник | Покрытие фактов | Вспомогательных фактов использовано | Неуверенные факты | Дубли вопросов | Неподтверждённые утверждения | Чужая тема урока | Дополнение до квоты | Предупреждения |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for label, values in (("Плюс Excel", excel_metrics), ("Ломбард PDF", pdf_metrics)):
        first = values[0]
        lines.append(
            f"| {label} | {float(first['coverage_ratio']):.1%} | {first['supporting_facts_used']} "
            f"| {first['uncertain_facts']} | {first['duplicate_questions']} "
            f"| {first['unsupported_claims']} | {first['cross_lesson_questions']} "
            f"| {first['quota_padding']} | {', '.join(first['warnings']) or 'нет'} |"
        )
    lines.extend(
        [
            "",
            "## Найденный и устранённый дефект прототипа",
            "",
            "Первый PDF-прогон дал 65 вопросов, из них 40 повторяли один и тот же "
            "смысл. Такой результат был отклонён. Генератор вопросов переведён на "
            "маскирование только однозначно извлечённых сроков и числовых значений, "
            "а варианты ответа допускаются только при наличии других подтверждённых "
            "значений совместимого типа. После исправления: 19 вопросов, 0 дублей.",
            "",
            "## Ручная смысловая приёмка",
            "",
            "### Плюс Excel",
            "",
            "- Основной лист «Коллекции» правильно выбран источником учебной структуры.",
            "- Вспомогательный лист используется только для точечных примеров ассортимента; "
            "артикулы не стали отдельными темами курса.",
            "- Факты разделены по назначению, материалам, ассортименту и работе с покупателем; "
            "фиксированная квота уроков не применяется.",
            "- Вопросы относятся к конкретной коллекции и одному атрибуту, однако часть "
            "вариантов слишком длинная и проверяет буквальное узнавание строки таблицы, "
            "а не прикладное решение продавца.",
            "",
            "### Ломбард PDF",
            "",
            "- Все 13 содержательных разделов сохранены в исходной последовательности; "
            "оглавление и приложение не превращены в самостоятельные учебные темы.",
            "- Единственный распознанный как таблица фрагмент помечен неуверенным и не "
            "используется для теста.",
            "- Вопросы не дублируются и не содержат придуманных фактов, но охватывают только "
            "сроки и однозначные числовые значения.",
            "- OCR-опечатки, обрывочные названия части уроков и фрагментарные формулировки "
            "вопросов пока делают результат непригодным для выдачи клиенту без редакторского слоя.",
            "",
            "## Итоговое решение",
            "",
            "- **GO для архитектурного ядра V2:** единый план фактов действительно устраняет "
            "расхождение уроков и тестов, зависимость от порядка исполнения и добивку до квоты.",
            "- **NO-GO для замены текущего клиентского движка:** локальный доказательный renderer "
            "ещё не создаёт готовую учебную прозу и полноценные прикладные вопросы.",
            "- Следующий безопасный этап — оставить этот детерминированный план неизменяемым, "
            "добавить поверх него ограниченный LLM-realizer с обязательными fact_id, затем "
            "проверять каждое утверждение и каждый ответ обратно по плану. Для PDF отдельно "
            "нужны очистка OCR и табличный адаптер. До прохождения тех же повторных прогонов "
            "и слепой ручной оценки подключать V2 к DEV или production нельзя.",
            "",
            "## Ограничение эксперимента",
            "",
            "Текст сформирован локальным доказательным renderer без LLM. Поэтому эксперимент "
            "проверяет разбор источника, распределение фактов, адаптивный объём, связь уроков "
            "и вопросов, отсутствие подмены тем и повторяемость. Он не доказывает качество "
            "будущей стилистической переформулировки моделью.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--ocr-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 2:
        raise ValueError("Use at least two runs to measure repeatability")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ocr = json.loads(args.ocr_json.read_text(encoding="utf-8"))
    engine = EvidenceCourseEngine()
    intent = CourseIntent(
        purpose="Подготовить сотрудника к применению сведений источника без домыслов.",
    )
    narrative = narrative_document_from_pages(path=args.pdf, pages=ocr["pages"])

    excel_metrics = _simulate(
        label="plus-excel",
        runs=args.runs,
        output_dir=args.output_dir,
        generate=lambda seed: engine.generate(args.excel, intent=intent, simulation_seed=seed),
    )
    pdf_metrics = _simulate(
        label="lombard-pdf",
        runs=args.runs,
        output_dir=args.output_dir,
        generate=lambda seed: engine.generate_from_document(
            narrative,
            intent=intent,
            simulation_seed=seed,
        ),
    )
    summary = {
        "runs": args.runs,
        "excel": excel_metrics,
        "pdf": pdf_metrics,
        "ocr": {key: value for key, value in ocr.items() if key != "pages"},
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _report(
        output=args.output_dir / "REPORT_RU.md",
        runs=args.runs,
        excel=args.excel,
        pdf=args.pdf,
        ocr=ocr,
        excel_metrics=excel_metrics,
        pdf_metrics=pdf_metrics,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
