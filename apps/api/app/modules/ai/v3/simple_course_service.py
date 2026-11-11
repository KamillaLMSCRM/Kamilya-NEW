"""Lean course editor on the existing journal and ordinary draft persistence DTOs."""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from app.modules.ai.architect_schema import CourseStructure, LearningObjective
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import (
    PRESERVE_REVIEWED_OPTION_ORDER,
    CourseAssessment,
    LessonAssessment,
    MCQOption,
    MCQQuestion,
)
from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.v3.practical_contract import (
    PracticalSourceBlock,
    PracticalSourcePacket,
    _digest,
    build_practical_source_packet,
)
from app.modules.ai.v3.simple_course_editor import (
    SimpleCourseResult,
    _editor_format,
    _source_context,
    matches_simple_editor,
    run_simple_course_editor,
)
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.modules.courses.draft_review import DRAFT_REVIEW_VERSION


def simple_stage_allowed(stage: Any, group: Any, fmt: Any, *, policy: Any, validator: Any) -> bool:
    from app.modules.ai.v3.response_contracts import response_contract
    from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY

    versions = {SIMPLE_COURSE_REVIEW_POLICY: 'v1', SIMPLE_COURSE_REVIEW_V2_POLICY: 'v2'}
    if type(group) is not str or type(policy) is not str or policy not in versions or not callable(validator):
        return False
    match = re.fullmatch(r'practical:simple:(author|review|review-content|review-assessment|review-explanations|editor):(v[12]):([0-9a-f]{64}):output=[1-9][0-9]*', group)
    if not match or match[2] != versions[policy]:
        return False
    if (match[1] == 'review' and match[2] != 'v1'
            or match[1] in {'review-content', 'review-assessment', 'review-explanations'} and match[2] != 'v2'):
        return False
    expected = {'author': ('lesson', 'practical_course'),
                'review': ('review', 'simple_course_review'),
                'review-content': ('review', 'practical_editorial_review'),
                'review-assessment': ('review', 'practical_option_predicates'),
                'review-explanations': ('review', 'simple_course_review'),
                'editor': ('repair', 'simple_course_editor')}
    if match[2] == 'v2':
        expected['editor'] = ('repair', 'simple_course_revision_v2')
    if (stage, response_contract(fmt)) != expected[match[1]]:
        return False
    return match[1] == 'author' or fmt['json_schema']['schema']['properties']['source_fingerprint']['enum'] == [match[3]]


def _pinned_spans(blocks: list[PracticalSourceBlock], corpus: DirectSourceCorpus) -> list[dict[str, Any]]:
    """Persistence spans have no borrowed limit from a separate correction-tool prompt."""
    docs = {doc.doc_id: doc for doc in corpus.documents}
    merged: list[tuple[str, int, int]] = []
    for b in sorted(blocks, key=lambda b: (b.doc_id, b.start, b.end)):
        text = docs[b.doc_id].source_text
        if (not isinstance(text, str) or b.source_revision != docs[b.doc_id].source_revision
                or text[b.start:b.end] != b.text):
            raise ValueError('simple_source_reference_invalid')
        if merged and b.doc_id == merged[-1][0] and b.start <= merged[-1][2]:
            previous = merged[-1]
            merged[-1] = (previous[0], previous[1], max(previous[2], b.end))
        else:
            merged.append((b.doc_id, b.start, b.end))
    return [{'kind': 'working_text_span_v1', 'doc_id': doc_id,
        'source_revision': docs[doc_id].source_revision,
        'source_text_sha256': hashlib.sha256((docs[doc_id].source_text or '').encode('utf-8')).hexdigest(),
        'start': start, 'end': end,
        'span_sha256': hashlib.sha256((docs[doc_id].source_text or '')[start:end].encode('utf-8')).hexdigest()}
        for doc_id, start, end in merged]


def _question_quote(blocks: list[PracticalSourceBlock], corpus: DirectSourceCorpus) -> str:
    if len({b.doc_id for b in blocks}) != 1:
        return ''
    text = next(doc.source_text for doc in corpus.documents if doc.doc_id == blocks[0].doc_id) or ''
    ordered = sorted(blocks, key=lambda b: (b.start, b.end))
    end = ordered[0].end
    for b in ordered[1:]:
        if b.start > end and text[end:b.start].strip():
            return ''  # Keep separate selected refs, never quote unselected intervening instructions.
        end = max(end, b.end)
    return text[ordered[0].start:end]


