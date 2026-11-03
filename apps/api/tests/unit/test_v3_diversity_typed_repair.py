import hashlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.v3.auxiliary_response_contracts import diversity_review_format
from app.modules.ai.v3.diversity_owned_selection_guard import build_owned_selection_guard
from app.modules.ai.v3.diversity_repair_selection import select_candidate
from app.modules.ai.v3.diversity_response_schema import (
    diversity_author_format,
    is_diversity_author_format,
    is_diversity_author_response,
)
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_v3_diversity_repair_selection import setup


def test_author_format_binds_variant_quote_and_parser_shape():
    fmt = diversity_author_format('v1', 'source')
    response = {'variant_id': 'v1', 'source_quote': 'source', 'branch_context': '', 'scenario_premise': 'case',
                'prompt': 'question', 'correct': 'correct', 'explanation': 'explain',
                'distractors': [{'text': str(i), 'category': 'role_confusion'} for i in range(3)]}
    assert is_diversity_author_format(fmt) and is_diversity_author_response(response, fmt)
    assert not is_diversity_author_response(response | {'variant_id': 'v2'}, fmt)
    assert not is_diversity_author_response(response | {'source_quote': 'other'}, fmt)
    assert not is_diversity_author_response(response | {'extra': 'x'}, fmt)


@pytest.mark.asyncio
@pytest.mark.parametrize('typed', [False, True])
async def test_owned_guard_reads_exact_policy_specific_review_plan(typed):
    args = setup()
    selected = select_candidate(**args)
    assert selected is not None
    corpus, rule, lesson = args['corpus'], args['rules'][0], args['lesson']
    journal = PendingStageJournal('tenant', uuid4(), 'job', object())
    response = {'fingerprint': selected.observation_fingerprint, 'status': 'observed',
                'overlaps': [[1, 2]], 'omissions': [{'rule_id': rule.rule_id, 'exact_quote': rule.source_quote}]}
    observed = []
    async def read(_session, _key, plan):
        observed.append(plan)
        return {'identity': _digest(plan), 'response': response, 'response_sha256': _digest(response)}
    journal.read_owned_value_in_session = AsyncMock(side_effect=read)
    guard = build_owned_selection_guard(lesson=lesson, corpus=corpus, rules=(rule,), journal=journal,
        expected_document_ids=('d1',), review_group_id='diversity:g',
        source_sha256=hashlib.sha256(corpus.documents[0].source_text.encode()).hexdigest(),
        route_fingerprint='b' * 64, selected=selected, typed_output=typed)
    assert await guard(object(), object(), {}) is True
    assert observed[0]['request_sha256']
    import json

    from app.modules.ai.v3.assessment_projection import project_lesson_questions
    from app.modules.ai.v3.diversity_review import _SYSTEM, POLICY, _hash
    from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest
    manifest = build_primary_source_manifest(corpus, (rule,), expected_tenant_id='tenant', expected_document_ids=('d1',))
    request = {'policy': POLICY, 'manifest_sha256': manifest.fingerprint,
               'primary_sources': [{'rule_id': rule.rule_id, 'text': manifest.fragments[0]}],
               'questions': [question.to_dict() for question in project_lesson_questions(lesson)]}
    fingerprint = _hash(request)
    messages = [{'role': 'system', 'content': _SYSTEM},
                {'role': 'user', 'content': json.dumps({**request, 'fingerprint': fingerprint}, ensure_ascii=False)}]
    expected = diversity_review_format(fingerprint, len(request['questions']), [rule.rule_id]) if typed else {'type': 'json_object'}
    assert observed[0]['request_sha256'] == _digest([messages, expected])
