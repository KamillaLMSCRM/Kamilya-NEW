"""P14: independently review each lesson and audit every source block."""
from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.v3.practical_applicability import SOURCE_APPLICABILITY_GUIDE
from app.modules.ai.v3.practical_atomic_audit import (
    atomic_audit_format,
    atomic_audit_messages,
    atomic_audit_narrative_sources,
    compiled_atomic_audit_findings,
    validate_atomic_audit,
)
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import (
    PracticalSourcePacket,
    course_response_format,
    source_model_text,
    validate_practical_course,
)
from app.modules.ai.v3.practical_cycle import (
    FRESH_AUTHOR_SYSTEM,
    PracticalCycleResult,
    StageInvoker,
    _hash,
    practical_patch_messages,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_patch import merge_practical_patch, practical_patch_format
from app.modules.ai.v3.practical_review import (
    interpret_practical_review,
    practical_review_format,
    practical_review_messages,
)


def partition_previous(course: dict[str, Any], packet: PracticalSourcePacket,
                       previous: tuple[dict[str, Any], ...]) -> tuple[dict[str, tuple[dict[str, Any], ...]], tuple[dict[str, Any], ...]]:
    """Each existing issue has exactly one reviewer; stale targets fail closed."""
    lessons = {lesson['id']: lesson for lesson in course['lessons']}
    question_owner = {q['id']: lesson['id'] for lesson in course['lessons'] for q in lesson['questions']}
    sources = {block.block_id for block in packet.blocks if block.text.strip()}
    grouped: dict[str, list[dict[str, Any]]] = {lesson_id: [] for lesson_id in lessons}
    global_items: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in previous:
        issue_id, scope, target = item['issue_id'], item['scope'], item['id']
        if type(issue_id) is not str or not issue_id or issue_id in ids:
            raise ValueError('practical_lesson_issue_inventory_invalid')
        ids.add(issue_id)
        if scope == 'question' and target in question_owner:
            grouped[question_owner[target]].append(item)
        elif scope in {'lesson', 'assessment'} and target in lessons:
            grouped[target].append(item)
        elif scope == 'source' and target in sources or scope == 'coverage' and target in sources | set(lessons):
            global_items.append(item)
        else:
            raise ValueError('practical_lesson_issue_target_invalid')
    return ({key: tuple(items) for key, items in grouped.items()}, tuple(global_items))


async def run_lesson_practical_cycle(packet: PracticalSourcePacket, intent: dict[str, Any], invoke: StageInvoker,
                                     *, max_revisions: int = 3) -> PracticalCycleResult:
    if type(max_revisions) is not int or not 0 <= max_revisions <= 3:
        raise ValueError('practical_revision_policy_invalid')
    view = PracticalModelView(packet)
    planning = [{'unit_id': key, 'source_refs': list(refs)} for key, refs in audit_units(packet).groups]

    async def call(stage: str, group: str, messages: list[dict[str, str]], fmt: dict[str, Any], validate: Any) -> dict[str, Any]:
        def validate_wire(value: dict[str, Any]) -> None:
            validate(view.decode(value))
        raw = await invoke(stage, group, messages, view.schema(fmt), validate_wire)
        value = view.decode(raw)
        if not isinstance(value, dict):
            raise ValueError('practical_response_invalid')
        validate(value)
        return value

    messages = [{'role': 'system', 'content': FRESH_AUTHOR_SYSTEM + SOURCE_APPLICABILITY_GUIDE},
        {'role': 'user', 'content': source_model_text(packet, aliases=view.canonical_to_alias)
         + '\nSOURCE_LOGICAL_UNITS_JSON\n' + json.dumps(view.encode(planning), ensure_ascii=False, sort_keys=True)
         + '\nCOURSE_INTENT_JSON\n' + json.dumps(intent, ensure_ascii=False, sort_keys=True, indent=2)}]
    def validate_author(value: dict[str, Any]) -> None:
        view.assert_course_ids_disjoint(value)
        validate_practical_course(value, packet)
    candidate = validate_practical_course(await call('lesson', 'practical:author:v1', messages,
                                                      course_response_format(packet), validate_author), packet)
    previous: tuple[dict[str, Any], ...] = ()
    seen: set[str] = set()
    history: list[dict[str, Any]] = []
    for revision in range(max_revisions + 1):
        digest = _hash(candidate)
        seen.add(digest)
        by_lesson, global_previous = partition_previous(candidate, packet, previous)
        parts = []
        for lesson in candidate['lessons']:
            part = {'title': candidate['title'], 'lessons': [copy.deepcopy(lesson)]}
            prior = by_lesson[lesson['id']]
            def validate_part(value: dict[str, Any], checked: dict[str, Any] = part,
                              checked_prior: tuple[dict[str, Any], ...] = prior) -> None:
                interpret_practical_review(value, packet, checked, checked_prior, concise=True, strict_targets=True)
            group = 'practical:review:' + _hash(['v3-practical-source-review-v14', part, prior])
            result = await call('review', group,
                practical_review_messages(packet, part, prior, model_view=view, concise=True, lesson_scoped=True),
                practical_review_format(packet, part, prior, concise=True, strict_targets=True), validate_part)
            parts.append(result)
        def validate_global(value: dict[str, Any], checked: dict[str, Any] = candidate,
                            prior: tuple[dict[str, Any], ...] = global_previous) -> None:
            validate_atomic_audit(value, packet, checked, prior)
        audit = await call('review', 'practical:source-audit:' + _hash(['v3-practical-source-review-v14', candidate, global_previous]),
            atomic_audit_messages(packet, candidate, global_previous, model_view=view),
            atomic_audit_format(packet, candidate, global_previous), validate_global)
        narrative = atomic_audit_narrative_sources(audit, packet, candidate, global_previous)
        consolidated: dict[str, Any] = {'source_fingerprint': packet.fingerprint,
            'source_review': '\n'.join([row['source_review'] for row in parts] + [audit['source_review']]),
            'source_notes': [], 'findings': [], 'answer_keys': {}, 'answerability': [], 'narrative_sources': {}}
        issue_checks: dict[str, Any] = {}
        for lesson, part in zip(candidate['lessons'], parts, strict=True):
            lesson_id = lesson['id']
            consolidated['source_notes'].extend(part['source_notes'])
            consolidated['findings'].extend(part['findings'])
            consolidated['answer_keys'].update(part['answer_keys'])
            consolidated['answerability'].extend(part['answerability'])
            consolidated['narrative_sources'][lesson_id] = list(dict.fromkeys(
                [*part['narrative_sources'][lesson_id], *narrative[lesson_id]]))
            for key, value in part.get('issue_checks', {}).items():
                if key in issue_checks:
                    raise ValueError('practical_lesson_issue_inventory_invalid')
                issue_checks[key] = value
        consolidated['source_notes'].extend(audit['source_notes'])
        consolidated['findings'].extend(compiled_atomic_audit_findings(audit, packet, candidate, global_previous))
        for key, value in audit.get('issue_checks', {}).items():
            if key in issue_checks:
                raise ValueError('practical_lesson_issue_inventory_invalid')
            issue_checks[key] = value
        if set(issue_checks) != {item['issue_id'] for item in previous}:
            raise ValueError('practical_lesson_issue_inventory_invalid')
        if previous:
            consolidated['issue_checks'] = issue_checks
        decision = interpret_practical_review(consolidated, packet, candidate, previous, concise=True)
        history.append({'course_sha256': digest, 'lesson_reviews': parts, 'atomic_audit': audit,
                        'consolidated_review': consolidated, 'accepted': decision.accepted,
                        'source_uncertain': decision.source_uncertain})
        editable = bool(decision.lesson_ids or decision.question_ids or decision.assessment_lesson_ids)
        reason = ('accepted' if decision.accepted else 'source_uncertain'
                  if decision.source_uncertain and (not editable or revision == max_revisions)
                  else 'revision_limit' if revision == max_revisions else '')
        if reason:
            return PracticalCycleResult(candidate, consolidated, decision, tuple(history), reason,
                                        (), False, True, lesson_scoped_review=True)
        fmt = practical_patch_format(packet, candidate, decision)
        def validate_patch(value: dict[str, Any], checked: dict[str, Any] = candidate,
                           checked_decision: Any = decision) -> None:
            view.assert_course_ids_disjoint(merge_practical_patch(checked, packet, checked_decision, value))
        patch = await call('repair', 'practical:repair:' + _hash([digest, consolidated]),
            practical_patch_messages(packet, candidate, decision, model_view=view), fmt, validate_patch)
        revised = merge_practical_patch(candidate, packet, decision, patch)
        view.assert_course_ids_disjoint(revised)
        if _hash(revised) in seen:
            return PracticalCycleResult(candidate, consolidated, decision, tuple(history), 'no_progress',
                                        (), False, True, lesson_scoped_review=True)
        candidate = revised
        previous = decision.feedback
    raise AssertionError('unreachable')
