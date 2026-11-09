"""Conditional draft cycle; all graph observations remain unverified."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from app.modules.ai.v3 import practical_action_object_graph as graph
from app.modules.ai.v3 import practical_attachment_planner as attachment
from app.modules.ai.v3 import practical_question_editor as question_editor
from app.modules.ai.v3.isolated_attachment_choice_contract import matches_attachment_choice_response
from app.modules.ai.v3.practical_coherent_editorial_cycle import blind_review_units, coherent_author_request
from app.modules.ai.v3.practical_contract import (
    _digest,
    build_practical_source_packet,
    normalize_author_question_ids,
    validate_practical_course,
)
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_editorial_cycle import CASE_STATUS_REVIEW_GUIDE, _context
from app.modules.ai.v3.practical_focused_graph import action_query, focused_editor_request, graph_records, noun_query
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_option_predicates import (
    interpret_option_predicates,
    option_predicates_format,
    option_predicates_messages,
)
from app.modules.ai.v3.practical_owned_media_aliases import _images, _plain_mentions
from app.modules.ai.v3.practical_prose_revision import compile_prose_revision
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_source_semantic_cycle import SOURCE_AUTHORITY_GUIDE


def _protect_prose(before: dict[str, Any], after: dict[str, Any]) -> None:
    if before['title'] != after['title'] or len(before['lessons']) != len(after['lessons']):
        raise ValueError('focused_protected_structure_changed')
    for left, right in zip(before['lessons'], after['lessons'], strict=True):
        if (left['id'], left['title'], left['questions']) != (right['id'], right['title'], right['questions']):
            raise ValueError('focused_protected_structure_changed')
        old, new = _images(left['content']), _images(right['content'])
        if ([row['markdown'] for row in old] != [row['markdown'] for row in new]
                or _plain_mentions(left['content'], old) != _plain_mentions(right['content'], new)):
            raise ValueError('focused_protected_media_changed')


def _with_question_uncertainty(packet: Any, course: dict[str, Any], receipt: dict[str, Any],
                               findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep explicit editor uncertainty actionable for this exact question revision."""
    fingerprint = _digest(course)
    if (receipt['source_fingerprint'] != packet.fingerprint
            or receipt['after_course_fingerprint'] != fingerprint):
        raise ValueError('focused_question_receipt_stale')
    questions = {q['id']: q for lesson in course['lessons'] for q in lesson['questions']}
    result = copy.deepcopy(findings)
    indexed = {(row['scope'], row['id']): row for row in result}
    for check in receipt['checks']:
        if check['status'] != 'UNVERIFIED':
            continue
        qid = check['question_id']
        question = questions[qid]
        evidence = {'problem': 'Редактор не подтвердил вопрос: ' + check['reason'],
            'reason': check['reason'], 'source_refs': list(question['source_refs']),
            'reviewed_course_fingerprint': fingerprint, 'reviewed_question_fingerprint': _digest(question),
            'producer': 'question_editor'}
        existing = indexed.get(('question', qid))
        if existing is not None:
            existing['evidence']['question_editor_unverified'] = evidence
            existing['evidence']['problem'] = (str(existing['evidence'].get('problem') or '')
                                               + '\n' + evidence['problem']).strip()
        else:
            row = {'issue_id': 'focused-question-' + _digest([packet.fingerprint, qid, evidence])[:24],
                   'scope': 'question', 'id': qid, 'evidence': evidence}
            result.append(row)
            indexed[('question', qid)] = row
    return result


