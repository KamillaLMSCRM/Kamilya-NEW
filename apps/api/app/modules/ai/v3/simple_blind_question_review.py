"""Adapt the existing key-blind option review to the visible quiz-card context."""
from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _digest, validate_practical_course
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_option_predicates import (
    _inventory,
    interpret_option_predicates,
    option_predicates_format,
    option_predicates_messages,
)


def _visible_course(packet: PracticalSourcePacket, original: dict[str, Any]) -> dict[str, Any]:
    visible = validate_practical_course(original, packet)
    for lesson in visible['lessons']:
        for question in lesson['questions']:
            question['prompt'] = 'Visible quiz title: ' + lesson['title'] + '\nQuestion: ' + question['prompt']
    return visible


def blind_question_request(packet: PracticalSourcePacket, original: dict[str, Any], context: str,
                           view: PracticalModelView) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    if type(context) is not str or not isinstance(view, PracticalModelView):
        raise ValueError('simple_blind_context_invalid')
    visible = _visible_course(packet, original)
    fmt = option_predicates_format(packet, visible)
    return option_predicates_messages(packet, visible, context, model_view=view), view.schema(fmt), visible


def compile_blind_question_review(raw_canonical: dict[str, Any], packet: PracticalSourcePacket,
                                  original: dict[str, Any], visible_course: dict[str, Any]
                                  ) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = _visible_course(packet, original)
    if visible_course != expected:
        raise ValueError('simple_blind_visible_course_invalid')
    decision = interpret_option_predicates(raw_canonical, packet, expected)
    proposals, observations = [], []
    for item in decision.feedback:
        evidence = item['evidence']
        observation = {'question_id': item['id'], 'status': 'UNVERIFIED', 'problem': evidence['problem'],
                       'source_refs': copy.deepcopy(evidence['source_refs'])}
        if item['id'] in decision.question_ids:
            proposals.append({'target_id': item['id'], 'correction': evidence['correction'],
                              'source_refs': copy.deepcopy(evidence['source_refs'])})
        if any(row['status'] == 'UNDECIDABLE' for row in evidence['option_judgments']):
            observations.append(observation)
    review = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
              'proposals': proposals, 'source_questions': []}
    _, _, owners = _inventory(packet, expected)
    judgments = [{**copy.deepcopy(row), 'question_id': owners[row['item_id']][0],
                  'option_index': owners[row['item_id']][1]} for row in raw_canonical['judgments']]
    evidence = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
                'bank_fingerprint': raw_canonical['bank_fingerprint'],
                'judgments': judgments,
                'unverified_observations': observations, 'semantic_approval': False}
    return review, evidence
