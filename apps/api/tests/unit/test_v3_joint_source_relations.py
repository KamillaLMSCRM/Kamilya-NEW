import copy

import pytest

from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_semantic_cycle import (
    SOURCE_COMPLETENESS_SYSTEM,
    SOURCE_READING_SYSTEM,
    SOURCE_RELATION_GUIDE,
    SOURCE_VERIFY_SYSTEM,
    prepare_source_semantics,
)
from app.modules.ai.v3.practical_source_semantics import compile_source_semantics
from tests.unit.test_v3_source_semantics import packet, reading, verification


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_returned_relation_correction_preserves_source_and_other_rules(enabled):
    p = packet()
    raw = reading(p)
    raw['uncertainties'] = []
    raw['sections'][0]['rules'][0]['conditions'][0]['applies_to'] = 'person'
    original = copy.deepcopy(raw)
    compiled = compile_source_semantics(raw, p)
    checks = verification(p, compiled)
    corrected = copy.deepcopy(raw['sections'][0]['rules'][0])
    corrected['conditions'][0]['applies_to'] = 'credit'
    checks['rule_checks'][0].update(status='REVISE', replacement=[corrected],
                                   reason='The source qualifies the credit, not the person.')
    calls = []

    async def call(_name, _group, messages, fmt, validate):
        calls.append(messages)
        if len(calls) == 1:
            value = raw
        elif len(calls) == 2:
            value = checks
        else:
            value = {'source_fingerprint': p.fingerprint, 'additional_rules': [],
                     'verified_reading_fingerprint': fmt['json_schema']['schema']['properties'][
                         'verified_reading_fingerprint']['enum'][0]}
        validate(value)
        return copy.deepcopy(value)

    result = await prepare_source_semantics(p, 'ORIGINAL WITH EXACT CONDITIONS', PracticalModelView(p), call,
                                            relation_checks=enabled)
    assert len(calls) == 3
    assert calls[0][0]['content'] == SOURCE_READING_SYSTEM
    assert calls[2][0]['content'] == SOURCE_COMPLETENESS_SYSTEM
    assert calls[1][0]['content'] == SOURCE_VERIFY_SYSTEM + ('\n' + SOURCE_RELATION_GUIDE if enabled else '')
    assert all('ORIGINAL WITH EXACT CONDITIONS' in messages[1]['content'] for messages in calls)
    assert result['original_reading']['original'] == original == raw
    assert result['interpretations'][0]['status'] == 'REVISE'
    assert result['interpretations'][0]['custody_valid']
    assert result['interpretations'][0]['rule']['conditions'][0]['applies_to'] == 'credit'
    assert result['interpretations'][1]['rule'] == original['sections'][0]['rules'][1]
    assert all(row['status'] != 'SOURCE_AMBIGUITY' for row in result['interpretations'])


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [1, None, 'true'])
async def test_relation_policy_rejects_non_boolean_before_a_model_request(value):
    async def call(*args):
        raise AssertionError('No request is allowed for an invalid policy')

    p = packet()
    with pytest.raises(ValueError, match='source_relation_policy_invalid'):
        await prepare_source_semantics(p, 'source', PracticalModelView(p), call, relation_checks=value)


@pytest.mark.asyncio
@pytest.mark.parametrize('joint', [False, True])
async def test_only_joint_policy_requests_source_relation_verification(monkeypatch, joint):
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3 import practical_autonomous_editorial_cycle as cycle
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    doc = DirectSourceDocument('doc', 'Title', 'f', 'general', 'r1', (), source_text='Owned source.')
    corpus = DirectSourceCorpus('tenant', (doc,), len(doc.source_text), 0)
    p = build_practical_source_packet(corpus)
    observed = []

    class SourceBoundaryReachedError(Exception):
        pass

    async def prepare(_packet, context, _view, _call, **options):
        assert context
        observed.append(options)
        raise SourceBoundaryReachedError

    async def stage(*args):
        raise AssertionError('The source boundary must precede any course request')

    monkeypatch.setattr(cycle, 'prepare_source_semantics', prepare)
    with pytest.raises(SourceBoundaryReachedError):
        await cycle.run_autonomous_editorial_cycle(p, corpus, CourseIntent(), (), stage,
                                                  max_revisions=3, joint_editor=joint)
    assert observed == ([{'relation_checks': True}] if joint else [{}])
