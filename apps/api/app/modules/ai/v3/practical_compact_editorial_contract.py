"""Compact model judgments with source identity and strict resolution custody.

Literal lesson prose establishes custody only; it does not prove semantic equivalence.
"""
from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import _obj, _review_format, compile_editorial_review
from app.modules.ai.v3.practical_editorial_verification import _format as _verification_base
from app.modules.ai.v3.practical_editorial_verification import compile_editorial_verification
from app.modules.ai.v3.practical_rule_editorial_contract import _compact, _scoped_identity
from app.modules.ai.v3.practical_source_semantics import source_semantics_final_rules

READ_NAME = 'v3_practical_compact_editorial_review_v2'
VERIFY_NAME = 'v3_practical_compact_editorial_verification_v2'


def _format(sources: list[str], source_fp: str, course_fp: str, reading_fp: str,
            lessons: list[str], questions: list[str], ids: list[str], issues: list[str] | None) -> dict[str, Any]:
    if not ids or len(set(ids)) != len(ids) or any(type(x) is not str or not x for x in ids):
        raise ValueError('compact_editorial_identity_invalid')
    if type(reading_fp) is not str or len(reading_fp) != 64:
        raise ValueError('compact_editorial_identity_invalid')
    base = _review_format(sources, lessons, questions, source_fp, course_fp)
    if issues is not None:
        base = _verification_base(base, issues)
    _compact(base)
    props = base['json_schema']['schema']['properties']
    # One inventory is recoverable for strict format identity; other refs are
    # checked against the bound packet when the response is compiled.
    props['source_notes']['items']['properties']['source_refs']['items']['enum'] = copy.deepcopy(sources)
    if issues == []:
        props['resolutions']['items']['properties']['issue_id'].pop('enum', None)
    base['json_schema']['name'] = VERIFY_NAME if issues is not None else READ_NAME
    text = {'type': 'string'}
    props['reading_fingerprint'] = {'type': 'string', 'enum': [reading_fp]}
    props['source_rule_checks'] = {'type': 'array', 'minItems': len(ids), 'maxItems': len(ids), 'items': _obj({
        'rule_id': {'type': 'string', 'enum': ids},
        'status': {'type': 'string', 'enum': ['SUPPORTED', 'CONTRADICTED', 'INCOMPLETE', 'NOT_APPLICABLE', 'SOURCE_READING_DISPUTED']},
        'lesson_ids': {'type': 'array', 'items': text},
        'lesson_quotes': {'type': 'array', 'items': _obj({'lesson_id': text, 'quote': text})},
        'reason': text, 'correction': text, 'severity': {'type': 'string', 'enum': ['material', 'advisory']},
    })}
    base['json_schema']['schema']['required'].extend(['reading_fingerprint', 'source_rule_checks'])
    return base


def _make(packet: Any, course: dict[str, Any], reading: dict[str, Any], rule_ids: list[str] | None,
          issues: list[str] | None) -> dict[str, Any]:
    source_fp, course_fp, reading_fp, lessons, questions, ids = _scoped_identity(packet, course, reading, rule_ids)
    return _format([b.block_id for b in packet.blocks if b.text.strip()], source_fp, course_fp,
                   reading_fp, lessons, questions, ids, issues)


def compact_editorial_review_format(packet: Any, course: dict[str, Any], reading: dict[str, Any], *,
                                    rule_ids: list[str] | None = None) -> dict[str, Any]:
    return _make(packet, course, reading, rule_ids, None)


def compact_editorial_verification_format(packet: Any, course: dict[str, Any], reading: dict[str, Any],
        findings: list[dict[str, Any]], *, rule_ids: list[str] | None = None) -> dict[str, Any]:
    return _make(packet, course, reading, rule_ids, [row['issue_id'] for row in findings if row['severity'] == 'material'])


def _is_format(fmt: Any, verification: bool) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        targets = props['findings']['items']['properties']['target']['anyOf']
        sources = props['source_notes']['items']['properties']['source_refs']['items']['enum']
        ids = props['source_rule_checks']['items']['properties']['rule_id']['enum']
        issues = props['resolutions']['items']['properties']['issue_id'].get('enum', []) if verification else None
        return bool(fmt == _format(sources, props['source_fingerprint']['enum'][0], props['course_fingerprint']['enum'][0],
            props['reading_fingerprint']['enum'][0], targets[1]['properties']['id']['enum'],
            targets[2]['properties']['id']['enum'], ids, issues))
    except (KeyError, TypeError, ValueError, IndexError, RecursionError):
        return False


def is_compact_editorial_review_format(fmt: Any) -> bool:
    return _is_format(fmt, False)


def is_compact_editorial_verification_format(fmt: Any) -> bool:
    return _is_format(fmt, True)


def _matches_response(value: Any, fmt: Any, verification: bool) -> bool:
    try:
        if not _is_format(fmt, verification) or not _matches(value, fmt['json_schema']['schema']):
            return False
        props = fmt['json_schema']['schema']['properties']
        ids = props['source_rule_checks']['items']['properties']['rule_id']['enum']
        checks = value['source_rule_checks']
        if len(checks) != len(ids) or {row['rule_id'] for row in checks} != set(ids):
            return False
        if any(not row['reason'].strip() or (not row['correction'].strip() and row['status'] not in ('SUPPORTED', 'NOT_APPLICABLE'))
               for row in checks):
            return False
        if verification:
            expected = props['resolutions']['items']['properties']['issue_id'].get('enum', [])
            actual = [row['issue_id'] for row in value['resolutions']]
            if len(actual) != len(expected) or set(actual) != set(expected):
                return False
        return True
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def matches_compact_editorial_review(value: Any, fmt: Any) -> bool:
    return _matches_response(value, fmt, False)


