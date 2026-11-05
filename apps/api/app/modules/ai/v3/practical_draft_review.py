"""One source-bound editorial issue registry; no inference or semantic guessing."""
from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.courses.draft_review import DRAFT_REVIEW_VERSION


def editorial_manifest(result: Any, packet: Any, integrity_issues: list[str]) -> dict[str, Any]:
    history = result.history[0] if result.history else {}
    custody = history.get('editor_custody', history.get('source_core_custody', {}))
    rows: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}

    def add(kind: str, target: str, message: str, refs: list[str], *, blocking: bool = True,
            target_title: str = '', evidence: dict[str, Any] | None = None, issue_id: str = '') -> None:
        identity = 'p30-' + _digest([kind, target, message, refs, evidence, issue_id])[:24]
        row = {'id': identity, 'kind': kind, 'target_id': target, 'message': message,
               'source_refs': list(dict.fromkeys(refs)), 'blocking': blocking,
               'target_title': target_title, 'evidence': copy.deepcopy(evidence or {})}
        (rows if blocking else observations)[identity] = row

    for finding in result.decision.feedback:
        evidence = finding.get('evidence', {})
        target = finding['id']
        lesson = next((row for row in result.course['lessons']
                       if row['id'] == target or any(q['id'] == target for q in row['questions'])), None)
        question = next((q for q in lesson['questions'] if q['id'] == target), None) if lesson else None
        context = history.get('finding_case_context', {}).get(finding['issue_id'])
        initial_ids = {row['issue_id'] for row in history.get('initial_findings', [])}
        if context is None and finding['issue_id'] in initial_ids:
            # Historical indices must never be translated through edited choices.
            question = None
        elif context is None:
            context = history.get('case_context', {}).get(target)
        if context is not None:
            question = context
        title = ((context['lesson_title'] + ': ' + context['prompt']) if context else
                 (lesson['title'] + ': ' + question['prompt']) if lesson and question
                 else lesson['title'] if lesson else target)
        case = evidence.get('counterexample') or {}
        refs = list(dict.fromkeys([*(evidence.get('source_refs') or []), *(case.get('source_refs') or [])]))
        if not refs and question:
            refs = list(question.get('source_refs', []))
        options = case.get('possible_options') or evidence.get('possible_options') or []
        explanation = {'unverified': True, 'observation': case.get('case_description') or evidence.get('reason') or '',
            'missing_condition': case.get('unstated_condition') or '',
            'possible_answers': [question['choices'][i] for i in options
                                 if question and type(i) is int and 0 <= i < len(question['choices'])],
            'source_quotes': [b.text for b in packet.blocks if b.block_id in refs]}
        problem = str(evidence.get('problem') or finding['scope'])
        message = ('Проверьте однозначность ответа в этой учебной ситуации.'
                   if problem == 'option_answerability_unresolved' else problem)
        add('finding', target, message, refs, target_title=title, evidence=explanation,
            issue_id=finding['issue_id'])
    for issue in integrity_issues:
        if issue != 'source_core_source_review_pending' and not issue.startswith(
                ('source_core_case_unresolved:', 'curriculum_coverage_unresolved:', 'question_context_unresolved:')):
            add('integrity', '', issue, [])
    for case in result.source_core_unresolved_cases:
        add('case_review', case, 'Автоматическая правка этой учебной ситуации не подтверждена: ' + case, [])
    for goal in result.unresolved_curriculum_goals:
        add('coverage_review', goal, 'Проверьте раскрытие учебной цели: ' + goal, [])
    for question in result.unresolved_question_context:
        add('question_context', question, 'Проверьте полноту условий вопроса: ' + question, [])
    plan = result.curriculum_plan or {}
    for row in plan.get('source_uncertainties', []):
        add('source_uncertainty', '', row['note'], row['source_refs'])
    for row in custody.get('global_source_proposals_unverified', []):
        add('source_proposal', row['document_id'], row['text'], [])
    for row in custody.get('unverified_discovered_dependencies', []):
        add('discovered_dependency', row['lesson_id'],
            'Проверьте дополнительную связь с другим разделом источника.', row['source_refs'])
    for unit in custody.get('auxiliary_units_unverified', []):
        add('auxiliary_context', unit, 'Вспомогательный блок сохранён как контекст урока.', [], blocking=False)
    for row in result.review.get('source_notes', []):
        add('source_observation', '', row['note'], row['source_refs'], blocking=False)
    for stage in ('initial_bank', 'final_bank'):
        bank = history.get(stage, {})
        for row in bank.get('source_notes', []):
            add('source_observation', '', row['note'], row['source_refs'], blocking=False)
        summary = bank.get('source_review')
        if isinstance(summary, str) and summary.strip():
            add('self_review_summary', stage, summary, [], blocking=False)
    # A clean machine result still needs a real methodologist's sign-off.
    add('editorial_review', '', 'Проверьте содержание уроков, ключи тестов и соответствие источникам.', [])
    return {'version': DRAFT_REVIEW_VERSION, 'generation_status': 'draft_prepared',
            'self_review_status': 'passed' if result.decision.accepted and not integrity_issues else 'needs_attention',
            'human_review_required': True, 'source_fingerprint': packet.fingerprint,
            'draft_fingerprint': _digest(result.course), 'issues': list(rows.values()),
            'observations': list(observations.values())}
