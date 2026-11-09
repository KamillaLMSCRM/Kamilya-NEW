"""Short practical cycle through the ordinary journal and persistence contracts."""
from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.extraction_checkpoint import ExtractionJournal
from app.modules.ai.v3.models import (
    RuleEntity,
    V3Course,
    V3Lesson,
    V3Option,
    V3Question,
)
from app.modules.ai.v3.practical_contract import (
    PracticalSourcePacket,
    _digest,
    build_practical_source_packet,
)
from app.modules.ai.v3.practical_cycle import PracticalCycleResult, run_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_scope import scoped_course_view
from app.modules.ai.v3.practical_source_reader import (
    source_read_format,
    source_read_messages,
    source_reader_parts,
    validate_source_read,
)
from app.modules.ai.v3.revision_policy import (
    ARBITRATED_PRACTICAL_REVIEW_POLICY,
    ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY,
    AUTONOMOUS_EDITORIAL_REVIEW_POLICY,
    CANONICAL_EDITORIAL_REVIEW_POLICY,
    CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY,
    COHERENT_EDITORIAL_REVIEW_POLICY,
    CONCISE_PRACTICAL_REVIEW_POLICY,
    CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY,
    COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY,
    DOMAIN_PRACTICAL_REVIEW_POLICY,
    EDITORIAL_PRACTICAL_REVIEW_POLICY,
    EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY,
    EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY,
    FOCUSED_EDITORIAL_REVIEW_POLICY,
    JOINT_EDITORIAL_REVIEW_POLICY,
    MATERIALITY_PRACTICAL_REVIEW_POLICY,
    OWNED_AUDIT_PRACTICAL_REVIEW_POLICY,
    PRACTICAL_MAX_OUTPUT_TOKENS,
    PRACTICAL_REVIEW_POLICY,
    PREVIOUS_PRACTICAL_REVIEW_POLICY,
    QUESTION_BANK_PRACTICAL_REVIEW_POLICY,
    SCOPED_PRACTICAL_REVIEW_POLICY,
    SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
    SOURCE_CORE_PRACTICAL_REVIEW_POLICY,
    SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY,
    STANDALONE_PRACTICAL_REVIEW_POLICY,
    TYPED_PRACTICAL_REVIEW_POLICY,
    is_autonomous_editorial_policy,
    is_editorial_policy,
    is_practical_policy,
)
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision


