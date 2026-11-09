"""One source-bound editorial issue registry; no inference or semantic guessing."""
from __future__ import annotations

import copy
import re
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.revision_policy import AUTONOMOUS_EDITORIAL_REVIEW_POLICY, is_autonomous_editorial_policy
from app.modules.courses.draft_review import DRAFT_REVIEW_VERSION


def editorial_manifest(result: Any, packet: Any, integrity_issues: list[str], *,
                       review_policy: str = AUTONOMOUS_EDITORIAL_REVIEW_POLICY) -> dict[str, Any]:
    history = result.history[0] if result.history else {}
    autonomous = history.get('autonomous_editorial') is True
    current_fingerprint = _digest(result.course) if autonomous else ''
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
        observation = case.get('case_description') or evidence.get('reason') or evidence.get('basis') or ''
        if evidence.get('status') == 'EDITED_UNVERIFIED':
            observation = 'Адресная правка внесена; её результат ещё требует проверки.\n' + observation
        elif evidence.get('status') == 'SOURCE_UNRESOLVED':
            observation = 'Замечание к исходному документу не закрывается автоматической правкой курса.\n' + observation
        if evidence.get('correction'):
            observation += '\nПредложение редактора: ' + evidence['correction']
        explanation = {'unverified': True, 'observation': observation,
            'missing_condition': case.get('unstated_condition') or '',
            'possible_answers': [question['choices'][i] for i in options
                                 if question and type(i) is int and 0 <= i < len(question['choices'])],
            'source_quotes': [b.text for b in packet.blocks if b.block_id in refs]}
        if autonomous:
            explanation.update(review_domain=evidence.get('domain'), review_status=evidence.get('status'),
                resolution_owner='source_owner' if evidence.get('status') == 'SOURCE_UNRESOLVED' else 'model')
        problem = str(evidence.get('problem') or finding['scope'])
        if evidence.get('status') == 'SOURCE_UNRESOLVED' and evidence.get('source_question'):
            problem = str(evidence['source_question'])
        elif evidence.get('status') == 'AUTOMATIC_REVIEW_UNRESOLVED':
            problem = 'Автоматическая редактура не завершена: ' + problem
        message = ('Проверьте однозначность ответа в этой учебной ситуации.'
                   if problem == 'option_answerability_unresolved' else problem)
        add('finding', target, message, refs, target_title=title, evidence=explanation,
            issue_id=finding['issue_id'])
    structured_summaries = {row['scope'] + ':' + row['id'] for row in result.decision.feedback}
    for issue in integrity_issues:
        if issue not in structured_summaries and issue != 'source_core_source_review_pending' and not issue.startswith(
                ('source_core_case_unresolved:', 'curriculum_coverage_unresolved:', 'question_context_unresolved:')):
            message = ('Проверьте актуальные привязки переработанных объяснений к источникам.'
                       if issue == 'practical_lesson_prose_provenance_requires_review' else issue)
            add('integrity', '', message, [])
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
    current_source_notes = list(result.review.get('source_notes', []))
    final_blind = history.get('final_blind_review') if autonomous else None
    blind_notes = final_blind.get('source_notes', []) if isinstance(final_blind, dict) else []
    if not isinstance(blind_notes, list):
        blind_notes = []
    blind_course_fp = history.get('final_blind_current_course_fingerprint')
    blind_hash = history.get('final_blind_input_hash')
    blind_current = (autonomous and blind_course_fp == current_fingerprint and isinstance(blind_hash, str)
                     and re.fullmatch(r'[0-9a-fA-F]{64}', blind_hash) is not None)
    if blind_current:
        known = {_digest([row['note'], row['source_refs']]) for row in current_source_notes}
        for row in blind_notes:
            if not isinstance(row, dict) or not isinstance(row.get('note'), str) or not isinstance(row.get('source_refs'), list):
                continue
            signature = _digest([row['note'], row['source_refs']])
            if signature not in known:
                current_source_notes.append(row)
                known.add(signature)
    for row in current_source_notes:
        evidence = ({'unverified': True, 'historical': False, 'reviewed_course_fingerprint': current_fingerprint,
                     'reviewed_target_kind': 'source', 'reviewed_target_id': ''} if autonomous else None)
        add('source_observation', '', row['note'], row['source_refs'], blocking=False, evidence=evidence)
    for stage in ('initial_bank', 'final_bank'):
        bank = history.get(stage, {})
        for row in bank.get('source_notes', []):
            add('source_observation', '', row['note'], row['source_refs'], blocking=False)
        summary = bank.get('source_review')
        if isinstance(summary, str) and summary.strip():
            add('self_review_summary', stage, summary, [], blocking=False)
    editorial = history.get('editorial_review', {})
    for row in editorial.get('findings', []):
        if row['severity'] == 'advisory':
            evidence = {'unverified': True, 'observation': row['basis'] + '\n' + row['correction']}
            if autonomous:
                evidence.update(historical=False, reviewed_course_fingerprint=current_fingerprint,
                                reviewed_target_kind=row['target']['kind'], reviewed_target_id=row['target']['id'])
            add('editorial_suggestion', row['target']['id'], row['problem'], row['source_refs'], blocking=False,
                evidence=evidence)
    if autonomous:
        # Earlier model observations are evidence of an earlier review, not a
        # statement about the revised course. The driver supplies each reviewed
        # candidate's fingerprint; legacy v33 history still has the initial one.
        snapshots = history.get('editorial_observation_history', [])
        if not isinstance(snapshots, list):
            snapshots = []
        initial = history.get('initial_editorial_review')
        original = history.get('editorial_original_course')
        if isinstance(initial, dict) and isinstance(original, dict):
            snapshots = [{'course_fingerprint': _digest(original), 'review': initial}, *snapshots]
        if blind_notes and not blind_current:
            known_fp = blind_course_fp if isinstance(blind_course_fp, str) and re.fullmatch(r'[0-9a-f]{64}', blind_course_fp) else None
            snapshots = [*snapshots, {'course_fingerprint': known_fp, 'allow_unknown_fingerprint': True,
                                      'review': {'findings': [], 'source_notes': blind_notes}}]
        current_findings = {_digest([r.get('target'), r.get('problem'), r.get('basis'), r.get('correction'), r.get('source_refs')])
                            for r in editorial.get('findings', []) if r.get('severity') == 'advisory'}
        current_issue_ids = {(r['issue_id'], r['target']['kind'], r['target']['id'])
                             for r in editorial.get('findings', []) if r.get('severity') == 'advisory'
                             and isinstance(r.get('issue_id'), str) and isinstance(r.get('target'), dict)
                             and isinstance(r['target'].get('kind'), str) and isinstance(r['target'].get('id'), str)}
        current_notes = {_digest([r.get('note'), r.get('source_refs')]) for r in current_source_notes}
        seen = set()
        for snapshot in reversed(snapshots):
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get('review'), dict):
                continue
            fingerprint = snapshot.get('course_fingerprint')
            if not (isinstance(fingerprint, str) and len(fingerprint) == 64) and not (
                fingerprint is None and snapshot.get('allow_unknown_fingerprint') is True
            ):
                continue
            reviewed = snapshot['review']
            for row in reversed(reviewed.get('findings', [])):
                if not isinstance(row, dict) or row.get('severity') != 'advisory':
                    continue
                target = row.get('target')
                if not isinstance(target, dict) or not all(isinstance(target.get(k), str) for k in ('kind', 'id')):
                    continue
                if not all(isinstance(row.get(k), str) for k in ('problem', 'basis', 'correction')) or not isinstance(row.get('source_refs'), list):
                    continue
                signature = _digest([target, row['problem'], row['basis'], row['correction'], row['source_refs']])
                identity = (row['issue_id'], target['kind'], target['id']) if isinstance(row.get('issue_id'), str) and row['issue_id'] else None
                key = ('finding', fingerprint, identity or signature)
                if signature in current_findings or identity in current_issue_ids or key in seen:
                    continue
                seen.add(key)
                add('editorial_suggestion', target['id'], 'Ранее отмечено; не подтверждено для текущей версии: ' + row['problem'],
                    row['source_refs'], blocking=False, evidence={'unverified': True, 'historical': True,
                    'reviewed_course_fingerprint': fingerprint, 'reviewed_target_kind': target['kind'],
                    'reviewed_target_id': target['id'], 'observation': row['basis'] + '\n' + row['correction']})
            for row in reviewed.get('source_notes', []):
                if not isinstance(row, dict) or not isinstance(row.get('note'), str) or not isinstance(row.get('source_refs'), list):
                    continue
                signature = _digest([row['note'], row['source_refs']])
                key = ('source_note', fingerprint, signature)
                if signature in current_notes or key in seen:
                    continue
                seen.add(key)
                add('source_observation', '', 'Ранее отмечено; не подтверждено для текущей версии: ' + row['note'],
                    row['source_refs'], blocking=False, evidence={'unverified': True, 'historical': True,
                    'reviewed_course_fingerprint': fingerprint, 'reviewed_target_kind': 'source', 'reviewed_target_id': ''})
    if editorial.get('summary'):
        add('self_review_summary', 'editorial', editorial['summary'], [], blocking=False)
    revision = history.get('editorial_revision', {})
    for target in revision.get('ignored_unrequested_changes', []):
        add('protected_content', target, 'Незапрошенная правка не применена; исходная часть сохранена.', [], blocking=False)
    for target in revision.get('retained_missing_targets', []):
        add('retained_content', target, 'Часть не возвращена редактором; сохранена исходная версия для проверки.', [], blocking=False)
    # Publication remains an ordinary explicit approval. It is not an unresolved
    # model defect when the exact current candidate has passed both reviews.
    automated_pass = (autonomous and is_autonomous_editorial_policy(review_policy)
        and result.decision.accepted and not integrity_issues
        and history.get('verified_course_fingerprint') == _digest(result.course))
    if not automated_pass:
        add('editorial_review', '', 'Проверьте содержание уроков, ключи тестов и соответствие источникам.', [])
    return {'version': DRAFT_REVIEW_VERSION, 'generation_status': 'draft_prepared',
            'self_review_status': 'passed' if result.decision.accepted and not integrity_issues else 'needs_attention',
            'human_review_required': True, 'source_fingerprint': packet.fingerprint,
            'draft_fingerprint': _digest(result.course), 'issues': list(rows.values()),
            'observations': list(observations.values()),
            **({'content_review_required': not automated_pass,
                'source_clarification_required': result.decision.source_uncertain} if autonomous else {}),
            **({'automated_acceptance': {'policy': review_policy,
                'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(result.course)}}
                if automated_pass else {})}
