"""Propose one contiguous, source-unit citation candidate; never certify meaning."""

import hashlib
import json
from collections import Counter
from dataclasses import replace
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.citation_review import bind_displayed_citation, build_citation_review_items
from app.modules.ai.v3.models import RuleEntity, V3Lesson


def propose_rule_quote_expansion(corpus: DirectSourceCorpus, rule: RuleEntity, original: str) -> str | None:
    """Return the complete contiguous rule span when the displayed quote is short.

    The extracted ``source_quote`` is the rule's semantic anchor, while its
    offsets identify an extraction-unit span in the authenticated document.
    The offsets prove document/revision/span provenance, not that every
    sentence in the unit belongs semantically to this rule. Answers and
    explanations may use more than the anchor sentence, so expand only to that
    exact contiguous unit and leave semantic support to the independent review.
    No disjoint excerpts are joined here and expansion never certifies meaning.
    """
    anchor = rule.source_quote
    if (not isinstance(original, str) or not original.strip() or not isinstance(anchor, str)
            or not anchor.strip() or original not in anchor):
        return None
    matching = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id
                and doc.source_revision == rule.source_revision and doc.source_text is not None]
    if (len(matching) != 1 or type(rule.source_start) is not int or type(rule.source_end) is not int):
        return None
    source = matching[0].source_text or ""
    if not 0 <= rule.source_start < rule.source_end <= len(source):
        return None
    candidate = source[rule.source_start:rule.source_end]
    if not candidate.strip() or original == candidate:
        return None
    if (not bind_displayed_citation(corpus, rule, anchor)
            or not bind_displayed_citation(corpus, rule, original)
            or not bind_displayed_citation(corpus, rule, candidate)):
        return None
    return candidate


def citation_question_fingerprint(lesson: V3Lesson, question_id: str) -> str | None:
    """Bind all variant, case and compatibility-question state before review."""
    found = [(case, variant) for case in lesson.cases for variant in case.variants
             if f"{variant.variant_id}-assembled" == question_id]
    compatible = [q.to_dict() for q in lesson.questions if q.question_id == question_id]
    if len(compatible) > 1 or (lesson.cases and len(found) != 1) or (not lesson.cases and len(compatible) != 1):
        return None
    data: dict[str, Any] = {"compatibility": compatible}
    if found:
        case, variant = found[0]
        data.update(case_id=case.case_id, rule_id=case.rule_id, learning_objective=case.learning_objective,
                    variant=variant.to_dict())
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf8")).hexdigest()


def stage_citation_candidate(
    lesson: V3Lesson, rule: RuleEntity, corpus: DirectSourceCorpus, reviewed_item: dict[str, str], candidate: str,
    reviewed_question_fingerprint: str,
) -> V3Lesson | None:
    """Stage one source-bound candidate against the exact reviewed question state."""
    question_id = reviewed_item.get("id", "")
    original = reviewed_item.get("displayed_quote", "")
    if (not question_id or not original or not candidate or not reviewed_question_fingerprint
            or citation_question_fingerprint(lesson, question_id) != reviewed_question_fingerprint
            or propose_rule_quote_expansion(corpus, rule, original) != candidate):
        return None
    current, issues = build_citation_review_items(lesson, [rule], corpus)
    matching = [item for item in current if item["id"] == question_id]
    if len(matching) != 1 or matching[0] != reviewed_item or "duplicate_or_empty_question_id" in issues:
        return None
    q_matches = [q for q in lesson.questions if q.question_id == question_id]
    if len(q_matches) > 1:
        return None
    variants = [v for case in lesson.cases for v in case.variants if f"{v.variant_id}-assembled" == question_id]
    if lesson.cases:
        if len(variants) != 1 or variants[0].source_quote != original:
            return None
        variant = variants[0]
        if q_matches:
            q = q_matches[0]
            expected = variant.assemble_question(seed=42)
            allowed = Counter((o.text, o.is_correct) for o in (variant.correct_option, *variant.distractor_pool))
            if (q.scenario_premise != expected.scenario_premise or q.prompt != variant.prompt
                    or q.rule_id != expected.rule_id or q.explanation != variant.explanation or q.source_quote != original
                    or len(q.options) != 4 or Counter((o.text, o.is_correct) for o in q.options) - allowed
                    or [o.text for o in q.options if o.is_correct] != [variant.correct_option.text]):
                return None
        cases = tuple(replace(case, variants=tuple(
            replace(v, source_quote=candidate) if f"{v.variant_id}-assembled" == question_id else v
            for v in case.variants)) for case in lesson.cases)
    else:
        if len(q_matches) != 1 or q_matches[0].source_quote != original:
            return None
        cases = lesson.cases
    questions = tuple(replace(q, source_quote=candidate) if q.question_id == question_id else q
                      for q in lesson.questions)
    return replace(lesson, cases=cases, questions=questions)
