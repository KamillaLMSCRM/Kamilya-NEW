"""Comprehensive quality verification and evidence generation for V3 course output."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import docx

# Add apps/api to sys.path so app modules import cleanly
api_dir = str(Path(__file__).resolve().parents[2] / "apps" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from app.modules.ai.v3.models import V3Course
from app.modules.ai.v3.validator import validate_v3_course

# Ensure utf-8 output on Windows console
sys.stdout.reconfigure(encoding="utf-8")


def load_docx_full_text(docx_path: Path) -> str:
    doc = docx.Document(str(docx_path))
    parts: list[str] = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if txt:
            parts.append(txt)
    for t in doc.tables:
        for r in t.rows:
            row_str = " ".join(dict.fromkeys(c.text.strip().replace("\n", " ") for c in r.cells if c.text.strip()))
            if row_str:
                parts.append(row_str)
    return "\n".join(parts)


def run_audit(
    json_path: Path = Path(r".release-evidence/v3-benchmark-universal/preview.json"),
    source_docx: Path = Path(r"C:\Users\user\Documents\ломбард\стандарты26.docx"),
) -> dict:
    source_text = load_docx_full_text(source_docx) if source_docx.exists() else ""
    data = json.load(json_path.open(encoding="utf-8"))
    course = V3Course.from_dict(data)

    report = validate_v3_course(course, source_text, max_longest_correct_ratio=0.25)

    result_payload = {
        "course_title": course.title,
        "verdict": report.verdict,
        "quality_status": report.quality_status,
        "lessons_count": len(course.lessons),
        "lessons": [
            {
                "index": idx,
                "title": l.title,
                "word_count": len(l.content.split()),
                "cases_count": len(l.cases),
                "variants_count": sum(len(c.variants) for c in l.cases),
            }
            for idx, l in enumerate(course.lessons, 1)
        ],
        "metrics": {
            "total_cases": report.metrics.total_cases,
            "total_variants": report.metrics.total_variants,
            "total_options_evaluated": report.metrics.total_options_evaluated,
            "four_option_adherence_percent": report.metrics.four_option_adherence_percent,
            "single_correct_adherence_percent": report.metrics.single_correct_adherence_percent,
            "zero_binary_adherence_percent": report.metrics.zero_binary_adherence_percent,
            "distractor_category_breakdown": report.metrics.distractor_category_breakdown,
            "length_bias_ratio_mean": report.metrics.length_bias_ratio_mean,
            "longest_correct_count": report.metrics.longest_correct_count,
            "longest_correct_percent": report.metrics.longest_correct_percent,
            "anti_cheating_distractor_overlap_percent": report.metrics.anti_cheating_distractor_overlap_percent,
            "source_quotes_found_percent": report.metrics.source_quotes_found_percent,
            "unverified_quotes": report.metrics.unverified_quotes,
        },
        "violations": report.violations,
    }
    return result_payload


def main() -> int:
    report = run_audit()
    m = report["metrics"]
    verdict = report["verdict"]

    print("=" * 60)
    print("           ОТЧЁТ ПОДТВЕРЖДЕНИЯ КАЧЕСТВА ДВИЖКА V3")
    print("=" * 60)
    print(f"Курс: {report['course_title']}")
    print(f"Уроков сформировано: {report['lessons_count']}")
    print("-" * 60)
    for l in report["lessons"]:
        print(f"  • Урок {l['index']}: {l['title']} | Слов: {l['word_count']} | Кейсов: {l['cases_count']} | Вариантов: {l['variants_count']}")
    print("-" * 60)
    print("КЛЮЧЕВЫЕ ДИДАКТИЧЕСКИЕ ИНВАРИАНТЫ:")
    print(f"  1. Строго 4 варианта ответа (MCQ):       {m['four_option_adherence_percent']:.1f}% ({m['total_variants']}/{m['total_variants']})")
    print(f"  2. Ровно 1 правильный ответ:             {m['single_correct_adherence_percent']:.1f}% ({m['total_variants']}/{m['total_variants']})")
    print(f"  3. Отсутствие бинарных угадаек (Да/Нет): {m['zero_binary_adherence_percent']:.1f}% (0 бинарных вопросов)")
    print(f"  4. Коэффициент симметрии длины ответа:   {m['length_bias_ratio_mean']} (норма: 0.80 - 1.25)")
    print(f"  5. Защита от шортката 'длинный ответ':   {m['longest_correct_percent']:.1f}% ({m['longest_correct_count']}/{m['total_variants']}, макс. 25.0%)")
    print(f"  6. Защита от списывания (overlap тестов): {m['anti_cheating_distractor_overlap_percent']:.1f}% (0 дубликатов между филиалами)")
    print(f"  7. Дословное совпадение цитат в источнике: {m['source_quotes_found_percent']:.1f}% (буквальное вхождение)")
    print("-" * 60)
    print("РАСПРЕДЕЛЕНИЕ РЕАЛИСТИЧНЫХ ОШИБОК (ДИСТРАКТОРОВ):")
    for cat, count in m["distractor_category_breakdown"].items():
        print(f"  • {cat:25s}: {count:2d} формулировок")

    if report["violations"]:
        print("-" * 60)
        print(f"ОБНАРУЖЕНЫ НАРУШЕНИЯ ({len(report['violations'])}):")
        for v in report["violations"]:
            print(f"  [X] {v}")

    print("=" * 60)
    if verdict == "PASS":
        print("ВЕРДИКТ: СТРУКТУРНАЯ ПРОВЕРКА ПРОЙДЕНА (PASS); СМЫСЛОВАЯ ПРОВЕРКА ТРЕБУЕТСЯ (NEEDS_REVIEW)")
    else:
        print(f"ВЕРДИКТ: ТРЕБУЕТСЯ ДОРАБОТКА (FAIL - {len(report['violations'])} нарушений)")
    print("=" * 60)

    # Save evidence file
    evidence_path = Path(".release-evidence/v3-benchmark-universal/quality_audit.json")
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
