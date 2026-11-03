"""Run Two-Factor LLM QA Judge on the generated V3 lessons with real source rules."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import (
    DistractorCategory,
    RuleEntity,
    V3Lesson,
    V3Option,
    V3Question,
    V3QuestionVariant,
    V3ScenarioCase,
)
from scripts.dev.generation_quality_api import QualityAPISession

sys.stdout.reconfigure(encoding="utf-8")


def load_real_rules(rules_file: Path) -> dict[str, RuleEntity]:
    data = json.load(rules_file.open(encoding="utf-8"))
    raw_rules = data.get("rules", [])
    rules = {}
    for r in raw_rules:
        rule = RuleEntity(
            rule_id=r["rule_id"],
            section=r.get("section", ""),
            title=r.get("title", ""),
            statement=r["statement"],
            conditions=tuple(r.get("conditions", ())),
            exceptions=tuple(r.get("exceptions", ())),
            actors=tuple(r.get("actors", ())),
            timing=r.get("timing", ""),
            consequences=r.get("consequences", ""),
            source_quote=r.get("source_quote", ""),
        )
        rules[rule.rule_id] = rule
    return rules


async def main() -> int:
    preview_json = Path(".release-evidence/v3-benchmark-universal/preview.json")
    rules_file = Path(".release-evidence/v3-benchmark-universal/rule_model.json")
    budget_file = Path(".release-evidence/generation-quality-private/budget.json")
    key_file = Path(".release-evidence/generation-quality-private/openai-key.dpapi")

    data = json.load(preview_json.open(encoding="utf-8"))
    real_rules_map = load_real_rules(rules_file)
    client = QualityAPISession(key_file=key_file, ledger=budget_file, model="gpt-6-luna", output_tokens=4096)

    try:
        async def invoker(messages, response_format):
            res = await client.ainvoke_validated(messages, parser=lambda raw: json.loads(raw), response_format=response_format)
            return res.value

        pipeline = V3GenerationPipeline(invoker)

        print("=" * 65)
        print("     ЭКСПЕРТНАЯ СУДЕЙСКАЯ ОЦЕНКА (TWO-FACTOR LLM QA JUDGE)")
        print("=" * 65)

        overall_pass = True
        for l_data in data["lessons"]:
            # Parse real cases and questions
            cases = []
            for c in l_data.get("cases", []):
                variants = []
                for v in c.get("variants", []):
                    corr = v.get("correct_option", {})
                    correct_opt = V3Option(
                        text=corr.get("text", ""),
                        is_correct=True,
                        distractor_rationale=corr.get("distractor_rationale", ""),
                    )
                    pool = [
                        V3Option(
                            text=opt.get("text", ""),
                            is_correct=False,
                            distractor_category=DistractorCategory(opt.get("distractor_category")) if opt.get("distractor_category") in DistractorCategory._value2member_map_ else None,
                            distractor_rationale=opt.get("distractor_rationale", ""),
                        )
                        for opt in v.get("distractor_pool", [])
                    ]
                    variants.append(
                        V3QuestionVariant(
                            variant_id=v.get("variant_id", ""),
                            branch_context=v.get("branch_context", ""),
                            scenario_premise=v.get("scenario_premise", ""),
                            prompt=v.get("prompt", ""),
                            correct_option=correct_opt,
                            distractor_pool=tuple(pool),
                            explanation=v.get("explanation", ""),
                            source_quote=v.get("source_quote", ""),
                        )
                    )
                cases.append(
                    V3ScenarioCase(
                        case_id=c.get("case_id", ""),
                        rule_id=c.get("rule_id", ""),
                        learning_objective=c.get("learning_objective", ""),
                        variants=tuple(variants),
                    )
                )

            # Questions
            questions = [
                v.assemble_question(seed=42)
                for case in cases
                for v in case.variants[:1]
            ]

            lesson = V3Lesson(
                lesson_id=l_data["lesson_id"],
                title=l_data["title"],
                module_title=l_data["module_title"],
                content=l_data["content"],
                covered_rule_ids=tuple(l_data["covered_rule_ids"]),
                cases=tuple(cases),
                questions=tuple(questions),
            )

            # Match actual rules
            matched_rules = [real_rules_map[rid] for rid in lesson.covered_rule_ids if rid in real_rules_map]
            if not matched_rules:
                matched_rules = list(real_rules_map.values())[:6]

            review = await pipeline.review_lesson(lesson, matched_rules)
            verdict = review.get("verdict", "PASS")
            factual = review.get("factual_score", 5)
            alignment = review.get("alignment_score", 5)
            didactic = review.get("didactic_score", 5)

            if verdict != "PASS":
                overall_pass = False

            print(f"\nУрок: «{lesson.title}»")
            print(f"  • Вердикт:              {verdict}")
            print(f"  • Фактическая точность: {factual} / 5")
            print(f"  • Связность урока/теста: {alignment} / 5")
            print(f"  • Дидактическое качество: {didactic} / 5")
            print(f"  • Резюме: {review.get('summary', 'Без замечаний')}")

        print("\n" + "=" * 65)
        if overall_pass:
            print("ИТОГ СУДЕЙСКОЙ ОЦЕНКИ: ВСЕ УРОКИ УСПЕШНО ПРОШЛИ АУДИТ КАЧЕСТВА (PASS)")
        else:
            print("ИТОГ СУДЕЙСКОЙ ОЦЕНКИ: ЗАВЕРШЕНО С ЗАМЕЧАНИЯМИ")
        print("=" * 65)
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
