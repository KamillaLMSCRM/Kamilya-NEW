"""Review a staged case repair before it may replace the original lesson."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.citation_expansion import citation_question_fingerprint
from app.modules.ai.v3.models import RuleEntity, V3Lesson


def answer_review_fingerprint(
    scenario: str, question: str, options: list[tuple[str, bool]], rule_id: str,
    source_units: list[str], reference_context: tuple[str, ...],
) -> str:
    """Bind reuse to the exact delivered option order and evidence sent for review."""
    payload = [scenario, question, options, rule_id, source_units, reference_context]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf8")).hexdigest()


def case_compatibility_identity_matches(lesson: V3Lesson, case_id: str) -> bool:
    """Reject replacement when a compatibility question is not the target case's own projection."""
    matches = [(index, case) for index, case in enumerate(lesson.cases) if case.case_id == case_id]
    if len(matches) != 1 or not matches[0][1].variants:
        return False
    if not lesson.questions:
        return True
    if len(lesson.questions) != len(lesson.cases) or len({q.question_id for q in lesson.questions}) != len(lesson.questions):
        return False
    index, case = matches[0]
    variant = case.variants[0]
    question = lesson.questions[index]
    expected = variant.assemble_question(seed=42)
    allowed = Counter((o.text, o.is_correct) for o in (variant.correct_option, *variant.distractor_pool))
    return (question.question_id == expected.question_id and question.rule_id == expected.rule_id
            and question.scenario_premise == expected.scenario_premise and question.prompt == expected.prompt
            and question.explanation == expected.explanation and question.source_quote == expected.source_quote
            and len(question.options) == 4 and not (Counter((o.text, o.is_correct) for o in question.options) - allowed)
            and [o.text for o in question.options if o.is_correct] == [variant.correct_option.text])


async def review_staged_case(
    candidate: V3Lesson, case_id: str, review_rules: list[RuleEntity], corpus: DirectSourceCorpus,
    source_fragments: list[str], exact_source_units: list[str], reference_context: tuple[str, ...],
    partial_case: bool, pipeline: Any, record: dict[str, Any],
) -> tuple[bool, dict[str, dict[str, Any]]]:
    """Accumulate evidence into record before promotion; unknown outcomes propagate."""
    from dataclasses import replace

    from app.modules.ai.v3.service import (
        _review_source_unit_fragments,
        _validate_answer_completeness,
        _validate_critic_response,
        _validate_question_entailment,
    )

    matches = [(index, case) for index, case in enumerate(candidate.cases, 1) if case.case_id == case_id]
    if len(matches) != 1 or not exact_source_units:
        record["rejected"] = "candidate_case_identity_or_source_invalid"
        return False, {}
    ci, case = matches[0]
    linked = [rule for rule in review_rules if rule.rule_id == case.rule_id]
    if len(linked) != 1 or not _review_source_unit_fragments(linked, corpus):
        record["rejected"] = "candidate_rule_source_invalid"
        return False, {}
    case_part = replace(candidate, cases=(case,), questions=())
    critic = await pipeline.review_lesson(case_part, review_rules, source_fragments=source_fragments,
                                          partial_case=partial_case, reference_context=reference_context)
    record["recheck"] = critic
    valid, reason = _validate_critic_response(critic, candidate.lesson_id, candidate.title)
    if not valid or str(critic.get("verdict", "")).strip().upper() != "PASS":
        record["rejected"] = "candidate_critic_failed"
        record["rejection_reason"] = reason
        return False, {}
    answer_checks: list[dict[str, Any]] = []
    record["answer_rechecks"] = answer_checks
    accepted: dict[str, dict[str, Any]] = {}
    for vi, variant in enumerate(case.variants, 1):
        question = variant.assemble_question(seed=100 + ci * 10 + vi)
        flags = [option.is_correct for option in question.options]
        if len(flags) != 4 or sum(flags) != 1 or any(not option.text.strip() for option in question.options):
            record["rejected"] = "candidate_question_shape_invalid"
            return False, {}
        qid = variant.variant_id
        entry: dict[str, Any] = {"question_id": qid}
        answer_checks.append(entry)
        texts = [option.text for option in question.options]
        option_review = await pipeline.review_question_options(question.scenario_premise, question.prompt, texts,
                                                               exact_source_units, reference_context)
        entry["review"] = option_review
        valid, reason = _validate_question_entailment(option_review, flags)
        if not valid:
            record.update(rejected="candidate_option_review_failed", rejection_reason=reason)
            return False, {}
        compatibility = await pipeline.review_question_compatibility(question.scenario_premise, question.prompt,
                                                                     texts, exact_source_units, reference_context)
        from app.modules.ai.v3.compatibility_recheck import recheck_compatibility
        valid, reason = await recheck_compatibility(
            pipeline, question.scenario_premise, question.prompt, texts, flags,
            exact_source_units, reference_context, compatibility, entry)
        if not valid:
            record.update(rejected="candidate_compatibility_failed", rejection_reason=reason)
            return False, {}
        answer = next(option.text for option in question.options if option.is_correct)
        completeness = await pipeline.review_answer_completeness(question.scenario_premise, question.prompt, answer,
                                                                 exact_source_units, reference_context)
        entry["completeness"] = completeness
        valid, reason = _validate_answer_completeness(completeness)
        if not valid:
            record.update(rejected="candidate_completeness_failed", rejection_reason=reason)
            return False, {}
        fingerprint = citation_question_fingerprint(candidate, question.question_id)
        if not fingerprint or qid in accepted:
            record["rejected"] = "candidate_question_identity_invalid"
            return False, {}
        accepted[qid] = {"fingerprint": fingerprint,
                         "answer_review_fingerprint": answer_review_fingerprint(
                             question.scenario_premise, question.prompt, [(o.text, o.is_correct) for o in question.options],
                             case.rule_id, exact_source_units, reference_context),
                         "check": entry}
    if not case.variants:
        record["rejected"] = "candidate_empty_case"
        return False, {}
    return True, accepted
