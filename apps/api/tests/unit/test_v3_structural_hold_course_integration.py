import json

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3 import partitioned_extraction, service
from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity, V3Course
from app.modules.ai.v3.revision_policy import POLICY, REVIEW_POLICY
from tests.unit.test_v3_partitioned_extraction import Journal


@pytest.mark.asyncio
@pytest.mark.parametrize('unknown', [False, True])
async def test_course_keeps_lesson_hold_and_continues_or_propagates_unknown(monkeypatch, unknown):
    source = 'The clerk verifies the document before approval.'
    rule = RuleEntity('r', 's', 't', source, source_quote=source, doc_id='d1', source_revision='rev',
                      source_start=0, source_end=len(source))
    groups = [CurriculumGroup('g1', 'bad', 's', (rule,)), CurriculumGroup('g2', 'later', 's', (rule,))]
    document = DirectSourceDocument('d1', 't', 'f', 'general', 'rev', (), source_text=source)
    corpus = DirectSourceCorpus('tenant', (document,), len(source), 0)
    calls = []
    async def extract(*_args, **_kwargs):
        return DocumentRuleModel('t', 's', (rule,)), []
    async def generate(_self, *_args, **kwargs):
        label = kwargs['lesson_theme']
        calls.append('author:' + label)
        count = 1 if label == 'bad' else 5
        cases = []
        for index in range(count):
            wrong = ['skip checks!', 'delay checks!', 'ignore checks!'] if label == 'bad' else [
                f'Skip check {index} now', f'Delay check {index}', f'Ignore item {index}']
            cases.append({'case_id': f'case-{label}-{index}', 'rule_id': 'r', 'learning_objective': 'verify',
                'variants': [{'variant_id': f'v-{label}-{index}', 'scenario_premise': 'At the desk',
                'prompt': f'What action {label} {index}?', 'correct_option': {'text': 'Verify document'},
                'distractor_pool': [{'text': text} for text in wrong],
                'explanation': 'The clerk must verify the document.', 'source_quote': source}]})
        return V3Course.from_dict({'course_id': 'c', 'title': 't', 'lessons': [{
            'lesson_id': label, 'title': label, 'module_title': 't', 'content': 'The clerk verifies the document.',
            'covered_rule_ids': ['r'], 'cases': cases}]}).lessons[0]
    async def shortcut(lesson, *_args, **kwargs):
        calls.append('repair:' + lesson.lesson_id)
        assert kwargs.get('convergent_repair') is True
        if lesson.lesson_id == 'bad':
            report = service.validate_v3_course(V3Course(course_id='c', title='t', document_sha256='s',
                                                          lessons=(lesson,)), source)
            assert report.structural_verdict == 'FAIL'
            assert any('correct answer is longest' in issue for issue in report.violations)
            if unknown:
                raise service.ExtractionOutcomeUnknownError('synthetic_unknown')
            raise service.OptionShortcutRepairUnresolvedError(('Invariant 4 (Shortcut Gate) failed: synthetic',))
        return lesson, False
    async def unchanged(lesson, *_args, **_kwargs):
        return lesson, False
    async def diversity(**_kwargs):
        return None
    class PassCache:
        def wrap(self, pipeline):
            return pipeline
    async def prime(*_args, **_kwargs):
        return PassCache()
    async def review(_self, *_args, **_kwargs):
        return {'verdict': 'PASS', 'factual_score': 5, 'alignment_score': 5, 'didactic_score': 5,
                'summary': 'Independent review completed.', 'defects': []}
    async def entail(_self, *_args, **_kwargs):
        return {'verdict': 'SUPPORTED', 'claims': [{'claim': 'check', 'status': 'SUPPORTED', 'reason': 'source'}],
                'summary': 'supported'}
    async def options(_self, _scenario, _question, choices, *_args, **_kwargs):
        rows = []
        for index, choice in enumerate(choices):
            status = 'SUPPORTED' if choice == 'Verify document' else 'CONTRADICTED'
            rows.append({'index': index, 'verdict': status, 'omitted_required_elements': [], 'summary': 'reviewed',
                         'claims': [{'claim': choice, 'status': status, 'reason': 'source'}]})
        return {'options': rows}
    async def completeness(_self, *_args, **_kwargs):
        return {'answers': [{'index': 0, 'omissions': []}], 'explanation_review': await entail(None)}
    async def synthetic_provider(messages, _format):
        payload = json.loads(messages[1]['content'])
        if set(payload) != {'items'}:
            raise AssertionError('unexpected synthetic request')
        return {'items': [{'id': item['id'], 'verdict': 'COMPLETE', 'unsupported': [], 'summary': 'supported'}
                          for item in payload['items']]}
    monkeypatch.setattr(partitioned_extraction, 'extract_partitioned_rule_model', extract)
    monkeypatch.setattr(service, '_build_curriculum_groups', lambda *_args, **_kwargs: groups)
    monkeypatch.setattr(service.V3GenerationPipeline, 'generate_lesson_with_scenarios', generate)
    monkeypatch.setattr(service, '_repair_option_shortcuts', shortcut)
    monkeypatch.setattr(service, '_review_final_diversity', diversity)
    monkeypatch.setattr(BatchedReview, 'prime', prime)
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_lesson', review)
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_answer', entail)
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_question_options', options)
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_question_compatibility', options)
    monkeypatch.setattr(service.V3GenerationPipeline, 'review_answer_completeness', completeness)
    from app.modules.ai.v3 import explanation_repair
    monkeypatch.setattr(explanation_repair, 'repair_order_dependent_explanations', unchanged)
    kwargs = dict(corpus=corpus, intent=CourseIntent(), generation_client=synthetic_provider, extraction_journal=Journal(),
                  route_fingerprint='a' * 64, revision_policy=POLICY, review_policy=REVIEW_POLICY)
    if unknown:
        with pytest.raises(service.ExtractionOutcomeUnknownError, match='synthetic_unknown'):
            await service.generate_v3_course_from_corpus(**kwargs)
        assert calls == ['author:bad', 'repair:bad']
    else:
        artifacts = await service.generate_v3_course_from_corpus(**kwargs)
        assert calls == ['author:bad', 'repair:bad', 'author:later', 'repair:later']
        assert artifacts.diagnostics['requires_source_review'] is True
        assert any('bad' in issue and 'Shortcut Gate' in issue for issue in artifacts.diagnostics['violations'])
        assert len(artifacts.assessment.assessments) == 2
        assert [len(assessment.mcq) for assessment in artifacts.assessment.assessments] == [1, 5]
        assert artifacts.diagnostics['validation_report']['structural_verdict'] == 'PASS'
