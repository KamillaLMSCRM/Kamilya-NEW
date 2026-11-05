import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_applicability import SOURCE_APPLICABILITY_GUIDE
from app.modules.ai.v3.practical_contract import source_model_text
from app.modules.ai.v3.practical_cycle import (
    AUTHOR_SYSTEM,
    FRESH_AUTHOR_SYSTEM,
    PATCH_SYSTEM,
    practical_patch_messages,
)
from app.modules.ai.v3.practical_question_scope import scoped_course_view
from app.modules.ai.v3.practical_review import (
    REVIEW_SYSTEM,
    PracticalReviewDecision,
    practical_review_messages,
)
from app.modules.ai.v3.practical_source_audit import AUDIT_SYSTEM, source_audit_messages
from app.modules.ai.v3.response_contracts import response_contract
from app.modules.ai.v3.revision_policy import (
    ARBITRATED_PRACTICAL_REVIEW_POLICY,
    ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY,
    CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY,
    CONCISE_PRACTICAL_REVIEW_POLICY,
    CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY,
    COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY,
    DOMAIN_PRACTICAL_REVIEW_POLICY,
    EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY,
    EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY,
    MATERIALITY_PRACTICAL_REVIEW_POLICY,
    OWNED_AUDIT_PRACTICAL_REVIEW_POLICY,
    POLICY,
    PRACTICAL_REVIEW_POLICY,
    PREVIOUS_PRACTICAL_REVIEW_POLICY,
    QUESTION_BANK_PRACTICAL_REVIEW_POLICY,
    SCOPED_PRACTICAL_REVIEW_POLICY,
    SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
    STANDALONE_PRACTICAL_REVIEW_POLICY,
    TYPED_PRACTICAL_REVIEW_POLICY,
    is_practical_policy,
    read_review_policy,
    stamp_policy,
)
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from tests.unit.test_v3_practical_cycle import checked, model_wire

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def test_closed_practical_versions_and_fresh_stamp():
    assert PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v14'
    assert ARBITRATED_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v15'
    assert STANDALONE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v16'
    assert TYPED_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v17'
    assert COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v18'
    assert EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v19'
    assert QUESTION_BANK_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v20'
    assert OWNED_AUDIT_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v21'
    assert EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v22'
    assert CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v23'
    assert ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v24'
    assert MATERIALITY_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v25'
    assert CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v26'
    assert read_review_policy({'v3_review_policy': CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY}) == CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY
    assert stamp_policy({}, practical=True)['v3_review_policy'] == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    assert read_review_policy({'v3_review_policy': DOMAIN_PRACTICAL_REVIEW_POLICY}) == DOMAIN_PRACTICAL_REVIEW_POLICY
    assert is_practical_policy(MATERIALITY_PRACTICAL_REVIEW_POLICY)
    assert read_review_policy({'v3_review_policy': MATERIALITY_PRACTICAL_REVIEW_POLICY}) == MATERIALITY_PRACTICAL_REVIEW_POLICY
    assert is_practical_policy(ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY)
    assert read_review_policy({'v3_review_policy': ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY}) == ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY
    for version in (PREVIOUS_PRACTICAL_REVIEW_POLICY, SCOPED_PRACTICAL_REVIEW_POLICY, CONCISE_PRACTICAL_REVIEW_POLICY, PRACTICAL_REVIEW_POLICY, ARBITRATED_PRACTICAL_REVIEW_POLICY, STANDALONE_PRACTICAL_REVIEW_POLICY, TYPED_PRACTICAL_REVIEW_POLICY, COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY, EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY, QUESTION_BANK_PRACTICAL_REVIEW_POLICY, OWNED_AUDIT_PRACTICAL_REVIEW_POLICY, EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY, CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY):
        assert is_practical_policy(version)
        assert read_review_policy({'v3_review_policy': version}) == version
    assert SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v29'
    assert is_practical_policy(SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY)
    assert read_review_policy({'v3_review_policy': SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY}) == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    assert is_practical_policy('v3-practical-source-review-v30')
    assert is_practical_policy('v3-practical-source-review-v31')
    assert not is_practical_policy('v3-practical-source-review-v33')
    with pytest.raises(ValueError, match='v3_review_policy_invalid'):
        read_review_policy({'v3_review_policy': 'v3-practical-source-review-v33'})


