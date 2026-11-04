"""P14: independently review each lesson and audit every source block."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

from app.modules.ai.v3.practical_applicability import SOURCE_APPLICABILITY_GUIDE
from app.modules.ai.v3.practical_arbitration import (
    adjudicate_practical_findings,
    answer_finding,
    arbitration_format,
    arbitration_messages,
    original_finding,
    question_finding,
    retain_prior_findings,
)
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
    PracticalReviewDecision,
    interpret_practical_review,
    practical_review_format,
    practical_review_messages,
)


def partition_previous(course: dict[str, Any], packet: PracticalSourcePacket,
                       previous: tuple[dict[str, Any], ...], *, standalone: bool = False,
                       typed_findings: bool = False) -> tuple[dict[str, tuple[dict[str, Any], ...]], tuple[dict[str, Any], ...]]:
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
        if typed_findings and original_finding(item)['scope'] == 'question':
            owned_target = original_finding(item)['id']
            if owned_target not in question_owner:
                raise ValueError('practical_lesson_issue_target_invalid')
            (grouped[question_owner[owned_target]] if answer_finding(item) else global_items).append(item)
            continue
        if scope == 'question' and target in question_owner:
            grouped[question_owner[target]].append(item)
        elif scope in {'lesson', 'assessment'} and target in lessons:
            (global_items if standalone else grouped[target]).append(item)
        elif scope == 'source' and target in sources or scope == 'coverage' and target in sources | set(lessons):
            global_items.append(item)
        else:
            raise ValueError('practical_lesson_issue_target_invalid')
    return ({key: tuple(items) for key, items in grouped.items()}, tuple(global_items))


async def run_lesson_practical_cycle(packet: PracticalSourcePacket, intent: dict[str, Any], invoke: StageInvoker,
                                     *, max_revisions: int = 3, adjudicate: bool = False,
                                     standalone: bool = False, typed_findings: bool = False,
                                     counterexamples: bool = False) -> PracticalCycleResult:
    if (type(adjudicate) is not bool or type(standalone) is not bool or standalone and not adjudicate
            or type(typed_findings) is not bool or typed_findings and not standalone
            or type(counterexamples) is not bool or counterexamples and not typed_findings):
        raise ValueError('practical_revision_policy_invalid')
    if type(max_revisions) is not int or not 0 <= max_revisions <= 3:
        raise ValueError('practical_revision_policy_invalid')
    view = PracticalModelView(packet)
    typed_options = {'typed_findings': True} if typed_findings else {}
    review_options = {**typed_options, **({'counterexamples': True} if counterexamples else {})}
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
    # Invocation-local memo: source, route and policy cannot change in this call.
    # Resumption reconstructs it only by replaying the owned immutable stages.
    reviewed_parts: dict[str, dict[str, Any]] = {}
    for revision in range(max_revisions + 1):
        digest = _hash(candidate)
        seen.add(digest)
        by_lesson, global_previous = partition_previous(candidate, packet, previous, standalone=standalone, typed_findings=typed_findings)
        parts = []
        carried = []
        for lesson in candidate['lessons']:
            part = {'title': candidate['title'], 'lessons': [copy.deepcopy(lesson)]}
            prior = by_lesson[lesson['id']]
            def validate_part(value: dict[str, Any], checked: dict[str, Any] = part,
                              checked_prior: tuple[dict[str, Any], ...] = prior) -> None:
                interpret_practical_review(value, packet, checked, checked_prior, concise=True, strict_targets=True,
                                           **({'standalone': True} if standalone else {}), **review_options)
            review_version = ('v3-practical-source-review-v18' if counterexamples else
                              'v3-practical-source-review-v17' if typed_findings else
                              'v3-practical-source-review-v16' if standalone else 'v3-practical-source-review-v14')
            group = 'practical:review:' + _hash([review_version, part, prior])
            part_key = _hash([packet.fingerprint, part])
            if adjudicate and part_key in reviewed_parts:
                raw_review = reviewed_parts[part_key]
                result = copy.deepcopy(raw_review)
                result.pop('issue_checks', None)
                if prior:
                    result['issue_checks'] = {item['issue_id']: {'status': 'OPEN',
                        'reason': 'Unchanged lesson: carried review does not establish issue resolution.'} for item in prior}
                validate_part(result)
                carried.append({'lesson_id': lesson['id'], 'part_sha256': part_key,
                    'raw_review_sha256': _hash(raw_review), 'open_issue_ids': [item['issue_id'] for item in prior]})
            else:
                result = await call('review', group,
                    practical_review_messages(packet, part, prior, model_view=view, concise=True, lesson_scoped=True,
                        standalone=standalone, strict_targets=standalone, typed_findings=typed_findings,
                        counterexamples=counterexamples),
                    practical_review_format(packet, part, prior, concise=True, strict_targets=True,
                        **({'standalone': True} if standalone else {}), **review_options), validate_part)
                if adjudicate:
                    reviewed_parts[part_key] = copy.deepcopy(result)
            parts.append(result)
        def validate_global(value: dict[str, Any], checked: dict[str, Any] = candidate,
                            prior: tuple[dict[str, Any], ...] = global_previous) -> None:
            validate_atomic_audit(value, packet, checked, prior, **typed_options)
        audit = await call('review', 'practical:source-audit:' + _hash([review_version, candidate, global_previous]),
            atomic_audit_messages(packet, candidate, global_previous, model_view=view, **typed_options),
            atomic_audit_format(packet, candidate, global_previous, **typed_options), validate_global)
        narrative = atomic_audit_narrative_sources(audit, packet, candidate, global_previous, taught_only=standalone, **typed_options)
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
            consolidated['narrative_sources'][lesson_id] = (narrative[lesson_id] if standalone else list(dict.fromkeys(
                [*part['narrative_sources'][lesson_id], *narrative[lesson_id]])))
            for key, value in part.get('issue_checks', {}).items():
                if key in issue_checks:
                    raise ValueError('practical_lesson_issue_inventory_invalid')
                issue_checks[key] = value
        consolidated['source_notes'].extend(audit['source_notes'])
        consolidated['findings'].extend(compiled_atomic_audit_findings(audit, packet, candidate, global_previous, **typed_options))
        for key, value in audit.get('issue_checks', {}).items():
            if key in issue_checks:
                raise ValueError('practical_lesson_issue_inventory_invalid')
            issue_checks[key] = value
        if set(issue_checks) != {item['issue_id'] for item in previous}:
            raise ValueError('practical_lesson_issue_inventory_invalid')
        if previous:
            consolidated['issue_checks'] = issue_checks
        decision = interpret_practical_review(consolidated, packet, candidate, previous, concise=True,
                                             **({'allow_empty_narrative': True} if standalone else {}), **review_options)
        if adjudicate:
            decision = retain_prior_findings(decision, previous, issue_checks)
        adjudication = None
        if adjudicate and decision.feedback:
            modes = [('course', decision.feedback, False)]
            if standalone:
                classifier = answer_finding if typed_findings else question_finding
                modes = [(label, tuple(item for item in decision.feedback if classifier(item) is question_only), question_only)
                         for label, question_only in [('questions', True), ('course', False)]]
            applied = []
            adjudications = {}
            for label, allegations, question_only in modes:
                if not allegations:
                    continue
                unadjudicated = replace(decision, feedback=allegations)
                def validate_adjudication(value: dict[str, Any], checked_course: dict[str, Any] = candidate,
                                          checked_decision: Any = unadjudicated,
                                          checked_narrative: Any = consolidated['narrative_sources'],
                                          checked_question_only: bool = question_only) -> None:
                    adjudicate_practical_findings(value, packet, checked_course, checked_decision, checked_narrative,
                                                 selectors=standalone, question_only=checked_question_only, **typed_options)
                response = await call('review', 'practical:arbitrate:' + _hash([digest, unadjudicated.feedback]),
                    arbitration_messages(packet, candidate, unadjudicated, model_view=view, selectors=standalone,
                        question_only=question_only, counterexamples=counterexamples, **typed_options),
                    arbitration_format(packet, candidate, unadjudicated, selectors=standalone, question_only=question_only, **typed_options), validate_adjudication)
                applied.append(adjudicate_practical_findings(response, packet, candidate, unadjudicated,
                    consolidated['narrative_sources'], selectors=standalone, question_only=question_only, **typed_options))
                adjudications[label] = response
            if len(applied) == 1:
                decision = applied[0]
            else:
                decision = PracticalReviewDecision(all(item.accepted for item in applied), any(item.source_uncertain for item in applied),
                    tuple(dict.fromkeys(lid for item in applied for lid in item.lesson_ids)),
                    tuple(dict.fromkeys(qid for item in applied for qid in item.question_ids)),
                    any(item.allow_new_lessons for item in applied), tuple(issue for item in applied for issue in item.feedback),
                    tuple(dict.fromkeys(lid for item in applied for lid in item.assessment_lesson_ids)))
            adjudication = adjudications if standalone else adjudications['course']
        history.append({'course_sha256': digest, 'lesson_reviews': parts, 'atomic_audit': audit,
                        'consolidated_review': consolidated, 'accepted': decision.accepted,
                        'source_uncertain': decision.source_uncertain})
        if adjudicate:
            history[-1].update(adjudication=adjudication, carried_reviews=carried)
        editable = bool(decision.lesson_ids or decision.question_ids or decision.assessment_lesson_ids
                        or adjudicate and decision.allow_new_lessons and not decision.source_uncertain)
        reason = ('accepted' if decision.accepted else 'source_uncertain'
                  if decision.source_uncertain and (not editable or not adjudicate and revision == max_revisions)
                  else 'revision_limit' if revision == max_revisions else '')
        if reason:
            return PracticalCycleResult(candidate, consolidated, decision, tuple(history), reason,
                                        (), False, True, lesson_scoped_review=True, arbitrated_review=adjudicate, standalone_review=standalone,
                                        typed_findings=typed_findings, counterexample_review=counterexamples)
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
                                        (), False, True, lesson_scoped_review=True, arbitrated_review=adjudicate, standalone_review=standalone,
                                        typed_findings=typed_findings, counterexample_review=counterexamples)
        candidate = revised
        previous = decision.feedback
    raise AssertionError('unreachable')
