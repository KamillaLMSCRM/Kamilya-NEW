"""Custody of model finding dispositions; evidence is not semantic approval."""
from __future__ import annotations

import copy
from typing import Any, cast

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_editor import _object
from app.modules.ai.v3.validator import normalize_literal_quote

_STATUSES = ('CORRECTED', 'ALREADY_SATISFIED', 'NOT_MATERIAL', 'UNRESOLVED')
_KINDS = ('lesson_content', 'lesson_title', 'question_prompt', 'question_explanation', 'question_choice')


def inventory(source_fp: str, draft_fp: str, reviews: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for origin, review in reviews:
        for finding in review['findings']:
            if finding['severity'] != 'material' or finding['domain'] == 'source':
                continue
            identity = 'finding-' + _digest([source_fp, draft_fp, finding])[:24]
            row = rows.setdefault(identity, {'id': identity, 'finding': copy.deepcopy(finding),
                'origins': [], 'source_fingerprint': source_fp, 'draft_fingerprint': draft_fp})
            if origin not in row['origins']:
                row['origins'].append(origin)
    return list(rows.values())


def finding_disposition_schema(finding_ids: list[str], source_refs: list[str]) -> dict[str, Any]:
    def owned(ids: list[str]) -> dict[str, Any]:
        return {'type': 'string', **({'enum': list(ids)} if ids else {})}
    return {'type': 'array', 'items': _object({
        'finding_id': owned(finding_ids), 'status': {'type': 'string', 'enum': list(_STATUSES)},
        'reason': {'type': 'string'}, 'source_refs': {'type': 'array', 'items': owned(source_refs)},
        'source_quote': {'type': 'string'}, 'target': _object({
            'kind': {'type': 'string', 'enum': list(_KINDS)}, 'id': {'type': 'string'},
            'choice_index': {'type': 'integer'}}), 'final_quote': {'type': 'string'}})}


def _field(course: dict[str, Any], target: dict[str, Any]) -> str | None:
    kind, identity, index = target.get('kind'), target.get('id'), target.get('choice_index')
    if kind not in _KINDS or type(identity) is not str or type(index) is not int:
        return None
    for lesson in course.get('lessons', []):
        if kind.startswith('lesson_') and lesson.get('id') == identity:
            return cast(str | None, lesson.get('content' if kind == 'lesson_content' else 'title'))
        if kind.startswith('question_'):
            for question in lesson.get('questions', []):
                if question.get('id') == identity:
                    if kind == 'question_choice':
                        choices = question.get('choices', [])
                        return choices[index] if 0 <= index < len(choices) else None
                    return cast(str | None, question.get('prompt' if kind == 'question_prompt' else 'explanation'))
    return None


def compile_finding_dispositions(inventory: list[dict[str, Any]], decisions: Any, packet: Any,
                                 original: dict[str, Any], final: dict[str, Any], *,
                                 allow_final_field_typography: bool = False) -> list[dict[str, Any]]:
    source = {block.block_id: block.text for block in packet.blocks}
    original_fp, result_fp = _digest(original), _digest(final)
    grouped: dict[str, list[dict[str, Any]]] = {}
    if type(decisions) is list:
        for decision in decisions:
            if type(decision) is dict and type(decision.get('finding_id')) is str:
                grouped.setdefault(decision['finding_id'], []).append(decision)
    result = []
    for item in inventory:
        candidates = grouped.get(item['id'], [])
        decision = candidates[0] if len(candidates) == 1 else {}
        claim = decision.get('status') if decision.get('status') in _STATUSES else 'UNRESOLVED'
        target = cast(dict[str, Any], decision.get('target')) if type(decision.get('target')) is dict else {}
        finding_target = item['finding']['target']
        kind, identity = target.get('kind'), target.get('id')
        allowed = (item['finding']['domain'] == 'content' and finding_target['kind'] in ('lesson', 'course')
            and kind == 'lesson_content' or
            finding_target['kind'] == 'course' and item['finding']['domain'] != 'content' or
            finding_target['kind'] == 'lesson' and item['finding']['domain'] != 'content'
            and kind == 'lesson_content' and identity == finding_target['id'] or
            finding_target['kind'] == 'question' and kind in ('question_prompt', 'question_explanation', 'question_choice')
            and identity == finding_target['id'])
        before, after = _field(original, target), _field(final, target)
        refs, source_quote, final_quote, reason = (decision.get(key) for key in
            ('source_refs', 'source_quote', 'final_quote', 'reason'))
        final_quote_match = 'none'
        actual_final_quote = final_quote
        if type(final_quote) is str and final_quote.strip() and type(after) is str:
            if final_quote in after:
                final_quote_match = 'literal'
            elif allow_final_field_typography:
                quoted = normalize_literal_quote(final_quote).removesuffix('.')
                actual = normalize_literal_quote(after).removesuffix('.')
                if quoted and quoted == actual:
                    final_quote_match = 'owned_field_typography'
                    actual_final_quote = after
        source_quote_match = 'none'
        if (type(refs) is list and refs and all(type(ref) is str and ref in source for ref in refs)
                and type(source_quote) is str and source_quote.strip()):
            if any(source_quote in source[ref] for ref in refs):
                source_quote_match = 'literal'
            elif any(normalize_literal_quote(source_quote) in normalize_literal_quote(source[ref]) for ref in refs):
                source_quote_match = 'normalized_typography'
        evidence_valid = bool(item.get('source_fingerprint') == packet.fingerprint
            and item.get('draft_fingerprint') == original_fp and allowed and type(refs) is list and refs
            and all(type(ref) is str and ref in source for ref in refs) and len(refs) == len(set(refs))
            and type(source_quote) is str and source_quote.strip()
            and source_quote_match != 'none'
            and final_quote_match != 'none'
            and type(reason) is str and reason.strip())
        new_lesson = (kind == 'lesson_content' and before is None and
                      any(row.get('id') == identity for row in final.get('lessons', [])) and
                      not any(row.get('id') == identity for row in original.get('lessons', [])))
        resolved = bool(evidence_valid and (claim == 'NOT_MATERIAL'
            or claim == 'ALREADY_SATISFIED' and type(before) is str and cast(str, actual_final_quote) in before
            or claim == 'CORRECTED' and (type(before) is str and before != after
                                        and cast(str, actual_final_quote) not in before or new_lesson)))
        result.append({**copy.deepcopy(item), 'result_fingerprint': result_fp, 'claimed_status': claim,
            'decision': copy.deepcopy(decision), 'source_quote_match': source_quote_match, 'evidence_valid': evidence_valid,
            'model_resolved': resolved, 'status': 'UNVERIFIED', 'semantic_approval': False})
        if allow_final_field_typography:
            result[-1]['final_quote_match'] = final_quote_match
    return result