async def run_focused_cycle(packet: Any, corpus: Any, intent: Any, reference_decisions: tuple[Any, ...],
                            stage: Any, *, max_output_tokens: int, max_revisions: int) -> PracticalCycleResult:
    """No global prose critic; always returns editorial pending, never auto approval.

    Action retrieval covers only the bound negative/object pattern. Noun retrieval
    covers selected stable-anchor candidates. Absence of either is not coverage.
    The caller owns journal, source/tenant/actor, route, and final-save fencing.
    """
    if type(max_output_tokens) is not int or max_output_tokens < 1024:
        raise ValueError('focused_output_budget_invalid')
    if type(max_revisions) is not int or not 1 <= max_revisions <= 5:
        raise ValueError('focused_revision_budget_invalid')
    if build_practical_source_packet(corpus, reference_decisions) != packet:
        raise ValueError('focused_source_custody_invalid')
    view = PracticalModelView(packet)
    context = _context(packet, corpus, view, canonical_json=True)

    def author(raw: Any) -> dict[str, Any]:
        value = view.decode(raw)
        view.assert_course_ids_disjoint(value)
        value = normalize_author_question_ids(value, set(view.canonical_to_alias))
        view.assert_course_ids_disjoint(value)
        return validate_practical_course(value, packet)

    messages, fmt = coherent_author_request(packet, intent, context, view)
    original = author(await stage('lesson', 'practical:focused:author:v36:' + _digest([messages, fmt]),
                                  messages, view.schema(fmt), author))
    source_records, learner_records, _ = graph_records(packet, original, view)

    async def graph_call(role: str, records: list[dict[str, str]]) -> dict[str, Any]:
        request, schema, _ = graph.request(role, records)
        def validator(raw: Any) -> dict[str, Any]:
            return graph.compile_response(raw, role, records)
        value = await stage('review', 'practical:focused:graph:' + role + ':v36:' + _digest([request, schema]),
                            request, schema, validator)
        return validator(value)

    source_graph = await graph_call('source', source_records)
    learner_graph = await graph_call('learner', learner_records)
    def with_hash(identifier: str, text: str) -> dict[str, str]:
        return {'id': identifier, 'text': text, 'sha256': hashlib.sha256(text.encode('utf8')).hexdigest()}
    source_owned = [with_hash(view.canonical_to_alias[b.block_id], b.text) for b in packet.blocks if b.text.strip()]
    learner_owned = [with_hash(lesson['id'], lesson['content']) for lesson in original['lessons']]
    planned = attachment.plan(source_owned, learner_owned, packet.fingerprint, _digest(original))
    choices: dict[str, list[dict[str, Any]]] = {'source': [], 'learner': []}
    for role in ('source', 'learner'):
        for item in planned[role + '_plans']:
            schema = item['response_format']
            def validate_choice(raw: Any, expected: Any = schema) -> None:
                if not matches_attachment_choice_response(raw, expected):
                    raise ValueError('focused_attachment_invalid')
            value = await stage('review', 'practical:focused:attachment:' + role + ':v36:'
                                + _digest([item['messages'], schema]), item['messages'], schema, validate_choice)
            validate_choice(value)
            choices[role].append(value)

    async def edit(before: dict[str, Any], query: dict[str, Any], role: str) -> dict[str, Any]:
        request, schema, allowed = focused_editor_request(packet, before, view, query, role)
        if request is None:
            return copy.deepcopy(before)
        def compile_edit(raw: Any) -> dict[str, Any]:
            value = compile_prose_revision(raw, packet, before, allowed)['course']
            validated = validate_practical_course(value, packet)
            _protect_prose(before, validated)
            return validated
        value = await stage('repair', 'practical:focused:' + role + ':v36:' + _digest([request, schema]),
                            request, schema, compile_edit)
        return compile_edit(value)

    action = action_query(packet, original, original, view, source_graph, learner_graph)
    candidate = await edit(original, action, 'action')
    noun = noun_query(packet, original, candidate, view, planned, choices['source'], choices['learner'])
    candidate = await edit(candidate, noun, 'noun')
    q_messages, q_fmt = question_editor.request(packet, candidate, view)
    q_value = await stage('repair', 'practical:focused:questions:v36:' + _digest([q_messages, q_fmt]),
                          q_messages, q_fmt, lambda raw: question_editor.compile(raw, packet, candidate, view))
    before_questions = candidate
    candidate, q_receipt = question_editor.compile(q_value, packet, before_questions, view)
    if [(learner_row['id'], learner_row['title'], learner_row['content']) for learner_row in candidate['lessons']] != [
            (learner_row['id'], learner_row['title'], learner_row['content']) for learner_row in before_questions['lessons']]:
        raise ValueError('focused_question_changed_prose')

    blind_cache: dict[str, Any] = {}
    async def blind_check(current: dict[str, Any]) -> list[dict[str, Any]]:
        findings = []
        for unit in blind_review_units(current, max_output_tokens):
            messages = option_predicates_messages(packet, unit, context, model_view=view)
            messages[0]['content'] += CASE_STATUS_REVIEW_GUIDE + SOURCE_AUTHORITY_GUIDE
            fmt = option_predicates_format(packet, unit)
            wire_fmt = view.schema(fmt)
            fingerprint = _digest([messages, wire_fmt])
            def check(raw: Any, owned: Any = unit) -> Any:
                return interpret_option_predicates(view.decode(raw), packet, owned)
            if fingerprint not in blind_cache:
                blind_cache[fingerprint] = await stage('review', 'practical:focused:blind:v36:' + fingerprint,
                                                       messages, wire_fmt, check)
            findings.extend(check(blind_cache[fingerprint]).feedback)
        return findings

    current_q_receipt = q_receipt
    blind_feedback = _with_question_uncertainty(packet, candidate, current_q_receipt, await blind_check(candidate))
    question_repairs = []
    seen = {_digest(candidate)}
    for _ in range(max_revisions):
        allowed_ids = {row['id'] for row in blind_feedback if row.get('scope') == 'question'}
        if not allowed_ids:
            break
        q_messages, q_fmt = question_editor.request(packet, candidate, view)
        q_messages[0]['content'] += ('\nИсправляй только перечисленные вопросы; остальные сохраняй. '
                                    'Замечания непроверены: сопоставь их с исходником.')
        observations = []
        for finding in blind_feedback:
            if finding.get('scope') != 'question':
                continue
            evidence = finding['evidence']
            observations.append({'question_id': finding['id'], 'problem': evidence.get('problem', ''),
                'correction': evidence.get('correction', ''), 'source_refs': evidence.get('source_refs', []),
                'option_judgments': [{key: row[key] for key in ('option_index', 'status', 'reason', 'source_refs', 'compatible_case')}
                                     for row in evidence.get('option_judgments', [])]})
        q_messages[1]['content'] += '\nUNVERIFIED_CURRENT_QUESTION_FINDINGS_JSON\n' + json.dumps(
            view.encode(observations),
            ensure_ascii=False, sort_keys=True)
        before_questions = candidate
        def scoped_question(raw: Any, owned: Any = before_questions, allowed: Any = frozenset(allowed_ids)) -> Any:
            proposed, receipt = question_editor.compile(raw, packet, owned, view)
            if not set(receipt['updated_question_ids']) <= allowed:
                raise ValueError('focused_question_repair_outside_scope')
            return proposed, receipt
        q_value = await stage('repair', 'practical:focused:question-repair:v36:' + _digest([q_messages, q_fmt]),
                              q_messages, q_fmt, scoped_question)
        proposed, receipt = scoped_question(q_value)
        question_repairs.append(receipt)
        if not receipt['updated_question_ids']:
            current_q_receipt = receipt
            blind_feedback = _with_question_uncertainty(packet, candidate, current_q_receipt,
                                                        await blind_check(candidate))
            break
        if _digest(proposed) in seen:
            break
        seen.add(_digest(proposed))
        candidate = proposed
        current_q_receipt = receipt
        blind_feedback = _with_question_uncertainty(packet, candidate, current_q_receipt, await blind_check(candidate))
    normalized_feedback = []
    for finding in blind_feedback:
        row = copy.deepcopy(finding)
        if row.get('scope') == 'question' and isinstance(row.get('evidence'), dict):
            original_evidence = copy.deepcopy(row['evidence'])
            row['evidence'].update({'status': 'AUTOMATIC_REVIEW_UNRESOLVED', 'domain': 'assessment',
                'target': {'kind': 'question', 'id': row['id']}, 'unverified_observation': original_evidence})
        normalized_feedback.append(row)
    review = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(candidate),
              'summary': 'Automated focused observations are unverified.', 'findings': [], 'source_notes': [],
              'narrative_sources': {lesson['id']: [] for lesson in candidate['lessons']}}
    history = ({'autonomous_editorial': True, 'focused_observations_unverified': True,
                'source_graph_fingerprint': source_graph['input_fingerprint'],
                'learner_graph_fingerprint': learner_graph['input_fingerprint'], 'action_pairs': len(action['pairs']),
                'noun_observations': len(noun['noun_observations']), 'question_receipt': q_receipt,
                'current_question_receipt': current_q_receipt,
                'question_repairs': question_repairs,
                'unverified_revised_prose': [lesson['id'] for lesson in candidate['lessons']],
                'coverage_limits': action['coverage_limits']},)
    decision = PracticalReviewDecision(False, False, (), (), False, tuple(normalized_feedback))
    return PracticalCycleResult(candidate, review, decision, history, 'focused_review_pending',
                                standalone_review=True, editorial_review=True)
