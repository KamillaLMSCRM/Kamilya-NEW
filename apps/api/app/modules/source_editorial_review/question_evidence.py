"""Project literal proof separately from an editable, unique source anchor."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.source_editorial_review.question_context import QuestionContext, QuestionContextError, contexts


def verified_edit_scopes(original: str, issues: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Allow editing the proven row, without expanding factual verification.

    A reviewer may quote only a prefix of the row while asking about another
    field in it. Reconstruct navigation from exact stored proof, never from a
    product name, model interpretation or a nearby first occurrence.
    """
    candidates = [q for q in issues.values() if not q.get('source_scopes')
                  and not q.get('needs_source_verification') and len(q.get('source_refs', [])) == 1
                  and q.get('source_evidence')]
    if not candidates:
        return issues
    context, = contexts(original, [(0, original)])
    if context is None:
        return issues
    result = dict(issues)
    for question in candidates:
        ref = question['source_refs'][0]
        unit = context.references.get(ref)
        proofs = question['source_evidence']
        if unit is None or unit.kind != 'table_row':
            continue
        if any(proof.get('source_ref') != ref or type(proof.get('start')) is not int
               or type(proof.get('end')) is not int
               or not unit.start <= proof['start'] < proof['end'] <= unit.end
               or original[proof['start']:proof['end']] != proof.get('quote') for proof in proofs):
            continue
        if question.get('start') is not None and not (
                type(question.get('start')) is int and type(question.get('end')) is int
                and unit.start <= question['start'] < question['end'] <= unit.end
                and original[question['start']:question['end']] == question.get('quote')):
            continue
        result[question['id']] = {**question, 'source_scopes': [{
            'source_ref': ref, 'start': unit.start, 'end': unit.end, 'text': unit.text,
            'label': context.labels([ref])[0] if context.labels([ref]) else ref}]}
    return result


def project_question(finding: dict[str, Any], *, item_id: str, original: str,
                     offset: int, local: str, context: QuestionContext | None,
                     restore: Callable[[str, str], tuple[int, int] | None]) -> list[dict[str, Any]]:
    quote = finding['excerpt']
    start = offset + local.index(quote) if quote and local.count(quote) == 1 else None
    span = (start, start + len(quote)) if start is not None else None
    refs = finding.get('source_refs')
    evidence: list[dict[str, Any]] = []
    if context is not None and refs is not None:
        try:
            span = context.bind(quote, refs, restore)
        except QuestionContextError:
            span = None
        try:
            evidence = context.evidence(quote, refs, restore)
        except QuestionContextError:
            evidence = []
    row: dict[str, Any] = {'id': item_id, 'start': span[0] if span else None, 'end': span[1] if span else None,
           'quote': original[span[0]:span[1]] if span else quote,
           'category': finding['category'], 'reason': finding['reason']}
    if refs is not None:
        row['source_refs'] = refs
        labels = context.labels(refs) if context is not None else []
        if labels:
            row['source_labels'] = labels
    if evidence:
        row['source_evidence'] = evidence
    if span is None and evidence and context is not None:
        # One factual answer must not silently settle different products.
        result = []
        for ref in dict.fromkeys(e['source_ref'] for e in evidence):
            unit = context.references[ref]
            proofs = [e for e in evidence if e['source_ref'] == ref]
            result.append({**row, 'id': item_id if len(refs or []) == 1 else f'{item_id}-{ref}',
                'parent_finding_id': item_id, 'quote': proofs[0]['quote'],
                'source_refs': [ref], 'source_labels': context.labels([ref]), 'source_evidence': proofs,
                'source_scopes': [{'source_ref': ref, 'start': unit.start, 'end': unit.end,
                                   'text': unit.text, 'label': context.labels([ref])[0] if context.labels([ref]) else ref}]})
        return result
    if span is None or (context is not None and refs is None):
        row['needs_source_verification'] = True
    return [row]