def practical_artifacts(result: PracticalCycleResult, corpus: DirectSourceCorpus,
                        packet: PracticalSourcePacket, source_sha256: str, *,
                        editorial_policy: str = EDITORIAL_PRACTICAL_REVIEW_POLICY) -> GenerationArtifacts:
    """Quotes are exact contiguous spans; source IDs are never retold or guessed by the model."""
    blocks = {block.block_id: block for block in packet.blocks}
    documents = {doc.doc_id: doc for doc in corpus.documents}
    rules = [RuleEntity(rule_id=b.block_id, section='', title='', statement='', source_quote=b.text,
                       doc_id=b.doc_id, source_revision=b.source_revision, source_start=b.start, source_end=b.end)
             for b in packet.blocks]
    narrative = result.review['narrative_sources']
    displayed = scoped_course_view(packet, result.course, legacy_source_rule_scope=result.legacy_source_rule_scope)
    review_policy = (editorial_policy if result.editorial_review else
                     SOURCE_CORE_PRACTICAL_REVIEW_POLICY if result.source_core else
                     SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY if result.separate_domains else
                     SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY if result.source_scope_complete else
                     DOMAIN_PRACTICAL_REVIEW_POLICY if result.review_domains else
                     CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY if result.claim_evidence else
                     MATERIALITY_PRACTICAL_REVIEW_POLICY if result.materiality_review else
                     ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY if result.assessment_coverage else
                     CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY if result.context_supplemented else
                     EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY if result.exclusive_options else
                     OWNED_AUDIT_PRACTICAL_REVIEW_POLICY if result.strict_audit_owners else
                     QUESTION_BANK_PRACTICAL_REVIEW_POLICY if result.question_bank_review else
                     EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY if result.explicit_case_author else
                     COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY if result.counterexample_review else
                     TYPED_PRACTICAL_REVIEW_POLICY if result.typed_findings else
                     STANDALONE_PRACTICAL_REVIEW_POLICY if result.standalone_review else
                     ARBITRATED_PRACTICAL_REVIEW_POLICY if result.arbitrated_review else
                     PRACTICAL_REVIEW_POLICY if result.lesson_scoped_review else
                     PREVIOUS_PRACTICAL_REVIEW_POLICY if result.legacy_source_rule_scope else
                     CONCISE_PRACTICAL_REVIEW_POLICY if result.concise_review else SCOPED_PRACTICAL_REVIEW_POLICY)
    lessons = []
    provenance_holds = []
    prose_provenance_holds = []
    revised_prose = set(result.history[0].get('unverified_revised_prose', [])) if result.editorial_review and result.history else set()
    for lesson in displayed['lessons']:
        covered = list(narrative[lesson['id']])
        if result.standalone_review and (not covered or lesson['id'] in revised_prose):
            prose_provenance_holds.append(lesson['id'])
        questions = []
        for q in lesson['questions']:
            refs = [blocks[ref] for ref in q['source_refs']]
            if not result.standalone_review:
                covered.extend(q['source_refs'])
            quote = ''
            rule_id = ''
            if len({ref.doc_id for ref in refs}) == 1:
                doc = documents[refs[0].doc_id]
                start, end = min(ref.start for ref in refs), max(ref.end for ref in refs)
                quote = (doc.source_text or '')[start:end]
                rule_id = 'practical-question:' + q['id']
                rules.append(RuleEntity(rule_id=rule_id, section='', title='', statement='', source_quote=quote,
                    doc_id=doc.doc_id, source_revision=doc.source_revision, source_start=start, source_end=end))
            else:
                # A single quote field cannot truthfully encode a cross-document proof.
                provenance_holds.append(q['id'])
            ordered = sorted(enumerate(q['choices']), key=lambda pair: hashlib.sha256(
                (packet.fingerprint + '\0' + q['id'] + '\0' + str(pair[0])).encode()).digest())
            questions.append(V3Question(question_id=q['id'], scenario_premise='', prompt=q['prompt'],
                options=tuple(V3Option(text=text, is_correct=index == q['correct_index'])
                              for index, text in ordered), explanation=q['explanation'],
                rule_id=rule_id, source_quote=quote))
        lessons.append(V3Lesson(lesson_id=lesson['id'], title=lesson['title'], module_title=result.course['title'],
            content=lesson['content'], covered_rule_ids=tuple(dict.fromkeys(covered)), questions=tuple(questions)))
    issues = [f"{row['scope']}:{row['id']}" for row in result.decision.feedback]
    issues.extend('question_context_unresolved:' + qid for qid in result.unresolved_question_context)
    issues.extend('curriculum_coverage_unresolved:' + goal for goal in result.unresolved_curriculum_goals)
    issues.extend('source_core_case_unresolved:' + case_id for case_id in result.source_core_unresolved_cases)
    if result.source_core_source_review_pending:
        issues.append('source_core_source_review_pending')
    if provenance_holds:
        issues.append('practical_cross_document_question_quote_requires_review')
    if prose_provenance_holds:
        issues.append('practical_lesson_prose_provenance_requires_review')
    source_verified = all(not doc.conversion_fidelity.needs_review
                          and not doc.review_only_source_unresolved
                          and not doc.review_only_source_context for doc in corpus.documents)
    accepted = (result.decision.accepted and not provenance_holds and not prose_provenance_holds
                and not result.unresolved_question_context
                and not result.unresolved_curriculum_goals
                and not result.source_core_unresolved_cases
                and not result.source_core_source_review_pending
                and (not result.claim_evidence or not result.decision.feedback))
    report = {'review_policy': review_policy,
              'automated_review_passed': accepted,
              'stop_reason': result.stop_reason, 'violations': issues,
              'coverage_review_signals': [row['note'] for row in result.review['source_notes']],
              'source_notes': result.review['source_notes'], 'practical_review_history': list(result.history)}
    course = V3Course(course_id='practical:' + packet.fingerprint, title=result.course['title'],
                      document_sha256=source_sha256, lessons=tuple(lessons),
                      # Source verification is independent of publication. The
                      # ordinary persistence layer still creates a draft course.
                      quality_verdict='verified' if accepted and source_verified and not result.source_core
                          and (not result.editorial_review or is_autonomous_editorial_policy(review_policy)) else 'needs_review',
                      validation_report=report)
    assessment_only = (review_policy in {CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY, SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY} and source_verified
        and not result.decision.source_uncertain and not provenance_holds and not prose_provenance_holds
        and not result.unresolved_question_context and bool(result.decision.feedback)
        and not result.unresolved_curriculum_goals
        and not result.source_core_unresolved_cases
        and not result.source_core_source_review_pending
        and all(row.get('scope') in ({'assessment', 'question'} if result.review_domains else {'assessment'})
                and isinstance(row.get('evidence'), dict)
                and 'original_finding' not in row['evidence'] for row in result.decision.feedback))
    autonomous_course_only = (is_autonomous_editorial_policy(review_policy) and source_verified
        and not result.decision.source_uncertain and not provenance_holds and not prose_provenance_holds
        and not result.source_core_source_review_pending and not result.source_core_unresolved_cases
        and bool(result.decision.feedback) and all(
            row.get('scope') in {'lesson', 'question', 'assessment', 'coverage'}
            and isinstance(row.get('evidence'), dict)
            and row['evidence'].get('status') == 'AUTOMATIC_REVIEW_UNRESOLVED'
            and row['evidence'].get('domain') in {'content', 'assessment'}
            and isinstance(row['evidence'].get('target'), dict)
            and row['evidence']['target'].get('kind') in {'lesson', 'question', 'course'}
            for row in result.decision.feedback))
    focused_pending = (review_policy == FOCUSED_EDITORIAL_REVIEW_POLICY and result.editorial_review
        and result.stop_reason == 'focused_review_pending' and not result.decision.accepted
        and result.review.get('source_fingerprint') == packet.fingerprint
        and result.review.get('course_fingerprint') == _digest(result.course)
        and bool(result.history) and result.history[0].get('focused_observations_unverified') is True
        and not result.decision.source_uncertain and source_verified and not provenance_holds
        and not result.source_core_source_review_pending and not result.source_core_unresolved_cases
        and not result.unresolved_question_context and not result.unresolved_curriculum_goals
        and all(row.get('scope') in {'question', 'assessment', 'lesson', 'coverage'}
                and isinstance(row.get('evidence'), dict)
                and row['evidence'].get('status') == 'AUTOMATIC_REVIEW_UNRESOLVED'
                for row in result.decision.feedback))
    artifacts = v3_course_to_generation_artifacts(course, source_document_ids=list(corpus.document_ids),
        source_corpus=corpus, source_rules=tuple(rules), canonical_source=True,
        **({'source_review_required': False} if assessment_only or autonomous_course_only or focused_pending else {}))
    for assessment, lesson in zip(artifacts.assessment.assessments, displayed['lessons'], strict=True):
        for question, raw in zip(assessment.mcq, lesson['questions'], strict=True):
            question.question = raw['prompt']
    artifacts.diagnostics.update({
        'v3_review_policy': review_policy, 'source_packet_fingerprint': packet.fingerprint,
        'automated_review_passed': accepted,
        'practical_course': result.course, 'practical_question_source_refs': {
            q['id']: q['source_refs'] for lesson in result.course['lessons'] for q in lesson['questions']},
        'practical_cross_document_question_ids': provenance_holds,
        'practical_unverified_prose_lesson_ids': prose_provenance_holds,
        'practical_display_course': displayed,
        'practical_source_readings': list(result.source_readings),
        **({'practical_curriculum_plan': result.curriculum_plan,
            'practical_unresolved_curriculum_goals': list(result.unresolved_curriculum_goals)}
           if result.curriculum_plan is not None else {}),
        **({'practical_unresolved_question_context': list(result.unresolved_question_context)}
           if result.context_supplemented else {}),
        'practical_question_mode': ('source_rule_comprehension_v1' if result.legacy_source_rule_scope
                                    else 'authored_question_scope_v2'),
    })
    if is_autonomous_editorial_policy(review_policy):
        from app.modules.ai.assessment_schema import PRESERVE_REVIEWED_OPTION_ORDER

        artifacts.diagnostics['assessment_option_order_policy'] = PRESERVE_REVIEWED_OPTION_ORDER
    if result.source_core or result.editorial_review:
        from app.modules.ai.v3.practical_draft_review import editorial_manifest

        artifacts.diagnostics['draft_review'] = editorial_manifest(result, packet, issues, review_policy=review_policy)
    if result.source_core:
        artifacts.diagnostics['practical_source_core_unresolved_cases'] = list(result.source_core_unresolved_cases)
        artifacts.diagnostics['practical_source_core_source_review_pending'] = result.source_core_source_review_pending
        artifacts.diagnostics['practical_unverified_source_proposals'] = [
            {'document_id': doc.doc_id, 'source_revision': doc.source_revision,
             'proposals': [dict(item) for item in doc.review_only_source_context], 'status': 'UNVERIFIED'}
            for doc in corpus.documents if doc.review_only_source_context
        ]
    if assessment_only:
        artifacts.diagnostics['requires_assessment_review'] = True
    if autonomous_course_only or focused_pending:
        artifacts.diagnostics['requires_editorial_review'] = True
    if focused_pending and set(artifacts.diagnostics.get('unresolved_source_provenance_lesson_ids', [])) == set(prose_provenance_holds):
        artifacts.diagnostics['requires_source_review'] = False
        artifacts.diagnostics['focused_editorial_only_provenance_pending'] = list(prose_provenance_holds)
    return artifacts