def simple_course_artifacts(result: SimpleCourseResult, corpus: DirectSourceCorpus,
                            packet: PracticalSourcePacket, source_sha256: str, *,
                            review_policy: str | None = None) -> GenerationArtifacts:
    """Pin proposed references to owned source spans, without semantic certification."""
    from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY

    if review_policy is None:
        review_policy = SIMPLE_COURSE_REVIEW_POLICY
    if review_policy not in {SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY}:
        raise ValueError('simple_materialization_policy_invalid')

    _source_context(packet, corpus, {})
    envelope = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(result.draft),
                'course': result.course, 'source_questions': result.source_questions,
                'lesson_sources': result.lesson_sources}
    if not matches_simple_editor(envelope, _editor_format(
            [b.block_id for b in packet.blocks], packet.fingerprint, _digest(result.draft))):
        raise ValueError('simple_materialization_invalid')
    by_id = {b.block_id: b for b in packet.blocks}
    mapping = {row['lesson_id']: row['source_refs'] for row in result.lesson_sources}
    source_hold = bool(result.source_questions or any(doc.conversion_fidelity.needs_review
        or doc.review_only_source_unresolved or doc.review_only_source_context for doc in corpus.documents))
    structures, contents, assessments = [], [], []
    for lesson in result.course['lessons']:
        references = _pinned_spans([by_id[ref] for ref in mapping[lesson['id']]], corpus)
        structures.append(StructureLesson(title=lesson['title'],
            objectives=[LearningObjective(text=lesson['title'])],
            source_doc_ids=list(dict.fromkeys(ref['doc_id'] for ref in references))))
        contents.append(LessonContent(title=lesson['title'], content=lesson['content'],
            source_references=references, source_validation_status='needs_review' if source_hold else 'verified'))
        questions = []
        for q in lesson['questions']:
            quote = _question_quote([by_id[ref] for ref in q['source_refs']], corpus)
            questions.append(MCQQuestion(question=q['prompt'], explanation=q['explanation'], source_quote=quote,
                options=[MCQOption(text=text, is_correct=i == q['correct_index']) for i, text in enumerate(q['choices'])]))
        assessments.append(LessonAssessment(lesson_title=lesson['title'], mcq=questions))
    course = copy.deepcopy(result.course)
    source_questions = {_digest(row): row for row in result.source_questions}
    issues = [{'id': 'simple-source-' + identity[:24], 'kind': 'source_question', 'target_id': '',
        'message': row['question'], 'source_refs': row['source_refs'], 'blocking': True}
        for identity, row in source_questions.items()]
    issues.append({'id': 'simple-editorial-review', 'kind': 'editorial_review', 'target_id': '',
        'message': 'Проверьте уроки и тесты перед согласованием курса.', 'source_refs': [], 'blocking': True})
    receipt = result.review.get('revision_receipt', {})
    if receipt and (receipt.get('source_fingerprint') != packet.fingerprint
                    or receipt.get('draft_fingerprint') != _digest(result.draft)):
        raise ValueError('simple_revision_receipt_stale')
    for row in receipt.get('unverified_source_questions', []):
        issues.append({'id': row['id'], 'kind': 'editorial_review', 'target_id': '',
            'message': row['question'], 'source_refs': row['source_refs'], 'blocking': True,
            'evidence': {'unverified': True, 'source_fingerprint': packet.fingerprint,
                         'reviewed_draft_fingerprint': _digest(result.draft)}})
    for row in receipt.get('unapplied_review_findings', []):
        if (row.get('source_fingerprint') != packet.fingerprint
                or row.get('draft_fingerprint') != _digest(result.draft)):
            raise ValueError('simple_unapplied_review_stale')
        finding = row['finding']
        target = finding['target']
        issues.append({'id': row['id'], 'kind': 'editorial_review',
            'target_id': target['id'] if target['kind'] in {'lesson', 'question'} else '',
            'message': finding['problem'] + '\n' + finding['correction'],
            'source_refs': finding['source_refs'], 'blocking': True,
            'evidence': {'unverified': True, 'source_fingerprint': packet.fingerprint,
                         'reviewed_draft_fingerprint': _digest(result.draft)}})
    independent = result.review.get('independent_option_review', {})
    if independent:
        if (independent.get('source_fingerprint') != packet.fingerprint
                or independent.get('draft_fingerprint') != _digest(result.draft)):
            raise ValueError('simple_independent_review_stale')
        final_questions = {question['id']: question for lesson in course['lessons'] for question in lesson['questions']}
        owned_refs = {block.block_id for block in packet.blocks}
        for row in independent.get('unverified_observations', []):
            question_id = row['question_id']
            if (question_id not in final_questions or row.get('status') != 'UNVERIFIED'
                    or not set(row['source_refs']).issubset(owned_refs)):
                raise ValueError('simple_independent_observation_invalid')
            issues.append({'id': 'simple-independent-' + _digest([packet.fingerprint, _digest(result.draft), question_id])[:24],
                'kind': 'editorial_review', 'target_id': question_id, 'message': row['problem'],
                'source_refs': row['source_refs'], 'blocking': True,
                'evidence': {'unverified': True, 'source_fingerprint': packet.fingerprint,
                    'reviewed_draft_fingerprint': _digest(result.draft),
                    'current_question_fingerprint': _digest(final_questions[question_id])}})
    observations = [{'id': 'simple-observation-' + str(i), 'kind': 'editorial_suggestion',
        'target_id': row['target_id'], 'message': row['correction'], 'source_refs': row['source_refs'],
        'blocking': False, 'evidence': {'unverified': True, 'reviewed_draft_fingerprint': _digest(result.draft)}}
        for i, row in enumerate(result.review['proposals'])]
    diagnostics = {'generation_engine': 'v3_cogen', 'v3_review_policy': review_policy,
        'document_sha256': source_sha256, 'source_packet_fingerprint': packet.fingerprint,
        'lessons_count': len(contents), 'assessments_count': len(assessments),
        'quality_verdict': 'needs_review', 'automated_review_passed': False,
        'requires_source_review': source_hold, 'requires_editorial_review': True,
        'practical_course': course, 'practical_display_course': copy.deepcopy(course),
        'practical_question_source_refs': {q['id']: q['source_refs'] for lesson in course['lessons'] for q in lesson['questions']},
        'assessment_option_order_policy': PRESERVE_REVIEWED_OPTION_ORDER,
        'simple_source_order': copy.deepcopy(result.plan), 'simple_review': copy.deepcopy(result.review),
        'simple_changed_paths': list(result.changes), 'simple_lesson_sources': copy.deepcopy(result.lesson_sources),
        'draft_review': {'version': DRAFT_REVIEW_VERSION, 'generation_status': 'draft_prepared',
            'self_review_status': 'needs_attention', 'human_review_required': True,
            'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(course),
            'source_clarification_required': source_hold, 'content_review_required': True,
            'issues': issues, 'observations': observations}}
    title = course['title']
    return GenerationArtifacts(
        CourseStructure(title=title, modules=[StructureModule(title=title, lessons=structures)]),
        CourseContent(title=title, modules=[ModuleContent(title=title, lessons=contents)]),
        CourseAssessment(assessments=assessments), diagnostics)