def test_legacy_review_and_audit_prompts_preserve_projection_and_system_bytes(case):
    _, packet, course = case
    original = copy.deepcopy(course)
    legacy = scoped_course_view(packet, course, legacy_source_rule_scope=True)
    for lesson in legacy['lessons']:
        for question in lesson['questions']:
            del question['correct_index']
            del question['source_refs']
            del question['explanation']
    expected = (source_model_text(packet) + '\n\nГОТОВЫЙ КУРС. COURSE_JSON\n'
        + json.dumps(legacy, ensure_ascii=False, sort_keys=True, indent=2)
        + '\nPREVIOUS_FINDINGS_JSON\n' + json.dumps((), ensure_ascii=False, sort_keys=True, indent=2))
    review = practical_review_messages(packet, course, legacy_source_rule_scope=True)
    assert review == [{'role': 'system', 'content': REVIEW_SYSTEM}, {'role': 'user', 'content': expected}]
    audit = source_audit_messages(packet, course, legacy_source_rule_scope=True)
    assert audit[0]['content'] == AUDIT_SYSTEM
    assert legacy['lessons'][0]['questions'][0]['prompt'] in audit[1]['content']
    fresh = practical_review_messages(packet, course)
    assert fresh[0]['content'] == REVIEW_SYSTEM + SOURCE_APPLICABILITY_GUIDE
    assert original['lessons'][0]['questions'][0]['prompt'] in fresh[1]['content']
    assert 'По указанным положениям источника (' not in fresh[1]['content']
    assert source_audit_messages(packet, course)[0]['content'] == AUDIT_SYSTEM + SOURCE_APPLICABILITY_GUIDE
    decision = PracticalReviewDecision(False, False, (), ('q1',), False, ())
    assert practical_patch_messages(packet, course, decision, legacy_source_rule_scope=True)[0]['content'] == PATCH_SYSTEM
    assert practical_patch_messages(packet, course, decision)[0]['content'] == PATCH_SYSTEM + SOURCE_APPLICABILITY_GUIDE
    assert course == original


@pytest.mark.asyncio
@pytest.mark.parametrize('version,legacy', [(PREVIOUS_PRACTICAL_REVIEW_POLICY, True),
                                             (SCOPED_PRACTICAL_REVIEW_POLICY, False),
                                             (CONCISE_PRACTICAL_REVIEW_POLICY, False)])
async def test_real_dispatch_author_and_artifacts_remain_bound_to_saved_policy(case, version, legacy):
    corpus, packet, course = case
    calls, audits = [], []
    async def model(messages, fmt):
        calls.append((response_contract(fmt), messages))
        value = copy.deepcopy(course if response_contract(fmt) == 'practical_course' else checked(packet, course))
        if response_contract(fmt) == 'practical_review' and version == CONCISE_PRACTICAL_REVIEW_POLICY:
            del value['question_rules']
            del value['option_checks']
            value['answerability'] = [
                {'question_id': q['id'], 'possible_options': [q['correct_index']], 'status': 'UNIQUE',
                          'source_refs': q['source_refs'], 'reason': 'Only this answer applies.'}
                for lesson in course['lessons'] for q in lesson['questions']
            ]
        return value
    result = await generate_v3_course_from_corpus(corpus, intent=CourseIntent(audience='Staff'),
        generation_client=model_wire(packet, model, audits), revision_policy=POLICY, review_policy=version)
    author = next(messages for kind, messages in calls if kind == 'practical_course')
    assert author[0]['content'] == (AUTHOR_SYSTEM if legacy else FRESH_AUTHOR_SYSTEM + SOURCE_APPLICABILITY_GUIDE)
    assert ('по source_refs как область задания' in author[0]['content']) is legacy
    assert ('они не добавляют условий к вопросу' in author[0]['content']) is not legacy
    assert result.diagnostics['v3_review_policy'] == version
    assert result.diagnostics['practical_question_mode'] == ('source_rule_comprehension_v1' if legacy else 'authored_question_scope_v2')
    displayed = result.diagnostics['practical_display_course']['lessons'][0]['questions'][0]['prompt']
    assert displayed == scoped_course_view(packet, course, legacy_source_rule_scope=legacy)['lessons'][0]['questions'][0]['prompt']
    assert ('По указанным положениям источника (' in displayed) is legacy


@pytest.mark.asyncio
async def test_saved_v11_managed_worker_keeps_luna6_factory_profile(monkeypatch):
    from app.modules.ai.v3 import revision_policy
    from tests.unit import test_qa_luna_pending_isolation as pending_tests

    monkeypatch.setattr(revision_policy, 'PRACTICAL_REVIEW_POLICY', PREVIOUS_PRACTICAL_REVIEW_POLICY)
    await pending_tests.test_managed_factory_configuration_is_bound_before_generation(monkeypatch, practical=True)
