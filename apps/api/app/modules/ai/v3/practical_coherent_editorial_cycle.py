"""Literal-source author, whole-course editor, independent answers and owned repairs.

Derived interpretations are audit hypotheses, never substituted for the approved
source. All transport, ownership, recovery and publication stay with their owners.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any

from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_autonomous_editorial_cycle import (
    EDITORIAL_REASONING_GUIDE,
    _blind_findings,
    _edit_batches,
    _owner_source_questions,
    _scoped_edit_messages,
)
from app.modules.ai.v3.practical_contract import (
    _digest,
    build_practical_source_packet,
    course_response_format,
    normalize_author_question_ids,
    validate_practical_course,
)
from app.modules.ai.v3.practical_current_reconciliation import (
    finish_current_reconciliation,
    reconcile_current_editorial,
)
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_editorial_contract import (
    compile_editorial_review,
    compile_editorial_revision,
    editorial_review_format,
    editorial_revision_format,
)
from app.modules.ai.v3.practical_editorial_cycle import (
    AUTHOR_SYSTEM,
    CASE_STATUS_REVIEW_GUIDE,
    REVIEW_SYSTEM,
    _context,
)
from app.modules.ai.v3.practical_editorial_proof_correction import correct_resolution_proofs
from app.modules.ai.v3.practical_editorial_verification import (
    matches_editorial_verification,
    matches_editorial_verification_shape,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_option_predicates import (
    interpret_option_predicates,
    option_predicates_format,
    option_predicates_messages,
)
from app.modules.ai.v3.practical_resolution_completion import (
    complete_editorial_resolutions,
    is_joint_verification_group,
)
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_source_semantic_cycle import SOURCE_AUTHORITY_GUIDE


def coherent_author_request(packet: Any, intent: Any, context: str, view: Any) -> tuple[Any, Any]:
    planning = [{'unit_id': key, 'source_refs': list(refs)} for key, refs in audit_units(packet).groups]
    return ([{'role': 'system', 'content': AUTHOR_SYSTEM + EDITORIAL_REASONING_GUIDE + SOURCE_AUTHORITY_GUIDE},
        {'role': 'user', 'content': context + '\nSOURCE_LOGICAL_UNITS_JSON\n'
            + json.dumps(view.encode(planning), ensure_ascii=False, sort_keys=True)
            + '\nCOURSE_INTENT_JSON\n' + json.dumps(view.encode(asdict(intent)), ensure_ascii=False, sort_keys=True)}],
        course_response_format(packet))


def blind_review_units(course: dict[str, Any], max_output_tokens: int) -> list[dict[str, Any]]:
    """Pack whole lessons when possible; never split a question or discard material.

    256 tokens per judgment is a conservative response-planning envelope (the
    measured 112-row Luna control used 8548 tokens). This is not a course limit
    or a semantic verdict. Every unit retains the full original source context.
    """
    if type(max_output_tokens) is not int or max_output_tokens < 1024:
        raise ValueError('coherent_blind_output_budget_invalid')
    row_budget = max_output_tokens // 256
    units: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    rows = 0

    def flush() -> None:
        nonlocal selected, rows
        if selected:
            units.append({'title': course['title'], 'lessons': selected})
            selected, rows = [], 0

    for lesson in course['lessons']:
        count = sum(len(q['choices']) for q in lesson['questions'])
        if count <= row_budget:
            if rows + count > row_budget:
                flush()
            selected.append(copy.deepcopy(lesson))
            rows += count
            continue
        flush()
        partial = {**copy.deepcopy(lesson), 'questions': []}
        for question in lesson['questions']:
            size = len(question['choices'])
            if size > row_budget:
                raise ValueError('coherent_question_exceeds_response_envelope')
            if rows + size > row_budget:
                selected = [partial]
                flush()
                partial = {**copy.deepcopy(lesson), 'questions': []}
            partial['questions'].append(copy.deepcopy(question))
            rows += size
        selected = [partial]
        flush()
    flush()
    return units


async def run_coherent_editorial_cycle(packet: Any, corpus: Any, intent: Any,
        reference_decisions: tuple[Any, ...], stage: Any, *, max_revisions: int,
        max_output_tokens: int) -> PracticalCycleResult:
    if type(max_revisions) is not int or not 1 <= max_revisions <= 5:
        raise ValueError('editorial_revision_budget_invalid')
    if type(max_output_tokens) is not int or max_output_tokens < 1024:
        raise ValueError('coherent_blind_output_budget_invalid')
    if build_practical_source_packet(corpus, reference_decisions) != packet:
        raise ValueError('editorial_source_custody_mismatch')
    view = PracticalModelView(packet)
    context = _context(packet, corpus, view, canonical_json=True)
    completions = []

    async def call(name: str, group: str, messages: Any, fmt: Any, validator: Any) -> Any:
        may_complete = name == 'review' and is_joint_verification_group(group)

        def checked(raw: Any) -> Any:
            value = view.decode(raw)
            if (may_complete and matches_editorial_verification_shape(value, fmt)
                    and not matches_editorial_verification(value, fmt)):
                return None
            return validator(value)

        value = view.decode(await stage(name, group, messages, view.schema(fmt), checked))
        if (may_complete and matches_editorial_verification_shape(value, fmt)
                and not matches_editorial_verification(value, fmt)):
            async def complete(key: str, request: Any, schema: Any, validate: Any) -> Any:
                raw = await stage('review', key, request, view.schema(schema), lambda v: validate(view.decode(v)))
                return view.decode(raw)
            value, receipt = await complete_editorial_resolutions(value, fmt, messages, complete)
            completions.append(receipt)
        validator(value)
        return value

    def author(value: Any) -> Any:
        view.assert_course_ids_disjoint(value)
        value = normalize_author_question_ids(value, set(view.canonical_to_alias))
        view.assert_course_ids_disjoint(value)
        return validate_practical_course(value, packet)

    messages, fmt = coherent_author_request(packet, intent, context, view)
    original = author(await call('lesson', 'practical:author:editorial:v33', messages, fmt, author))
    candidate = copy.deepcopy(original)
    messages = [{'role': 'system', 'content': REVIEW_SYSTEM + EDITORIAL_REASONING_GUIDE + SOURCE_AUTHORITY_GUIDE},
        {'role': 'user', 'content': context + '\nCURRENT_COURSE_JSON\n'
            + json.dumps(view.encode(candidate), ensure_ascii=False, sort_keys=True)}]
    fmt = editorial_review_format(packet, candidate)
    first_raw = await call('review', 'practical:editorial:review:v31:' + _digest([messages, fmt]), messages, fmt,
                           lambda v: compile_editorial_review(v, packet, candidate))
    review = compile_editorial_review(first_raw, packet, candidate)
    initial_review = copy.deepcopy(review)
    observations = [{'course_fingerprint': _digest(candidate), 'review': copy.deepcopy(review)}]
    known = {row['issue_id']: copy.deepcopy(row) for row in review['findings'] if row['severity'] == 'material'}
    blind_cache: dict[str, Any] = {}
    resolutions: list[dict[str, Any]] = []
    closed: set[str] = set()
    source_questions: dict[str, Any] = {}
    current_primary: set[str] = set()
    rounds = []
    revisions = 0
    verified_fp = _digest(candidate)

    async def blind_check() -> tuple[Any, Any, str]:
        raw, decisions, inputs = [], [], []
        for unit in blind_review_units(candidate, max_output_tokens):
            request = option_predicates_messages(packet, unit, context, model_view=view)
            request[0]['content'] += CASE_STATUS_REVIEW_GUIDE + SOURCE_AUTHORITY_GUIDE
            schema = option_predicates_format(packet, unit)
            fingerprint = _digest([request, view.schema(schema)])
            if fingerprint not in blind_cache:
                blind_cache[fingerprint] = await call('review', 'practical:review:option-predicates:v33:' + fingerprint,
                    request, schema, lambda v, owned=unit: interpret_option_predicates(v, packet, owned))
            value = blind_cache[fingerprint]
            raw.append(value)
            decisions.append(interpret_option_predicates(value, packet, unit))
            inputs.append(fingerprint)
        decision = PracticalReviewDecision(all(d.accepted for d in decisions), False, (),
            tuple(q for d in decisions for q in d.question_ids), False, tuple(r for d in decisions for r in d.feedback))
        return {'source_fingerprint': packet.fingerprint, 'question_units': raw, 'source_notes': []}, decision, _digest(inputs)

    async def verify_current() -> None:
        nonlocal review, resolutions, closed, source_questions, verified_fp, current_primary
        # Empty current references prevent inheriting evidence across a prose edit.
        empty = {'review': {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(candidate),
            'summary': 'Current verification pending', 'findings': [], 'source_notes': [],
            'narrative_sources': {lesson['id']: [] for lesson in candidate['lessons']}},
            'source_rule_checks': [], 'resolutions': [], 'observations': [], 'raw_parts': []}
        prior = list(known.values())
        compiled, proof_prior = await reconcile_current_editorial(packet, candidate, prior, empty, context, view, call)

        async def proof_call(name: str, group: str, request: Any, schema: Any, validate: Any) -> Any:
            return await call(name, group.replace(':v33:proof:', ':v34:proof:', 1), request, schema, validate)

        compiled = await correct_resolution_proofs(packet, candidate, proof_prior, compiled, context, view,
                                                   proof_call, addressed_evidence=True)
        finish_current_reconciliation(compiled, candidate, proof_prior)
        review, resolutions = compiled['review'], compiled['resolutions']
        closed = {r['issue_id'] for r in resolutions if r['verified']
                  and r['disposition'] in {'FIXED', 'ALREADY_COVERED', 'NOT_MATERIAL'}}
        source_questions = {r['issue_id']: r for r in resolutions
                            if r['verified'] and r['disposition'] == 'SOURCE_AMBIGUITY'}
        current_primary = set()
        for finding in review['findings']:
            if finding['severity'] == 'material':
                current_primary.add(finding['issue_id'])
                known[finding['issue_id']] = copy.deepcopy(finding)
                closed.discard(finding['issue_id'])
                source_questions.pop(finding['issue_id'], None)
        verified_fp = _digest(candidate)
        observations.append({'course_fingerprint': verified_fp, 'review': copy.deepcopy(review)})
        rounds.append({'course_fingerprint': verified_fp, 'verification_raw': compiled['raw_parts'],
                       'resolutions': copy.deepcopy(resolutions)})

    blind_raw, blind, blind_hash = await blind_check()
    initial_blind = copy.deepcopy(blind_raw)
    for finding in _blind_findings(blind, packet, candidate):
        known.setdefault(finding['issue_id'], finding)
    if known:
        await verify_current()
    stop = None
    while known.keys() - closed - source_questions.keys():
        latest = {row['issue_id']: row for row in resolutions}
        editable = [row for key, row in known.items() if key not in closed and key not in source_questions
            and row['domain'] != 'source' and row['target']['kind'] != 'source'
            and (key in current_primary or latest.get(key, {}).get('verified') is True
                 and latest[key]['disposition'] == 'NEEDS_REVISION')]
        if not editable or revisions >= max_revisions:
            stop = 'automatic_review_unresolved' if not editable else 'autonomous_revision_budget_exhausted'
            break
        before = _digest(candidate)
        receipts = []
        for batch in _edit_batches(candidate, editable):
            current = {**review, 'source_fingerprint': packet.fingerprint,
                       'course_fingerprint': _digest(candidate), 'findings': batch}
            request = _scoped_edit_messages(candidate, batch, context, view, [], SOURCE_AUTHORITY_GUIDE, explicit_scope=True)
            schema = editorial_revision_format(packet, candidate)
            raw = await call('repair', 'practical:editorial:revision:v33:' + _digest([candidate, batch]), request, schema,
                lambda v, owned=candidate, intent=current: compile_editorial_revision(v, packet, owned, intent))
            candidate, metadata = compile_editorial_revision(raw, packet, candidate, current)
            receipts.append({'response': raw, 'revision': metadata})
        revisions += 1
        await verify_current()
        blind_raw, blind, blind_hash = await blind_check()
        new_blind = [row for row in _blind_findings(blind, packet, candidate) if row['issue_id'] not in known]
        for finding in new_blind:
            known[finding['issue_id']] = finding
        if new_blind:
            await verify_current()
        rounds.append({'editorial_revision_batches': receipts, 'current_course_fingerprint': _digest(candidate),
                       'blind_review': copy.deepcopy(blind_raw)})
        if before == _digest(candidate) and known.keys() - closed - source_questions.keys():
            stop = 'autonomous_edit_no_progress'
            break
    unresolved = [row for key, row in known.items() if key not in closed]
    owners = _owner_source_questions(source_questions, packet.fingerprint)
    owner_by_issue = {key: q for q in owners for key in q['issue_ids']}
    feedback = []
    for row in unresolved:
        question = owner_by_issue.get(row['issue_id'])
        if question and row['issue_id'] != question['issue_ids'][0]:
            continue
        feedback.append({'issue_id': row['issue_id'],
            'scope': 'source' if question else {'course': 'coverage', 'lesson': 'lesson', 'question': 'question', 'source': 'source'}[row['target']['kind']],
            'id': question['source_refs'][0] if question else row['target']['id'],
            'evidence': {**row, 'editorial_finding': True,
                'status': 'SOURCE_UNRESOLVED' if question else 'AUTOMATIC_REVIEW_UNRESOLVED',
                **({'source_question': question['source_question'], 'source_refs': question['source_refs'],
                    'confirmed_source_quote': question['source_quote'], 'original_target': row['target'],
                    'source_issue_ids': question['issue_ids'], 'source_evidence_decisions': question['evidence_decisions']}
                   if question else {})}})
    blind_ids = {row['issue_id'] for row in _blind_findings(blind, packet, candidate)}
    blind_adjudicated = bool(blind_ids) and blind_ids <= closed
    accepted = not unresolved and (blind.accepted or blind_adjudicated) and verified_fp == _digest(candidate)
    originals = {row['id']: row for row in original['lessons']}
    revised = [row['id'] for row in candidate['lessons'] if row['id'] not in originals
               or row['content'] != originals[row['id']]['content']]
    history = ({'autonomous_editorial': True, 'coherent_literal_source': True,
        'editorial_original_course': original, 'initial_editorial_review': initial_review,
        'initial_editorial_review_raw': first_raw, 'initial_blind_review': initial_blind,
        'editorial_review': review, 'editorial_observation_history': observations,
        'all_material_findings': list(known.values()), 'verified_resolutions': resolutions,
        'confirmed_source_questions': owners, 'autonomous_rounds': rounds,
        'verified_course_fingerprint': verified_fp, 'final_blind_review': blind_raw,
        'final_blind_input_hash': blind_hash, 'final_blind_current_course_fingerprint': _digest(candidate),
        'final_blind_adjudicated_issue_ids': sorted(blind_ids) if blind_adjudicated else [],
        'unverified_revised_prose': [] if verified_fp == _digest(candidate) else revised, 'keyed_editorial_review': True,
        'blind_answer_review': True, 'revision_budget': max_revisions, 'revisions_used': revisions,
        'resolution_completion_history': completions},)
    return PracticalCycleResult(candidate, {'source_notes': review['source_notes'],
        'narrative_sources': review['narrative_sources']},
        PracticalReviewDecision(accepted, bool(source_questions), (), (), False, tuple(feedback)), history,
        'automated_editorial_review_passed' if accepted else stop or 'source_clarification_required',
        standalone_review=True, question_bank_review=True, editorial_review=True)
