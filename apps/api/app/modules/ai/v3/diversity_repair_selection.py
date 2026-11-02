"""Pure candidate selection only; no repair or semantic coverage claim."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.diversity_review import POLICY, _hash
from app.modules.ai.v3.models import RuleEntity, V3Lesson
from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest


@dataclass(frozen=True)
class Selection:
    case_id: str
    variant_id: str
    rule_id: str
    question_index: int
    source_quote: str
    manifest_fingerprint: str
    observation_fingerprint: str


def select_candidate(
    *,
    lesson: V3Lesson,
    corpus: DirectSourceCorpus,
    rules: tuple[RuleEntity, ...],
    expected_tenant_id: str,
    expected_document_ids: tuple[str, ...],
    observation: Any,
    selected_index: int,
    context_rules: tuple[RuleEntity, ...] = (),
) -> Selection | None:
    """Select only one reviewer-selected member of one overlap and one same-rule omission.

    Caller MUST load observation from its owned journal; this pure helper cannot authenticate it.
    """
    manifest = build_primary_source_manifest(
        corpus, rules, expected_tenant_id=expected_tenant_id, expected_document_ids=expected_document_ids
    )
    if manifest is None:
        return None
    questions = [q.to_dict() for q in project_lesson_questions(lesson)]  # type: ignore[no-untyped-call]
    request: dict[str, Any] = {
        "policy": POLICY,
        "manifest_sha256": manifest.fingerprint,
        "primary_sources": [
            {"rule_id": r.rule_id, "text": text} for r, text in zip(rules, manifest.fragments, strict=True)
        ],
        "questions": questions,
    }
    if context_rules:
        combined = build_primary_source_manifest(corpus, rules + context_rules, expected_tenant_id=expected_tenant_id,
                                                 expected_document_ids=expected_document_ids)
        context = build_primary_source_manifest(corpus, context_rules, expected_tenant_id=expected_tenant_id,
                                                expected_document_ids=expected_document_ids)
        if combined is None or context is None:
            return None
        request["context_source_manifest"] = {"fingerprint": context.fingerprint,
            "purpose": "Related conditions and exceptions only; assess omissions against primary sources, never treat context as a separate primary target.",
            "fragments": [{"rule_id": rule.rule_id, "text": fragment}
                          for rule, fragment in zip(context_rules, context.fragments, strict=True)]}
    fingerprint = _hash(request)
    if (
        not isinstance(observation, dict)
        or observation.get("status") != "review_required"
        or observation.get("fingerprint") != fingerprint
        or type(selected_index) is not int
    ):
        return None
    overlaps = observation.get("overlaps")
    omissions = observation.get("omissions")
    if not isinstance(overlaps, list) or len(overlaps) != 1 or not isinstance(omissions, list) or len(omissions) != 1:
        return None
    pair = overlaps[0]
    omission = omissions[0]
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or any(type(i) is not int for i in pair)
        or pair[0] >= pair[1]
        or selected_index not in pair
        or not isinstance(omission, dict)
        or set(omission) != {"rule_id", "exact_quote"}
        or not isinstance(omission["rule_id"], str)
        or not isinstance(omission["exact_quote"], str)
        or not omission["exact_quote"].strip()
    ):
        return None
    if not lesson.cases or len({c.case_id for c in lesson.cases}) != len(lesson.cases):
        return None
    projected = []
    for ci, case in enumerate(lesson.cases, 1):
        if not case.case_id or not case.rule_id:
            return None
        for vi, variant in enumerate(case.variants, 1):
            if not variant.variant_id:
                return None
            projected.append((case, variant, variant.assemble_question(seed=100 + ci * 10 + vi)))
    if len({v.variant_id for _, v, _ in projected}) != len(projected) or not 1 <= pair[0] < pair[1] <= len(projected):
        return None
    a, b = (projected[i - 1] for i in pair)
    if a[0].rule_id != b[0].rule_id or omission["rule_id"] != a[0].rule_id:
        return None
    matches = [(r, text) for r, text in zip(rules, manifest.fragments, strict=True) if r.rule_id == omission["rule_id"]]
    if len(matches) != 1:
        return None
    quote, fragment = omission["exact_quote"], matches[0][1]
    start = fragment.find(quote)
    if start < 0 or fragment.find(quote, start + 1) >= 0:
        return None
    case, variant, _ = projected[selected_index - 1]
    return Selection(
        case.case_id,
        variant.variant_id,
        case.rule_id,
        selected_index,
        omission["exact_quote"],
        manifest.fingerprint,
        fingerprint,
    )


def preserves_non_target(original: V3Lesson, candidate: V3Lesson, selected: Selection) -> bool:
    """Reject any changes outside the selected variant, including compatibility projections."""
    if not isinstance(candidate, V3Lesson) or len(original.cases) != len(candidate.cases):
        return False
    originals = [
        (i, j)
        for i, c in enumerate(original.cases)
        for j, v in enumerate(c.variants)
        if c.case_id == selected.case_id and v.variant_id == selected.variant_id and c.rule_id == selected.rule_id
    ]
    if len(originals) != 1:
        return False
    i, j = originals[0]
    try:
        old = original.cases[i]
        new = candidate.cases[i]
        if len(old.variants) != len(new.variants) or new.variants[j].variant_id != selected.variant_id:
            return False
        restored = replace(new, variants=(*new.variants[:j], old.variants[j], *new.variants[j + 1 :]))
        questions = candidate.questions
        if original.questions:
            from app.modules.ai.v3.case_repair_gate import case_compatibility_identity_matches

            if (len(original.questions) != len(original.cases) or len(questions) != len(original.questions)
                    or not case_compatibility_identity_matches(original, selected.case_id)):
                return False
            if j == 0:
                if questions[i] != new.variants[0].assemble_question(seed=42):
                    return False
                questions = (*questions[:i], original.questions[i], *questions[i + 1 :])
        return replace(candidate, cases=(*candidate.cases[:i], restored, *candidate.cases[i + 1 :]),
                       questions=questions) == original
    except (IndexError, AttributeError, TypeError):
        return False


async def select_owned_candidate(
    *,
    lesson: V3Lesson,
    corpus: DirectSourceCorpus,
    rules: tuple[RuleEntity, ...],
    expected_tenant_id: str,
    expected_document_ids: tuple[str, ...],
    journal: Any,
    group_id: str,
    source_sha256: str,
    route_fingerprint: str,
    selected_index: int,
    context_rules: tuple[RuleEntity, ...] = (),
) -> Selection | None:
    """Read the exact completed owned review; this function never invokes a provider.

    A later repair must recheck source ownership at its own atomic claim boundary.
    """
    import hashlib
    import json

    from app.modules.ai.v3.diversity_review import _SYSTEM, _validate
    from app.modules.ai.v3.owned_stage_inspection import inspect_owned_stage
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.stage_checkpoint import _digest, read_verified_stage_result, stage_plan

    if (
        type(journal) is not PendingStageJournal
        or journal.tenant_id != expected_tenant_id
        or corpus.tenant_id != expected_tenant_id
        or not callable(journal.verify_source)
    ):
        return None
    manifest = build_primary_source_manifest(
        corpus, rules, expected_tenant_id=expected_tenant_id, expected_document_ids=expected_document_ids
    )
    if manifest is None:
        return None
    source_parts = []
    for doc in corpus.documents:
        if doc.source_text is None:
            return None
        if doc.source_text:
            source_parts.append(doc.source_text)
    if hashlib.sha256("\n\n".join(source_parts).encode("utf-8")).hexdigest() != source_sha256:
        return None
    questions = [q.to_dict() for q in project_lesson_questions(lesson)]  # type: ignore[no-untyped-call]
    if not questions or len(questions) > 80:
        return None
    request: dict[str, Any] = {
        "policy": POLICY,
        "manifest_sha256": manifest.fingerprint,
        "primary_sources": [
            {"rule_id": rule.rule_id, "text": text} for rule, text in zip(rules, manifest.fragments, strict=True)
        ],
        "questions": questions,
    }
    if context_rules:
        combined = build_primary_source_manifest(corpus, rules + context_rules, expected_tenant_id=expected_tenant_id,
                                                 expected_document_ids=expected_document_ids)
        context = build_primary_source_manifest(corpus, context_rules, expected_tenant_id=expected_tenant_id,
                                                expected_document_ids=expected_document_ids)
        if combined is None or context is None:
            return None
        request["context_source_manifest"] = {"fingerprint": context.fingerprint,
            "purpose": "Related conditions and exceptions only; assess omissions against primary sources, never treat context as a separate primary target.",
            "fragments": [{"rule_id": rule.rule_id, "text": fragment}
                          for rule, fragment in zip(context_rules, context.fragments, strict=True)]}
    if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > 180_000:
        return None
    fingerprint = _hash(request)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps({**request, "fingerprint": fingerprint}, ensure_ascii=False)},
    ]
    plan = stage_plan(
        journal,
        stage="review",
        group_id=group_id,
        source_sha256=source_sha256,
        route_fingerprint=route_fingerprint,
        messages=messages,
        response_format={"type": "json_object"},
    )
    signature = _digest(plan)

    def validate(value: dict[str, Any]) -> dict[str, Any]:
        response = value.get("response")
        if (
            value.get("identity") != signature
            or not isinstance(response, dict)
            or value.get("response_sha256") != _digest(response)
        ):
            raise ValueError("owned_review_invalid")
        return response

    inspection = await inspect_owned_stage(
        journal=journal,
        user_id=journal.user_id,
        plan=plan,
        result_key=f"v3-stage-result:{signature}",
        claim_key=f"v3-stage-claim:{signature}",
        validate=validate,
        verify_source=journal.verify_source,
    )
    if inspection.decision != "replay" or inspection.result is None:
        return None
    result = await read_verified_stage_result(journal, plan)
    if result != inspection.result:
        return None
    checked = _validate(result, fingerprint, rules, manifest.fragments, len(questions))
    if checked is None:
        return None
    observation = {
        "status": "review_required",
        "fingerprint": fingerprint,
        "overlaps": checked["overlaps"],
        "omissions": checked["omissions"],
    }
    return select_candidate(
        lesson=lesson,
        corpus=corpus,
        rules=rules,
        expected_tenant_id=expected_tenant_id,
        expected_document_ids=expected_document_ids,
        observation=observation,
        selected_index=selected_index,
        context_rules=context_rules,
    )
