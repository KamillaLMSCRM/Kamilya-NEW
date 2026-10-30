"""Core generator and validator for V3 generation architecture."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from app.modules.ai.v3.models import (
    DistractorCategory,
    DocumentRuleModel,
    RuleEntity,
    V3Lesson,
    V3Option,
    V3Question,
    V3QuestionVariant,
    V3ScenarioCase,
)
from app.modules.ai.v3.prompts import (
    LESSON_COGEN_SYSTEM_PROMPT,
    QA_REVIEW_SYSTEM_PROMPT,
    RULE_EXTRACTION_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class V3GenerationPipeline:
    """End-to-end pipeline implementing the V3 Didactic Co-Generation Architecture."""

    def __init__(self, llm_invoker: Callable[[list[dict[str, str]], dict[str, Any] | None], Any]) -> None:
        """
        llm_invoker: async or sync callable that accepts messages list and optional response_format,
        returning a parsed JSON dict or string.
        """
        self.invoker = llm_invoker

    async def extract_rule_model(self, document_title: str, document_text: str, document_sha256: str) -> DocumentRuleModel:
        """Step 1: Extract structured Normative Matrix from full document text."""
        messages = [
            {"role": "system", "content": RULE_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"ДОКУМЕНТ: {document_title}\nSHA256: {document_sha256}\n\nПОЛНЫЙ ТЕКСТ:\n{document_text}",
            },
        ]
        raw = await self._call_llm(messages)
        rules = [
            RuleEntity(
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
            for r in raw.get("rules", [])
        ]
        return DocumentRuleModel(
            document_title=raw.get("document_title", document_title),
            document_sha256=document_sha256,
            rules=tuple(rules),
            overview=raw.get("overview", ""),
        )

    async def generate_lesson_with_scenarios(
        self,
        module_title: str,
        lesson_theme: str,
        rules: list[RuleEntity],
        existing_lessons_summary: str = "",
    ) -> V3Lesson:
        """Step 2 & 3: Co-generate Lesson Narrative paired directly with 4-option Scenario Questions."""
        rules_payload = [r.to_dict() for r in rules]
        messages = [
            {"role": "system", "content": LESSON_COGEN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"МОДУЛЬ: {module_title}\n"
                    f"ТЕМА УРОКА: {lesson_theme}\n"
                    f"ПРЕДЫДУЩИЕ УРОКИ: {existing_lessons_summary or 'Первый урок курса'}\n\n"
                    f"НОРМАТИВНЫЕ ПРАВИЛА ДЛЯ УРОКА:\n{json.dumps(rules_payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ]
        raw = await self._call_llm(messages)
        cases: list[V3ScenarioCase] = []
        assembled_questions: list[V3Question] = []

        for c in raw.get("cases", []):
            variants: list[V3QuestionVariant] = []
            for v in c.get("variants", []):
                corr_raw = v.get("correct_option", {})
                correct_opt = V3Option(
                    text=corr_raw.get("text", ""),
                    is_correct=True,
                    distractor_category=None,
                    distractor_rationale=corr_raw.get("distractor_rationale", ""),
                )
                distractor_pool: list[V3Option] = []
                for opt in v.get("distractor_pool", []):
                    cat_str = opt.get("distractor_category")
                    cat = DistractorCategory(cat_str) if cat_str in DistractorCategory._value2member_map_ else None
                    distractor_pool.append(
                        V3Option(
                            text=opt.get("text", ""),
                            is_correct=False,
                            distractor_category=cat,
                            distractor_rationale=opt.get("distractor_rationale", ""),
                        )
                    )
                variant = V3QuestionVariant(
                    variant_id=v.get("variant_id", ""),
                    branch_context=v.get("branch_context", ""),
                    scenario_premise=v.get("scenario_premise", ""),
                    prompt=v.get("prompt", ""),
                    correct_option=correct_opt,
                    distractor_pool=tuple(distractor_pool),
                    explanation=v.get("explanation", ""),
                    source_quote=v.get("source_quote", ""),
                )
                variants.append(variant)

            case_obj = V3ScenarioCase(
                case_id=c.get("case_id", ""),
                rule_id=c.get("rule_id", ""),
                learning_objective=c.get("learning_objective", ""),
                variants=tuple(variants),
            )
            cases.append(case_obj)
            if variants:
                assembled_questions.append(variants[0].assemble_question(seed=42))

        # Fallback if flat questions returned
        if not cases and "questions" in raw:
            for q in raw.get("questions", []):
                options = []
                for opt in q.get("options", []):
                    cat_str = opt.get("distractor_category")
                    cat = DistractorCategory(cat_str) if cat_str in DistractorCategory._value2member_map_ else None
                    options.append(
                        V3Option(
                            text=opt["text"],
                            is_correct=bool(opt.get("is_correct", False)),
                            distractor_category=cat,
                            distractor_rationale=opt.get("distractor_rationale", ""),
                        )
                    )
                assembled_questions.append(
                    V3Question(
                        question_id=q["question_id"],
                        scenario_premise=q["scenario_premise"],
                        prompt=q["prompt"],
                        options=tuple(options),
                        explanation=q.get("explanation", ""),
                        rule_id=q.get("rule_id", ""),
                        source_quote=q.get("source_quote", ""),
                    )
                )

        return V3Lesson(
            lesson_id=raw["lesson_id"],
            title=raw["title"],
            module_title=raw.get("module_title", module_title),
            content=raw["content"],
            covered_rule_ids=tuple(r.rule_id for r in rules),
            cases=tuple(cases),
            questions=tuple(assembled_questions),
        )

    async def review_lesson(self, lesson: V3Lesson, source_rules: list[RuleEntity]) -> dict[str, Any]:
        """Step 4: Two-factor evaluation of Lesson and Questions."""
        messages = [
            {"role": "system", "content": QA_REVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"ПРОВЕРЯЕМЫЙ УРОК:\n{json.dumps(lesson.to_dict(), ensure_ascii=False, indent=2)}\n\n"
                    f"ЭТАЛОННЫЕ ПРАВИЛА ИЗ ИСТОЧНИКА:\n{json.dumps([r.to_dict() for r in source_rules], ensure_ascii=False, indent=2)}"
                ),
            },
        ]
        result: dict[str, Any] = await self._call_llm(messages)
        return result

    async def _call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        result = await self.invoker(messages, {"type": "json_object"})
        if isinstance(result, str):
            parsed: dict[str, Any] = json.loads(result)
            return parsed
        parsed_dict: dict[str, Any] = dict(result)
        return parsed_dict
