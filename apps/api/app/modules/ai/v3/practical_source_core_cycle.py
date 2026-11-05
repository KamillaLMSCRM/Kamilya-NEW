"""Source-core generation using existing, journal-owned practical stages."""
from __future__ import annotations

import copy
import json
from typing import Any, cast

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_curriculum import (
    compile_curriculum_findings,
    curriculum_bank_format,
    curriculum_bank_messages,
    curriculum_format,
    curriculum_messages,
    validate_curriculum,
)
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import PracticalReviewDecision, _issue, interpret_practical_review
from app.modules.ai.v3.practical_source_core import prepare_source_core_request, source_core_blueprint
from app.modules.ai.v3.practical_source_core_editor import _case_inventory, prepare_source_core_editor


def _review_projection(course: dict[str, Any], cases: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(course)
    for lesson in projected['lessons']:
        practice_id = lesson['id'] + 'P1'
        practice = copy.deepcopy(cases[practice_id])
        lesson['questions'].append({'id': practice_id, **practice, 'explanation': 'Practice case.'})
    return projected


def _review_bank(value: dict[str, Any], packet: Any, course: dict[str, Any], plan: dict[str, Any],
                 previous: tuple[dict[str, Any], ...]) -> tuple[PracticalReviewDecision, tuple[str, ...]]:
    # Goal coverage is checked by goal_checks, not the answer-validity contract.
    # The complete original registry remains with the cycle for retention/history.
    previous = tuple(row for row in previous if row['scope'] != 'assessment')
    findings, unowned = compile_curriculum_findings(value, packet, course, plan, previous, include_goal_identity=True)
    base = {key: item for key, item in value.items() if key not in {'goal_checks', 'curriculum_fingerprint'}}
    decision = interpret_practical_review(base, packet, course, previous, concise=True, strict_targets=True,
        standalone=True, typed_findings=True, counterexamples=True, question_batch=True)
    rows = list(decision.feedback) + [_issue('assessment', row['target_id'], row) for row in findings]
    # A formative example is never an independent assessment witness.
    practice_ids = {q['id'] for lesson in course['lessons'] for q in lesson['questions'] if q['id'].endswith('P1')}
    unverified = [row['goal_id'] for row in value['goal_checks'] if row['status'] == 'COVERED'
                  and not (set(row['question_ids']) - practice_ids)]
    unique = {row['issue_id']: row for row in rows}
    return PracticalReviewDecision(not unique and not unowned and not unverified,
        any(row['scope'] == 'source' for row in unique.values()), (), (), False, tuple(unique.values())), tuple(dict.fromkeys((*unowned, *unverified)))


def _finding_targets(findings: tuple[dict[str, Any], ...], cases: dict[str, Any], owners: dict[str, str],
                     view: PracticalModelView | None = None) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    for finding in findings:
        scope, target = finding['scope'], finding['id']
        ids = ([target] if scope == 'question' and target in cases else
               [key for key, owner in owners.items() if owner == target and 'Q' in key] if scope == 'assessment' else [])
        for key in ids:
            evidence = copy.deepcopy(finding['evidence'])
            evidence.pop('goal_id', None)  # Server-only retention identity, not new editor guidance.
            evidence = view.encode(evidence) if view is not None else evidence
            targets.setdefault(key, []).append(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return targets


def _retain_unverified(initial: tuple[dict[str, Any], ...], final: tuple[dict[str, Any], ...],
                       changed: set[str], owners: dict[str, str],
                       goal_checks: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    retained = list(final)
    final_ids = {row['issue_id'] for row in retained}
    final_question_issues = {row['id'] for row in final if row['scope'] == 'question'}
    for row in initial:
        if row['issue_id'] in final_ids:
            continue
        if row['scope'] == 'assessment' and goal_checks is not None:
            goal = goal_checks.get(row['evidence'].get('goal_id'))
            witnesses = set(goal['question_ids']) & changed - final_question_issues if goal else set()
            if not goal or goal['status'] != 'COVERED' or not any(not key.endswith('P1') for key in witnesses):
                retained.append(row)
            continue
        relevant = ({row['id']} if row['scope'] == 'question' else
                    {key for key, owner in owners.items() if row['scope'] == 'assessment' and owner == row['id']
                     and not key.endswith('P1')})
        reviewed = relevant & changed
        if (row['scope'] not in {'question', 'assessment'} or not reviewed
                or reviewed & final_question_issues):
            retained.append(row)
    return retained


def _finding_case_context(initial: tuple[dict[str, Any], ...], final: tuple[dict[str, Any], ...],
                          initial_cases: dict[str, Any], final_cases: dict[str, Any],
                          owners: dict[str, str], lessons: list[dict[str, Any]]) -> dict[str, Any]:
    """Option indices belong to the exact case version seen by that reviewer."""
    titles = {lesson['id']: lesson['title'] for lesson in lessons}
    result = {}
    for round_name, findings, cases in (('initial', initial, initial_cases), ('final', final, final_cases)):
        for finding in findings:
            key = finding['id']
            if key in cases and finding['issue_id'] not in result:
                row = cases[key]
                result[finding['issue_id']] = {'lesson_title': titles[owners[key]],
                    'prompt': row['prompt'], 'choices': copy.deepcopy(row['choices']),
                    'source_refs': copy.deepcopy(row['source_refs']), 'review_round': round_name,
                    'case_fingerprint': _digest([row['prompt'], row['choices'], row['source_refs']])}
    return result


async def run_source_core_cycle(packet: Any, corpus: Any, intent: Any, reference_decisions: tuple[Any, ...],
                                stage: Any) -> PracticalCycleResult:
    view = PracticalModelView(packet)
    async def call(stage_name: str, group: str, messages: list[dict[str, str]], fmt: dict[str, Any], validate: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await stage(stage_name, group, messages, fmt, validate))

    fmt = view.schema(curriculum_format(packet))
    plan_wire = await call('review', 'practical:source-curriculum:v30', curriculum_messages(packet, view, family_coverage=True),
        fmt, lambda value: validate_curriculum(view.decode(value), packet))
    plan = validate_curriculum(view.decode(plan_wire), packet)
    title = corpus.documents[0].title.strip() or 'Практический учебный курс'
    core = prepare_source_core_request(packet, plan, course_title=title, intent=intent,
        corpus=corpus, reference_decisions=reference_decisions)
    request = core.request()
    author_wire = await call('lesson', 'practical:source-core:author:v30', request['messages'], request['response_format'],
        lambda value: core.compile_response(value, sent_request=request))
    course, core_meta = core.compile_response(author_wire, sent_request=request)
    cases = _case_inventory(view.decode(author_wire))

    async def bank(candidate: dict[str, Any], checked_cases: dict[str, Any], prior: tuple[dict[str, Any], ...], label: str
                   ) -> tuple[dict[str, Any], PracticalReviewDecision, tuple[str, ...]]:
        projected = _review_projection(candidate, checked_cases)
        answer_prior = tuple(row for row in prior if row['scope'] != 'assessment')
        messages = curriculum_bank_messages(packet, projected, plan, answer_prior, model_view=view, family_coverage=True)
        messages[0]['content'] += ('\nУчебные примеры с ID P1 проверяй на однозначность отдельно; '
                                  'не считай их вопросами итоговой оценки и не используй для goal_checks COVERED.')
        messages[1]['content'] += '\nPRACTICE_CASE_IDS_JSON\n' + json.dumps([k for k in checked_cases if k.endswith('P1')])
        wire_fmt = view.schema(curriculum_bank_format(packet, projected, plan, answer_prior))
        def validate(value: dict[str, Any]) -> None:
            _review_bank(view.decode(value), packet, projected, plan, prior)
        raw = await call('review', 'practical:review:bank:v30:' + label + ':' + _digest(projected), messages, wire_fmt, validate)
        decoded = view.decode(raw)
        result, unresolved = _review_bank(decoded, packet, projected, plan, prior)
        return decoded, result, unresolved

    initial_raw, initial, initial_unresolved = await bank(course, cases, (), 'initial')
    case_owner = {key: lesson['id'] for lesson in course['lessons'] for key in cases if key.startswith(lesson['id'] + 'Q') or key == lesson['id'] + 'P1'}
    targets = _finding_targets(initial.feedback, cases, case_owner, view)
    guidance = tuple({'case_id': key,
        'note': '\n'.join(notes) + '\nЕсли конкретный случай уже корректен, сохрани его без изменения.',
        'origin': 'AUTOMATIC_FINDING'} for key, notes in targets.items())
    editor = prepare_source_core_editor(core, author_wire, request, target_ids=tuple(targets), guidance=guidance)
    edit_request = editor.request()
    edit_wire = await call('review', 'practical:source-core:editor:v30', edit_request['messages'], edit_request['response_format'],
        lambda value: editor.compile_response(value, sent_request=edit_request, allow_partial=True))
    updated, edit_meta = editor.compile_response(edit_wire, sent_request=edit_request, allow_partial=True)
    final_cases = copy.deepcopy(cases)
    for row in view.decode(edit_wire)['replacements']:
        if row['case_id'] not in edit_meta['unresolved_cases']:
            final_cases[row['case_id']] = row['question']
    changed = {key for key in cases if any(cases[key][field] != final_cases[key][field]
                                          for field in ('prompt', 'choices', 'correct_index'))}
    final_raw, final, final_unresolved = await bank(updated, final_cases, initial.feedback, 'final')
    final_goals = {row['goal_id']: row for row in final_raw['goal_checks']}
    retained = _retain_unverified(initial.feedback, final.feedback, changed, case_owner, final_goals)
    final_question_issues = {row['id'] for row in final.feedback if row['scope'] == 'question'}
    for goal in initial_unresolved:
        row = final_goals[goal]
        reviewed = set(row['question_ids']) & changed - final_question_issues
        if row['status'] != 'COVERED' or not any(not key.endswith('P1') for key in reviewed):
            final_unresolved = tuple(dict.fromkeys((*final_unresolved, goal)))
    source_review_pending = bool(plan['source_uncertainties'] or edit_meta['global_source_proposals_unverified']
                                 or edit_meta['unverified_discovered_dependencies'])
    decision = PracticalReviewDecision(not retained and not final_unresolved and not edit_meta['unresolved_cases']
        and not source_review_pending,
        any(x['scope'] == 'source' for x in retained),
        (), (), False, tuple(retained))
    blueprint = source_core_blueprint(packet, plan, course_title=title, corpus=corpus, reference_decisions=reference_decisions)
    observed_notes = {_digest(row): row for raw in (initial_raw, final_raw) for row in raw['source_notes']}
    review = {'source_notes': list(observed_notes.values()),
              'narrative_sources': {lesson['id']: lesson['source_refs'] for lesson in blueprint['lessons']}}
    history = ({'initial_bank': initial_raw, 'initial_findings': list(initial.feedback), 'initial_unresolved_goals': initial_unresolved,
                'final_bank': final_raw, 'editor_raw_response': edit_wire,
                'editor_custody': edit_meta, 'source_core_custody': core_meta,
                'finding_case_context': _finding_case_context(initial.feedback, final.feedback, cases,
                                                               final_cases, case_owner, updated['lessons']),
                'case_context': {key: {'lesson_title': next(lesson['title'] for lesson in updated['lessons']
                                                          if lesson['id'] == case_owner[key]),
                                       'prompt': row['prompt'], 'choices': copy.deepcopy(row['choices']),
                                       'source_refs': copy.deepcopy(row['source_refs'])}
                                 for key, row in final_cases.items()},
                'changed_case_ids': sorted(changed)},)
    return PracticalCycleResult(updated, review, decision, history, 'reviewed' if decision.accepted else 'needs_review',
        standalone_review=True, question_bank_review=True, curriculum_plan=plan,
        unresolved_curriculum_goals=final_unresolved, source_core=True,
        source_core_unresolved_cases=tuple(edit_meta['unresolved_cases']),
        source_core_source_review_pending=source_review_pending)
