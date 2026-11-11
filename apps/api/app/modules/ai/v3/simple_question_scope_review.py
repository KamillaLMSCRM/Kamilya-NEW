"""Question-scope adapter for the existing key-blind counterexample review."""
from __future__ import annotations

import copy
import json
from typing import Any, TypedDict

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from app.modules.ai.v3.simple_blind_question_review import _visible_course


class _ReviewFlags(TypedDict):
    concise: bool
    strict_targets: bool
    standalone: bool
    typed_findings: bool
    counterexamples: bool
    question_batch: bool


_FLAGS: _ReviewFlags = {'concise': True, 'strict_targets': True, 'standalone': True,
          'typed_findings': True, 'counterexamples': True, 'question_batch': True}


def _scope_format(base: dict[str, Any], bank_fingerprint: str) -> dict[str, Any]:
    fmt = copy.deepcopy(base)
    fmt['json_schema']['name'] = 'simple_question_scope_review_v1'
    schema = fmt['json_schema']['schema']
    schema['properties']['bank_fingerprint'] = {'type': 'string', 'enum': [bank_fingerprint]}
    schema['required'].append('bank_fingerprint')
    return fmt


def _inner_format(fmt: dict[str, Any]) -> dict[str, Any]:
    inner = copy.deepcopy(fmt)
    inner['json_schema']['name'] = 'v3_practical_question_review_v16'
    schema = inner['json_schema']['schema']
    del schema['properties']['bank_fingerprint']
    schema['required'].remove('bank_fingerprint')
    return inner


def is_simple_question_scope_format(fmt: Any) -> bool:
    try:
        fingerprint = fmt['json_schema']['schema']['properties']['bank_fingerprint']['enum'][0]
        inner = _inner_format(fmt)
        return (type(fingerprint) is str and len(fingerprint) == 64
                and all(c in '0123456789abcdef' for c in fingerprint)
                and is_practical_review_format(inner)
                and inner['json_schema']['name'] == 'v3_practical_question_review_v16'
                and fmt == _scope_format(inner, fingerprint))
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return False


def matches_simple_question_scope(value: Any, fmt: Any) -> bool:
    if not is_simple_question_scope_format(fmt) or type(value) is not dict or 'bank_fingerprint' not in value:
        return False
    return (value['bank_fingerprint'] == fmt['json_schema']['schema']['properties']['bank_fingerprint']['enum'][0]
            and matches_practical_review({k: v for k, v in value.items() if k != 'bank_fingerprint'}, _inner_format(fmt)))


def _decision_reasons(packet: PracticalSourcePacket, context: dict[str, Any]) -> list[dict[str, Any]]:
    if (type(context) is not dict or context.get('source_fingerprint') != packet.fingerprint
            or type(context.get('documents')) is not list):
        raise ValueError('simple_scope_context_invalid')
    documents = context['documents']
    if len(documents) != len(packet.source_documents):
        raise ValueError('simple_scope_context_invalid')
    projected = []
    for doc, (doc_id, revision, digest) in zip(documents, packet.source_documents, strict=True):
        if (type(doc) is not dict or doc.get('document_id') != doc_id or doc.get('source_revision') != revision
                or doc.get('working_sha256') != digest or type(doc.get('approved_decisions')) not in (list, tuple)):
            raise ValueError('simple_scope_context_invalid')
        reasons = []
        for row in doc['approved_decisions']:
            if (type(row) is not dict or type(row.get('item_id')) is not str or not row['item_id'].strip()
                    or row.get('decision') not in ('keep', 'replace') or type(row.get('reason')) is not str
                    or not row['reason'].strip()):
                raise ValueError('simple_scope_context_invalid')
            reasons.append({'item_id': row['item_id'], 'decision': row['decision'], 'reason': row['reason']})
        projected.append({'document_id': doc_id, 'approved_decisions': reasons})
    return projected


def question_scope_request(packet: PracticalSourcePacket, original: dict[str, Any],
                           current_context: dict[str, Any], view: PracticalModelView
                           ) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    if not isinstance(view, PracticalModelView):
        raise ValueError('simple_scope_context_invalid')
    decisions = _decision_reasons(packet, current_context)
    visible = _visible_course(packet, original)
    messages = practical_review_messages(packet, visible, model_view=view, **_FLAGS)
    messages[0]['content'] += (' The quiz title explicitly prefixed inside each question is persistently visible '
        'to the learner and may supply scope. Do not borrow facts from other cards or hidden lesson content.')
    messages[1]['content'] += ('\nAPPROVED_INTERPRETATION_REASONS_JSON\n' + json.dumps(decisions, ensure_ascii=False, sort_keys=True)
                              + '\nBANK_FINGERPRINT ' + _digest(visible))
    return messages, view.schema(_scope_format(practical_review_format(packet, visible, **_FLAGS), _digest(visible))), visible


def compile_question_scope_review(raw_canonical: dict[str, Any], packet: PracticalSourcePacket,
                                  original: dict[str, Any], visible_course: dict[str, Any]
                                  ) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = _visible_course(packet, original)
    if visible_course != expected:
        raise ValueError('simple_scope_visible_course_invalid')
    fmt = _scope_format(practical_review_format(packet, expected, **_FLAGS), _digest(expected))
    if not matches_simple_question_scope(raw_canonical, fmt):
        raise ValueError('simple_scope_response_invalid')
    inner = {key: value for key, value in raw_canonical.items() if key != 'bank_fingerprint'}
    decision = interpret_practical_review(inner, packet, expected, **_FLAGS)
    proposals, source_questions, observations = [], [], []
    for finding in decision.feedback:
        details = finding['evidence']
        if finding['scope'] == 'source':
            source_questions.append({'question': details['problem'], 'source_refs': copy.deepcopy(details['source_refs'])})
        elif finding['scope'] == 'question':
            proposals.append({'target_id': finding['id'],
                'correction': details.get('correction', 'Recheck the question and its applicable conditions against the source.'),
                'source_refs': copy.deepcopy(details['source_refs'])})
            observations.append({'question_id': finding['id'], 'status': 'UNVERIFIED',
                                 'problem': details.get('reason', details['problem']),
                                 'source_refs': copy.deepcopy(details['source_refs'])})
    fingerprint = _digest(original)
    review = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
              'proposals': proposals, 'source_questions': source_questions}
    evidence = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
                'visible_course_fingerprint': _digest(expected), 'answerability': copy.deepcopy(raw_canonical['answerability']),
                'findings': copy.deepcopy(raw_canonical['findings']), 'unverified_observations': observations,
                'semantic_approval': False}
    return review, evidence
