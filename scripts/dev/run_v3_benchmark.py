"""Benchmark runner demonstrating end-to-end V3 course and scenario generation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import docx

from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import V3Course, V3Lesson
from scripts.dev.generation_quality_api import QualityAPISession


def extract_docx_full_text(docx_path: Path) -> str:
    """Extract complete text and tables preserving document structure."""
    doc = docx.Document(str(docx_path))
    parts: list[str] = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if txt:
            parts.append(txt)
    for i, tbl in enumerate(doc.tables, 1):
        parts.append(f"\n--- ТАБЛИЦА {i} ---")
        for r in tbl.rows:
            row_str = " | ".join(dict.fromkeys(c.text.strip().replace("\n", " ") for c in r.cells if c.text.strip()))
            if row_str:
                parts.append(row_str)
    return "\n".join(parts)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run V3 Generation Benchmark")
    parser.add_argument("--source", type=Path, default=Path(r"C:\Users\user\Documents\ломбард\стандарты26.docx"))
    parser.add_argument("--key-file", type=Path, default=Path(r".release-evidence/generation-quality-private/openai-key.dpapi"))
    parser.add_argument("--budget", type=Path, default=Path(r".release-evidence/generation-quality-private/budget.json"))
    parser.add_argument("--output", type=Path, default=Path(r".release-evidence/v3-benchmark/preview.md"))
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = args.source.read_bytes()
    doc_sha = hashlib.sha256(raw_bytes).hexdigest()
    full_text = extract_docx_full_text(args.source)

    client = QualityAPISession(key_file=args.key_file, ledger=args.budget, model="gpt-6-luna", output_tokens=16384)

    try:
        async def llm_invoker(messages: list[dict[str, str]], response_format: dict | None = None):
            res = await client.ainvoke_validated(messages, parser=lambda raw: json.loads(raw), response_format=response_format)
            return res.value

        pipeline = V3GenerationPipeline(llm_invoker)

        print("Шаг 1: Извлечение структурированной Карты Регламента (Rule Model)...")
        rule_model = await pipeline.extract_rule_model(
            document_title="Стандарты согласования при выдаче микрокредитов ТОО «Ломбард Сандық»",
            document_text=full_text,
            document_sha256=doc_sha,
        )
        print(f"  Извлечено правил: {len(rule_model.rules)}")

        # Group rules by curriculum lessons
        # Lesson 1: Limits Table 1
        # Lesson 2: Approval Table 2 Category 1
        # Lesson 3: Approval Table 2 Category 2
        # Lesson 4: Restrictions & Joint Liability
        groups = {
            "Лимиты выдачи микрокредитов (Таблица 1)": [r for r in rule_model.rules if "лимит" in r.statement.lower() or "таблица 1" in r.section.lower() or "700" in r.statement],
            "Порядок согласования: I категория (Таблица 2)": [r for r in rule_model.rules if "i категор" in r.title.lower() or "i категор" in r.statement.lower()],
            "Порядок согласования: II категория (Таблица 2)": [r for r in rule_model.rules if "ii категор" in r.title.lower() or "ii категор" in r.statement.lower()],
            "Запреты, пролонгация и материальная ответственность": [r for r in rule_model.rules if any(k in r.statement.lower() for k in ["пролонгац", "ответственност", "стоп-лист", "ущерб", "акт"])],
        }

        generated_lessons: list[V3Lesson] = []
        lessons_summary = ""

        for theme, rules in groups.items():
            if not rules:
                continue
            print(f"\nГенерация Обобщенного Урока и Банка Кейсов: «{theme}» ({len(rules)} правил)...")
            lesson = await pipeline.generate_lesson_with_scenarios(
                module_title="Стандарты выдачи микрокредитов",
                lesson_theme=theme,
                rules=rules,
                existing_lessons_summary=lessons_summary,
            )
            print(f"  Создан урок: «{lesson.title}»")
            print(f"  Кейсов: {len(lesson.cases)} | Вопросов в пуле: {len(lesson.questions)}")
            generated_lessons.append(lesson)
            lessons_summary += f"\n- {lesson.title}: {lesson.content[:150]}..."

        course = V3Course(
            course_id=f"course-v3-{doc_sha[:12]}",
            title="Стандарты согласования при выдаче микрокредитов ТОО «Ломбард Сандық»",
            document_sha256=doc_sha,
            lessons=tuple(generated_lessons),
        )

        # Save Markdown preview
        preview_md: list[str] = [
            f"# {course.title}",
            f"**Документ SHA256:** `{doc_sha}` | **Архитектура:** `V3 Universal Co-Gen & Multi-Variant Assessment Bank`",
            "",
            "> [!TIP]",
            "> **Преимущества перед конкурентами:**",
            "> 1. **Обобщенные уроки:** Текст урока обучает системному механизму и алгоритму действий без перегрузки конкретными городами и филиалами.",
            "> 2. **Мультивариативный банк кейсов:** Для каждого правила генерируются альтернативные сценарии в контексте разных филиалов/регионов.",
            "> 3. **Разнообразие формулировок дистракторов:** Неверные ответы в разных вариантах сформулированы по-разному (разные типы реальных ошибок), что исключает списывание по шаблонам.",
            "",
        ]
        for lesson in course.lessons:
            preview_md.extend([
                f"## Урок: {lesson.title}",
                "",
                lesson.content,
                "",
            ])
            if lesson.cases:
                preview_md.extend([
                    "### 🎯 Банк ситуационных кейсов (Адаптивное тестирование)",
                    "",
                    "> [!NOTE]",
                    "> Каждый кейс содержит независимые варианты контекста (филиалы Группы 1 vs Группы 2) и динамический пул формулировок ошибок. Студенты из разных филиалов видят разные фабулы и разные формулировки дистракторов.",
                    "",
                ])
                for i, case in enumerate(lesson.cases, 1):
                    preview_md.extend([
                        f"#### Кейс {i}: {case.learning_objective}",
                        f"**Правило-источник:** `{case.rule_id}`",
                        "",
                    ])
                    for v_idx, variant in enumerate(case.variants, 1):
                        assembled = variant.assemble_question(seed=100 + i * 10 + v_idx)
                        preview_md.extend([
                            f"##### Вариант {v_idx} [{variant.branch_context}]",
                            f"**Ситуация:** {variant.scenario_premise}",
                            "",
                            f"**Вопрос:** {variant.prompt}",
                            "",
                            "**Собранные 4 варианта ответа для сотрудника:**",
                        ])
                        for opt in assembled.options:
                            marker = "[x] **(Верно)**" if opt.is_correct else "[ ]"
                            cat_info = f" *[{opt.distractor_category.value}]*" if opt.distractor_category else ""
                            preview_md.append(f"- {marker} {opt.text}{cat_info}")
                        preview_md.extend([
                            "",
                            f"💡 **Обучающий разбор:** {variant.explanation}",
                            f"📌 *Нормативное основание:* «{variant.source_quote}»",
                            "",
                        ])
            else:
                preview_md.extend([
                    "### 🎯 Ситуационный тест к уроку",
                    "",
                ])
                for i, q in enumerate(lesson.questions, 1):
                    preview_md.extend([
                        f"#### Кейс {i}",
                        f"**Ситуация:** {q.scenario_premise}",
                        "",
                        f"**Вопрос:** {q.prompt}",
                        "",
                    ])
                    for opt in q.options:
                        marker = "[x] **(Верно)**" if opt.is_correct else "[ ]"
                        cat_info = f" *[{opt.distractor_category.value}]*" if opt.distractor_category else ""
                        preview_md.append(f"- {marker} {opt.text}{cat_info}")
                    preview_md.extend([
                        "",
                        f"💡 **Обучающее объяснение:** {q.explanation}",
                        f"📌 *Основание:* «{q.source_quote}»",
                        "",
                    ])

        args.output.write_text("\n".join(preview_md), encoding="utf-8")
        json_path = args.output.with_suffix(".json")
        json_path.write_text(json.dumps(course.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[OK] Course successfully generated and saved to:\n  {args.output}\n  {json_path}")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