async def generate_practical_course(corpus: DirectSourceCorpus, *, intent: CourseIntent,
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    source_sha256: str, journal: ExtractionJournal | None, route_fingerprint: str,
    reference_decisions: tuple[SourceReferenceDecision, ...] = (), direct_client: Any = None,
    direct_max_output_tokens: int = PRACTICAL_MAX_OUTPUT_TOKENS,
    cancellation_callback: Callable[[], Awaitable[None]] | None = None,
    progress_callback: Callable[[str, int, int, str | None, int | None], Awaitable[None]] | None = None,
    review_policy: str = SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
) -> GenerationArtifacts:
    if not is_practical_policy(review_policy):
        raise ValueError('v3_review_policy_invalid')
    separate_domains = review_policy == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    if separate_domains:
        review_policy = SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY
    if journal is not None and journal.tenant_id != corpus.tenant_id:
        raise ValueError('practical_journal_owner_mismatch')
    if any(doc.review_only_source_unresolved for doc in corpus.documents):
        raise ValueError('practical_source_review_required')
    packet = build_practical_source_packet(corpus, reference_decisions)
    lesson_policies = {PRACTICAL_REVIEW_POLICY, ARBITRATED_PRACTICAL_REVIEW_POLICY, STANDALONE_PRACTICAL_REVIEW_POLICY,
                       TYPED_PRACTICAL_REVIEW_POLICY, COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY,
                       EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY, QUESTION_BANK_PRACTICAL_REVIEW_POLICY,
                       OWNED_AUDIT_PRACTICAL_REVIEW_POLICY, EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY,
                       CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY, ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY,
                       MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY,
                       SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY}
    editorial = is_editorial_policy(review_policy)
    parts = () if editorial or review_policy in lesson_policies or review_policy == SOURCE_CORE_PRACTICAL_REVIEW_POLICY else source_reader_parts(packet)
    view = PracticalModelView(packet)
    completed = 0
    estimated_lessons = 0

    async def stage(stage: str, group: str, messages: list[dict[str, str]], fmt: dict[str, Any],
                    validate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        nonlocal completed, estimated_lessons
        if cancellation_callback:
            await cancellation_callback()
        if journal is not None:
            from app.modules.ai.v3.stage_checkpoint import stage_once
            value = await stage_once(journal, stage=stage,
                group_id=group + ':output=' + str(direct_max_output_tokens), source_sha256=source_sha256,
                route_fingerprint=route_fingerprint, messages=messages, response_format=fmt,
                invoke=lambda: invoke(messages, fmt), direct_client=direct_client,
                direct_max_output_tokens=direct_max_output_tokens, response_validator=validate)
        else:
            value = await invoke(messages, fmt)
            validate(value)
        completed += 1
        if progress_callback:
            # Author + two checks per candidate + at most four scoped repairs.
            if editorial:
                await progress_callback('realization', completed,
                    max(4, completed + 1) if is_autonomous_editorial_policy(review_policy) else 4, None, 1)
            elif review_policy == SOURCE_CORE_PRACTICAL_REVIEW_POLICY:
                await progress_callback('realization', completed, 5, None, 1)
            elif review_policy in lesson_policies:
                if stage == 'lesson' and group == 'practical:author:v1':
                    estimated_lessons = len(value['lessons'])
                elif stage == 'repair':
                    estimated_lessons += len(value['new_lessons'])
                # Estimate four review rounds and three repairs. New lessons grow it.
                checks = 1 if review_policy == PRACTICAL_REVIEW_POLICY else 2
                total = max(completed + 1, 1 + (estimated_lessons + checks) * 4 + 3)
                await progress_callback('realization', completed, total, None, 1)
            else:
                await progress_callback('realization', completed, len(parts) + 15, None, 1)
        return value

    readings = []
    for part in parts:
        def validate_reading(value: dict[str, Any], checked_part: Any = part) -> None:
            validate_source_read(view.decode(value), packet, checked_part)
        value = await stage('review', 'practical:source-read:' + part.fingerprint,
            source_read_messages(packet, part, model_view=view), view.schema(source_read_format(packet, part)),
            validate_reading)
        readings.append(validate_source_read(view.decode(value), packet, part))
    if review_policy == FOCUSED_EDITORIAL_REVIEW_POLICY:
        from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings
        from app.modules.ai.v3.practical_focused_cycle import run_focused_cycle

        policy = await resolve_runtime_settings()
        result = await run_focused_cycle(packet, corpus, intent, reference_decisions, stage,
            max_output_tokens=direct_max_output_tokens,
            max_revisions=policy.integer('generation.editorial_max_revisions'))
    elif review_policy == COHERENT_EDITORIAL_REVIEW_POLICY:
        from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings
        from app.modules.ai.v3.practical_coherent_editorial_cycle import run_coherent_editorial_cycle

        policy = await resolve_runtime_settings()
        result = await run_coherent_editorial_cycle(packet, corpus, intent, reference_decisions, stage,
            max_revisions=policy.integer('generation.editorial_max_revisions'),
            max_output_tokens=direct_max_output_tokens)
    elif is_autonomous_editorial_policy(review_policy):
        from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings
        from app.modules.ai.v3.practical_autonomous_editorial_cycle import run_autonomous_editorial_cycle

        policy = await resolve_runtime_settings()
        result = await run_autonomous_editorial_cycle(packet, corpus, intent, reference_decisions, stage,
            max_revisions=policy.integer('generation.editorial_max_revisions'),
            max_rules_per_review=policy.integer('generation.editorial_rules_per_review'),
            **({'joint_editor': True, 'addressed_current': True}
               if review_policy == JOINT_EDITORIAL_REVIEW_POLICY else {}))
    elif editorial:
        from app.modules.ai.v3.practical_editorial_cycle import run_editorial_cycle
        result = await run_editorial_cycle(packet, corpus, intent, reference_decisions, stage,
            canonical_json=review_policy == CANONICAL_EDITORIAL_REVIEW_POLICY)
    elif review_policy == SOURCE_CORE_PRACTICAL_REVIEW_POLICY:
        from app.modules.ai.v3.practical_source_core_cycle import run_source_core_cycle
        result = await run_source_core_cycle(packet, corpus, intent, reference_decisions, stage)
    elif review_policy in lesson_policies:
        from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
        options = ({'adjudicate': True, 'standalone': True, 'typed_findings': True, 'counterexamples': True,
                    'explicit_cases': True, 'question_batch': True, 'strict_audit_owners': True,
                    **({'exclusive_options': True} if review_policy in {EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY, CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY, ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY, MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else {}),
                    **({'context_supplemented': True} if review_policy in {CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY, ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY, MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else {}),
                    **({'assessment_coverage': True} if review_policy in {ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY, MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else {}),
                    **({'materiality_review': True} if review_policy in {MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else {}),
                    **({'claim_evidence': True} if review_policy in {CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else {}),
                    **({'review_domains': True} if review_policy in {DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else {}),
                    **({'source_scope_complete': True, 'curriculum_review': True}
                       if review_policy == SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY else {})}
                    if review_policy in {OWNED_AUDIT_PRACTICAL_REVIEW_POLICY, EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY, CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY, ASSESSMENT_COVERAGE_PRACTICAL_REVIEW_POLICY, MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY} else
                   {'adjudicate': True, 'standalone': True, 'typed_findings': True, 'counterexamples': True,
                    'explicit_cases': True, 'question_batch': True} if review_policy == QUESTION_BANK_PRACTICAL_REVIEW_POLICY else
                   {'adjudicate': True, 'standalone': True, 'typed_findings': True, 'counterexamples': True,
                    'explicit_cases': True} if review_policy == EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY else
                   {'adjudicate': True, 'standalone': True, 'typed_findings': True, 'counterexamples': True}
                   if review_policy == COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY else
                   {'adjudicate': True, 'standalone': True, 'typed_findings': True} if review_policy == TYPED_PRACTICAL_REVIEW_POLICY else
                   {'adjudicate': True, 'standalone': True} if review_policy == STANDALONE_PRACTICAL_REVIEW_POLICY else
                   {'adjudicate': True} if review_policy == ARBITRATED_PRACTICAL_REVIEW_POLICY else {})
        if separate_domains:
            options['separate_domains'] = True
        result = await run_lesson_practical_cycle(packet, asdict(intent), stage, max_revisions=3, **options)
    else:
        result = await run_practical_cycle(packet, asdict(intent), stage, source_readings=tuple(readings),
                                           legacy_source_rule_scope=review_policy == PREVIOUS_PRACTICAL_REVIEW_POLICY,
                                           concise_review=review_policy == CONCISE_PRACTICAL_REVIEW_POLICY)
    if cancellation_callback:
        await cancellation_callback()
    if review_policy in (CANONICAL_EDITORIAL_REVIEW_POLICY, AUTONOMOUS_EDITORIAL_REVIEW_POLICY,
                         JOINT_EDITORIAL_REVIEW_POLICY, COHERENT_EDITORIAL_REVIEW_POLICY, FOCUSED_EDITORIAL_REVIEW_POLICY):
        return practical_artifacts(result, corpus, packet, source_sha256, editorial_policy=review_policy)
    return practical_artifacts(result, corpus, packet, source_sha256)