async def generate_simple_course(corpus: DirectSourceCorpus, *, intent: Any, invoke: Any,
    source_sha256: str, journal: Any, route_fingerprint: str, reference_decisions: tuple[SourceReferenceDecision, ...] = (),
    direct_client: Any = None, direct_max_output_tokens: int,
    cancellation_callback: Any = None, progress_callback: Any = None,
    review_policy: str | None = None) -> GenerationArtifacts:
    from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY

    review_policy = SIMPLE_COURSE_REVIEW_POLICY if review_policy is None else review_policy
    if review_policy not in {SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY}:
        raise ValueError('simple_service_policy_invalid')
    total = 5 if review_policy == SIMPLE_COURSE_REVIEW_V2_POLICY else 3
    packet = build_practical_source_packet(corpus, reference_decisions)
    completed = 0

    async def stage(name: str, group: str, messages: list[dict[str, str]], fmt: dict[str, Any], validator: Any) -> Any:
        nonlocal completed
        if cancellation_callback:
            await cancellation_callback()
        if journal is not None:
            from app.modules.ai.v3.stage_checkpoint import stage_once

            value = await stage_once(journal, stage=name, group_id=group + ':output=' + str(direct_max_output_tokens),
                source_sha256=source_sha256, route_fingerprint=route_fingerprint, messages=messages,
                response_format=fmt, invoke=lambda: invoke(messages, fmt), direct_client=direct_client,
                direct_max_output_tokens=direct_max_output_tokens, response_validator=validator)
        else:
            from app.modules.ai.v3.practical_author_transport import (
                PracticalAuthorArtifact,
                validate_practical_author_artifact,
            )

            value = await invoke(messages, fmt)
            if type(value) is PracticalAuthorArtifact:
                if not validate_practical_author_artifact(value, fmt):
                    raise ValueError('simple_author_custody_invalid')
                value = value.normalized_value
            validator(value)
        completed += 1
        if progress_callback:
            await progress_callback('realization', completed, total, None, 1)
        return value

    if review_policy == SIMPLE_COURSE_REVIEW_V2_POLICY:
        from app.modules.ai.v3.simple_course_editor_v2 import run_simple_course_editor_v2

        result = await run_simple_course_editor_v2(packet, corpus, intent, stage)
    else:
        result = await run_simple_course_editor(packet, corpus, intent, stage)
    return simple_course_artifacts(result, corpus, packet, source_sha256, review_policy=review_policy)
