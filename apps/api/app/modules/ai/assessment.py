"""Assessment Agent — grounded question generation from lesson content."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Callable

from app.modules.ai.assessment_schema import (
    ASSESSMENT_JSON_SCHEMA,
    CourseAssessment,
    LessonAssessment,
)
from app.modules.ai.llm_client import LLMClient
from app.modules.ai.writer_schema import LessonContent

logger = logging.getLogger(__name__)
MAX_ASSESSMENT_RETRIES = 4


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response with preprocessing."""
    from json_repair import repair_json

    # Strip thinking tags if present
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    # Try code fence extraction — find ALL matches and pick the largest
    matches = re.findall(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", content)
    if matches:
        json_str = max(matches, key=len).strip()
    else:
        # Find all {...} blocks and pick the largest
        brace_matches = re.findall(r"\{[\s\S]*\}", content)
        if brace_matches:
            json_str = max(brace_matches, key=len).strip()
        else:
            json_str = content.strip()

    # Aggressive cleanup
    json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
    json_str = re.sub(r"//[^\n]*", "", json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    json_str = json_str.replace('\u201c', '"').replace('\u201d', '"')
    json_str = json_str.replace('\u2018', "'").replace('\u2019', "'")
    json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)

    # Try direct parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Fallback: json_repair library handles all missing commas, etc.
    repaired = repair_json(json_str, return_objects=True)
    if isinstance(repaired, dict):
        return repaired

    raise ValueError(f"Cannot parse JSON ({len(json_str)} chars)")


def _validate_assessment(assessment: LessonAssessment) -> list[str]:
    """Validate assessment structure."""
    issues = []
    for i, mcq in enumerate(assessment.mcq):
        correct_count = sum(1 for o in mcq.options if o.is_correct)
        if correct_count != 1:
            issues.append(f"MCQ #{i+1}: {correct_count} correct (expected 1)")
    for i, mq in enumerate(assessment.matching):
        lefts = [p.left for p in mq.pairs]
        rights = [p.right for p in mq.pairs]
        if len(lefts) != len(set(lefts)):
            issues.append(f"Matching #{i+1}: duplicate left values")
        if len(rights) != len(set(rights)):
            issues.append(f"Matching #{i+1}: duplicate right values")
    return issues


async def generate_lesson_assessment(
    llm: LLMClient,
    lesson_content: LessonContent,
    language: str = "ru",
) -> LessonAssessment:
    """Generate grounded assessment for a single lesson."""
    lang_names = {"ru": "Русский", "kk": "Қазақша", "en": "English"}
    lang_name = lang_names.get(language, language)

    system_prompt = (
        f"You are an assessment designer. Create questions based ONLY on the "
        f"provided lesson content. Write ALL content in {language} ({lang_name}). "
        f"Output valid JSON matching the schema."
    )

    user_prompt = f"""Create assessment questions for this lesson.

**Lesson**: {lesson_content.title}
**Target Language**: {language} ({lang_name})
**Content**: {lesson_content.content[:8000]}

Generate:
- 3-5 single choice questions (4 options, ONE correct)
- 2-3 true/false statements
- 1 matching question with 4-6 pairs

Output ONLY valid JSON matching this schema:
{json.dumps(ASSESSMENT_JSON_SCHEMA, indent=2, ensure_ascii=False)}"""

    for attempt in range(MAX_ASSESSMENT_RETRIES + 1):
        try:
            response = await llm.ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            print(f"[ASSESSMENT_RAW] attempt {attempt+1} len={len(response.content)} first500={response.content[:500]!r}", flush=True)
            data = _parse_json_response(response.content)
            print(f"[ASSESSMENT_OK] attempt {attempt+1} keys={list(data.keys())}", flush=True)
            break
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[ASSESSMENT_PARSE] attempt {attempt + 1} failed: {e}", flush=True)
            if attempt < MAX_ASSESSMENT_RETRIES:
                # Self-correction: send broken JSON back to LLM
                user_prompt = (
                    f"Your JSON has a syntax error: {e}\n\n"
                    f"Here is your output:\n{response.content[:3000]}\n\n"
                    f"Fix the JSON syntax and output ONLY the corrected valid JSON. No explanation."
                )
                continue
            raise

    assessment = LessonAssessment.from_dict({
        "lesson_title": lesson_content.title,
        **data,
    })

    issues = _validate_assessment(assessment)
    if issues:
        logger.warning(f"Validation issues for '{lesson_content.title}': {issues}")

    return assessment


async def generate_course_assessment(
    llm: LLMClient,
    course_content,
    language: str = "ru",
    on_progress: Callable | None = None,
) -> CourseAssessment:
    """Generate assessments for all lessons sequentially."""
    assessments = []
    total = sum(len(m.lessons) for m in course_content.modules)
    num = 0

    for module in course_content.modules:
        for lesson in module.lessons:
            num += 1
            if on_progress:
                result = on_progress(f"Generating assessment {num}/{total}: {lesson.title}")
                if hasattr(result, '__await__'):
                    await result
            a = await generate_lesson_assessment(llm, lesson, language=language)
            assessments.append(a)
            if num < total:
                await asyncio.sleep(5)

    return CourseAssessment(assessments=assessments)
