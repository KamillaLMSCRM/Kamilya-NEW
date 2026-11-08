"""One addressed evidence-only correction; never a course edit or new finding gate."""
from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_verification import (
    compile_editorial_verification,
    editorial_verification_format,
)

PROOF_ERRORS = frozenset({'source_quote_invalid', 'course_quote_invalid', 'source_refs_invalid', 'reason_missing'})
PROOF_ELIGIBLE = frozenset({'FIXED', 'ALREADY_COVERED', 'NOT_MATERIAL', 'NEEDS_REVISION', 'SOURCE_AMBIGUITY'})
POSITIVE_DISPOSITIONS = frozenset({'FIXED', 'ALREADY_COVERED'})
SYSTEM = (
    'Correct only the literal evidence and reason for the supplied existing resolutions. '
    'Do not change their dispositions, source questions, course, or substantive judgments. '
    'Copy a contiguous source quote from a referenced source block and, where required, '
    'a contiguous quote from the exact current target. Do not invent a source question. '
    'Other findings or notes are observations of this proof-only call, not edit authority.'
)


def same_proof_disposition(original: str, corrected: str) -> bool:
    """Two positive labels assert the same current coverage, not the same history."""
    return original == corrected or original in POSITIVE_DISPOSITIONS and corrected in POSITIVE_DISPOSITIONS


async def correct_resolution_proofs(packet: Any, course: dict[str, Any], prior: list[dict[str, Any]],
                                    result: dict[str, Any], context: str, view: Any, call: Any) -> dict[str, Any]:
    output = copy.deepcopy(result)
    rows = output['resolutions']
    if len({row['issue_id'] for row in rows}) != len(rows):
        raise ValueError('editorial_proof_resolution_identity_invalid')
    prior_by_id = {row['issue_id']: row for row in prior if row['severity'] == 'material'}
    if len(prior_by_id) != sum(row['severity'] == 'material' for row in prior):
        raise ValueError('editorial_proof_resolution_identity_invalid')
    selected = [row for row in rows if row['disposition'] in PROOF_ELIGIBLE
                and bool(set(row['verification_errors']) & PROOF_ERRORS)]
    if not selected:
        return output
    if any(row['issue_id'] not in prior_by_id for row in selected):
        raise ValueError('editorial_proof_resolution_identity_invalid')
    selected_prior = [prior_by_id[row['issue_id']] for row in selected]
    selected_by_id = {row['issue_id']: row for row in selected}
    questions = []
    for lesson in course['lessons']:
        for question in lesson['questions']:
            if any((finding['target']['kind'] == 'question' and finding['target']['id'] == question['id'])
                   or (finding['domain'] == 'assessment' and finding['target']['kind'] == 'lesson'
                       and finding['target']['id'] == lesson['id'])
                   or (finding['domain'] == 'assessment' and finding['target']['kind'] == 'course')
                   for finding in selected_prior):
                questions.append(question)
    prior_wire = view.encode(selected_prior)
    old_wire = copy.deepcopy(selected)
    for row in old_wire:
        row['source_refs'] = [view.canonical_to_alias.get(ref, ref) for ref in row['source_refs']]
    user = (context + '\nCURRENT_TEACHING_PROSE_JSON\n' + json.dumps(
        {'course_fingerprint': _digest(course), 'title': course['title'], 'lessons': [
            {key: lesson[key] for key in ('id', 'title', 'content')} for lesson in course['lessons']]},
        ensure_ascii=False, sort_keys=True)
        + '\nCURRENT_ASSESSMENT_TARGETS_JSON\n' + json.dumps(view.encode(questions), ensure_ascii=False, sort_keys=True)
        + '\nPRIOR_MATERIAL_FINDINGS_JSON\n' + json.dumps(prior_wire, ensure_ascii=False, sort_keys=True)
        + '\nPRIOR_INVALID_RESOLUTIONS_JSON\n' + json.dumps(old_wire, ensure_ascii=False, sort_keys=True))
    fmt = editorial_verification_format(packet, course, selected_prior)

    def compile_response(value: Any) -> dict[str, Any]:
        compiled = compile_editorial_verification(value, packet, course, selected_prior)
        for row in compiled['resolutions']:
            old = selected_by_id[row['issue_id']]
            if not same_proof_disposition(old['disposition'], row['disposition']):
                raise ValueError('editorial_proof_disposition_changed')
            if row['disposition'] == 'SOURCE_AMBIGUITY' and row['source_question'] != old['source_question']:
                raise ValueError('editorial_proof_source_question_changed')
            row['disposition'] = old['disposition']
        return compiled

    group = 'practical:editorial:verify:v33:proof:' + _digest([course, selected_prior, selected])
    raw = await call('review', group, [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}],
                     fmt, compile_response)
    compiled = compile_response(raw)
    corrected = {row['issue_id']: row for row in compiled['resolutions']}
    for index, old in enumerate(rows):
        if old['issue_id'] not in corrected:
            continue
        row = corrected[old['issue_id']]
        retained = [error for error in old['verification_errors'] if error not in PROOF_ERRORS]
        row['verification_errors'] = list(dict.fromkeys([*row['verification_errors'], *retained]))
        row['verified'] = not row['verification_errors']
        rows[index] = row
    output.setdefault('raw_parts', []).append({'review_kind': 'resolution_proof_correction',
        'issue_ids': [row['issue_id'] for row in selected], 'response': copy.deepcopy(raw),
        'unverified_proof_scope_extras': copy.deepcopy(compiled['review'])})
    return output