def matches_compact_editorial_verification(value: Any, fmt: Any) -> bool:
    return _matches_response(value, fmt, True)


def _compile(value: Any, packet: Any, course: dict[str, Any], reading: dict[str, Any],
             prior: list[dict[str, Any]] | None, rule_ids: list[str] | None) -> dict[str, Any]:
    fmt = (compact_editorial_review_format(packet, course, reading, rule_ids=rule_ids) if prior is None else
           compact_editorial_verification_format(packet, course, reading, prior, rule_ids=rule_ids))
    if not _matches_response(value, fmt, prior is not None):
        raise ValueError('compact_editorial_response_invalid')
    base = {key: copy.deepcopy(val) for key, val in value.items() if key not in ('reading_fingerprint', 'source_rule_checks')}
    result: dict[str, Any] = ({'review': compile_editorial_review(base, packet, course), 'resolutions': []} if prior is None else
                              compile_editorial_verification(base, packet, course, prior))
    rules = {row['rule_id']: row for row in source_semantics_final_rules(packet, reading)}
    lessons = {row['id']: row['content'] for row in course['lessons']}
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for row in value['source_rule_checks']:
        rule = rules[row['rule_id']]
        errors = []
        quotes = row['lesson_quotes']
        requested = row['lesson_ids']
        lesson_ids = list(dict.fromkeys(lid for lid in requested if lid in lessons))
        if len(requested) != len(set(requested)):
            errors.append('lesson_ids_duplicate')
        if any(lid not in lessons for lid in requested):
            errors.append('lesson_id_invalid')
        if row['status'] == 'SUPPORTED' and not requested:
            errors.append('lesson_ids_missing')
        if row['status'] in ('CONTRADICTED', 'INCOMPLETE') and not requested:
            errors.append('lesson_target_missing')
        if row['status'] == 'SUPPORTED' and not quotes:
            errors.append('lesson_quote_missing')
        if any(q['lesson_id'] not in lessons for q in quotes):
            errors.append('lesson_id_invalid')
        if any(q['lesson_id'] in lessons and (not q['quote'].strip() or q['quote'] not in lessons[q['lesson_id']]) for q in quotes):
            errors.append('lesson_quote_invalid')
        quoted = {q['lesson_id'] for q in quotes}
        if quoted - set(requested):
            errors.append('lesson_quote_target_mismatch')
        if row['status'] == 'SUPPORTED' and set(requested) - quoted:
            errors.append('lesson_quote_missing_for_target')
        irrelevant = rule['status'] == 'SOURCE_AMBIGUITY' and row['status'] == 'NOT_APPLICABLE'
        if not rule['custody_valid'] or (rule['status'] not in ('SUPPORTED', 'REVISE') and not irrelevant):
            errors.append('source_reading_unverified')
        if row['status'] == 'SOURCE_READING_DISPUTED':
            errors.append('source_reading_disputed')
        checks.append({**copy.deepcopy(row), 'lesson_ids': lesson_ids, 'verified': not errors, 'verification_errors': errors})
        if row['status'] in ('CONTRADICTED', 'INCOMPLETE') or errors:
            targets = [{'kind': 'lesson', 'id': lesson} for lesson in lesson_ids] or [{'kind': 'course', 'id': 'course'}]
            for target in targets:
                finding = {'domain': 'content', 'severity': 'material' if errors else row['severity'], 'target': target,
                    'problem': 'Source rule check requires review: ' + row['status'], 'basis': row['reason'],
                    'correction': row['correction'], 'source_refs': list(rule['rule']['source_refs']),
                    'source_rule_id': row['rule_id'], 'rule_check_unverified': bool(errors)}
                finding['issue_id'] = 'issue-' + _digest({'source_rule_id': row['rule_id'], 'target': target,
                                                           'rule_check_unverified': bool(errors)})[:20]
                findings.append(finding)
    result['review']['findings'].extend(findings)
    if prior is not None:
        prior_by_id = {row['issue_id']: row for row in prior}
        current_by_id = {row['rule_id']: row for row in checks}
        for resolution in result['resolutions']:
            rule_id = prior_by_id[resolution['issue_id']].get('source_rule_id')
            if not rule_id:
                continue
            card = current_by_id.get(rule_id)
            if card is None:
                resolution['verified'] = False
                resolution['verification_errors'].append('current_rule_not_checked_in_subset')
                continue
            negative = card['status'] in ('CONTRADICTED', 'INCOMPLETE')
            disposition = resolution['disposition']
            compatible = (card['verified'] and (
                negative and card['severity'] == 'material' if disposition == 'NEEDS_REVISION' else
                not (negative and card['severity'] == 'material') if disposition == 'NOT_MATERIAL' else
                not negative and card['status'] != 'SOURCE_READING_DISPUTED'))
            if not compatible:
                resolution['verified'] = False
                resolution['verification_errors'].append('current_rule_check_open')
    result['source_rule_checks'] = checks
    return result


def compile_compact_editorial_review(value: Any, packet: Any, course: dict[str, Any], reading: dict[str, Any], *,
                                     rule_ids: list[str] | None = None) -> dict[str, Any]:
    return _compile(value, packet, course, reading, None, rule_ids)


def compile_compact_editorial_verification(value: Any, packet: Any, course: dict[str, Any], reading: dict[str, Any],
        findings: list[dict[str, Any]], *, rule_ids: list[str] | None = None) -> dict[str, Any]:
    return _compile(value, packet, course, reading, findings, rule_ids)
