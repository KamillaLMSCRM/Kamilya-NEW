"""Frozen V9 teaching flow, one visible-card review and one scoped correction."""
from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, cast

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest, validate_practical_course
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_card_editorial_review import card_editorial_review_request, compile_card_editorial_review
from app.modules.ai.v3.simple_course_editor import SimpleCourseResult, _changes
from app.modules.ai.v3.simple_course_editor_v9 import run_simple_course_editor_v9
from app.modules.ai.v3.simple_editor_findings import compile_finding_dispositions, inventory
from app.modules.ai.v3.simple_postedit_cards import apply_postedit_cards, prepare_postedit_cards

POST_KEY = 'postedit_card_review'
POST_POLICY = 'simple-postedit-card-review-v1'


def _cards(course: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {q['id']: q for lesson in course['lessons'] for q in lesson['questions']}


def _question_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in review['findings'] if f['domain'] == 'assessment' and f['severity'] == 'material'
            and f['target']['kind'] == 'question']


def _revalidated_parent(base: SimpleCourseResult, final: dict[str, Any], packet: Any) -> dict[str, Any]:
    review = copy.deepcopy(base.review)
    receipt = review.get('revision_receipt')
    if final == base.course or not isinstance(receipt, dict):
        return review
    old = receipt.get('review_finding_dispositions', [])
    if old:
        fields = ('id', 'finding', 'origins', 'source_fingerprint', 'draft_fingerprint')
        items = [{key: row[key] for key in fields} for row in old]
        decisions = [row['decision'] for row in old if row.get('decision')]
        updated = compile_finding_dispositions(items, decisions, packet, base.draft, final)
        receipt['pre_postedit_finding_dispositions'] = copy.deepcopy(old)
        receipt['review_finding_dispositions'] = updated
        pending = {row['id']: row for row in receipt.get('unapplied_review_findings', [])}
        for row in updated:
            identity = 'simple-v9-unapplied-' + row['id']
            if not row['model_resolved']:
                pending[identity] = {**copy.deepcopy(row), 'id': identity}
        if pending:
            receipt['unapplied_review_findings'] = list(pending.values())
    return review


async def complete_card_review_v10(packet: Any, corpus: Any, intent: Any, base: SimpleCourseResult,
                                   stage: Any, *, additional_stage_callback: Any = None) -> SimpleCourseResult:
    before = validate_practical_course(base.course, packet)
    view = PracticalModelView(packet)
    messages, fmt, context = card_editorial_review_request(packet, corpus, intent, before, base.lesson_sources)
    before_fp = _digest(before)

    def review_valid(value: Any) -> dict[str, Any]:
        if not _matches(value, fmt['json_schema']['schema']):
            raise ValueError('simple_v10_review_shape_invalid')
        canonical = view.decode(value)
        compile_editorial_review(canonical, packet, before)
        return cast(dict[str, Any], canonical)

    wire = await stage('review', 'practical:simple:review-bank:v10:' + packet.fingerprint + ':unit=' + before_fp,
                       messages, fmt, review_valid)
    canonical_review = review_valid(wire)
    scope_status = 'valid'
    try:
        canonical_review = compile_card_editorial_review(wire, packet, before, context)
    except ValueError as exc:
        if str(exc) != 'simple_card_finding_scope_invalid':
            raise
        # An unsupported finding cannot suppress independent valid question findings.
        scope_status = 'partial'
    application_review = copy.deepcopy(canonical_review)
    application_review['findings'] = [f for f in canonical_review['findings']
        if (f['domain'] == 'assessment' and f['target']['kind'] == 'question')
        or (f['domain'] == 'source' and f['target']['kind'] == 'source')]
    # A question reviewer has no authority to replace unchanged lesson references.
    application_review['narrative_sources'] = {row['lesson_id']: copy.deepcopy(row['source_refs'])
                                              for row in base.lesson_sources}
    allowed = {f['target']['id'] for f in _question_findings(application_review)}
    source_observations: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    final = copy.deepcopy(before)
    status, application_error = 'not_needed', None
    repair_receipt: dict[str, Any] | None = None
    if allowed:
        if additional_stage_callback:
            await additional_stage_callback()
        repair_messages, repair_fmt, repair_context = prepare_postedit_cards(
            packet, corpus, intent, before, application_review)

        def repair_valid(value: Any) -> dict[str, Any]:
            if not _matches(value, repair_fmt['json_schema']['schema']):
                raise ValueError('simple_v10_repair_shape_invalid')
            return cast(dict[str, Any], view.decode(value))

        group = ('practical:simple:repair-cards:v10:' + packet.fingerprint + ':unit=' + before_fp
                 + ':proposal=' + _digest(application_review))
        proposal_wire = await stage('repair', group, repair_messages, repair_fmt, repair_valid)
        proposal = repair_valid(proposal_wire)
        decisions = copy.deepcopy(proposal['finding_dispositions'])
        source_observations = copy.deepcopy(proposal['source_questions'])
        try:
            envelope, repair_receipt = apply_postedit_cards(proposal, packet, before, repair_context)
            final = envelope['course']
            status = 'applied'
        except ValueError as exc:
            # Keep the completed course and proposal evidence; never apply out-of-scope edits.
            status = 'unapplied'
            application_error = str(exc) if str(exc).startswith('simple_') else 'simple_v10_repair_unapplied'
    review = _revalidated_parent(base, final, packet)
    old_cards = _cards(before)
    review[POST_KEY] = {
        'policy': POST_POLICY, 'source_fingerprint': packet.fingerprint,
        'pipeline_draft_fingerprint': _digest(base.draft), 'reviewed_course_fingerprint': before_fp,
        'result_fingerprint': _digest(final), 'review': canonical_review,
        'application_review': application_review, 'scope_status': scope_status,
        'application_status': status, 'application_error': application_error,
        'before_questions': {qid: copy.deepcopy(old_cards[qid]) for qid in sorted(allowed)},
        'question_fingerprints': {qid: _digest(q) for qid, q in old_cards.items()},
        'lesson_fingerprints': {lesson['id']: _digest([lesson['title'], lesson['content']]) for lesson in before['lessons']},
        'course_title_fingerprint': _digest(before['title']), 'lesson_sources_fingerprint': _digest(base.lesson_sources),
        'repair_decisions': decisions, 'repair_receipt': repair_receipt,
        'editor_source_observations': source_observations, 'semantic_approval': False,
    }
    review['method'] = 'unit-body-joint-editor-independent-visible-cards-v10'
    # Upstream source holds survive. A card corrector cannot create a new source-human gate.
    result = replace(base, course=final, changes=_changes(base.draft, final), review=review)
    postedit_review_state(result, packet)
    return result


def postedit_review_state(result: SimpleCourseResult, packet: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    post = result.review.get(POST_KEY)
    parent = result.review.get('editor_delta_receipts', {}).get('body', {})
    if parent.get('application_status') == 'applied':
        delta = parent.get('joint_delta_receipt', {})
        if delta.get('source_fingerprint') != packet.fingerprint or delta.get('draft_fingerprint') != _digest(result.draft):
            raise ValueError('simple_v10_parent_receipt_stale')
        expected_before = delta.get('result_fingerprint')
    elif parent.get('application_status') == 'unapplied':
        expected_before = _digest(result.draft)
    else:
        raise ValueError('simple_v10_parent_receipt_missing')
    if (not isinstance(post, dict) or post.get('policy') != POST_POLICY
            or post.get('source_fingerprint') != packet.fingerprint
            or post.get('pipeline_draft_fingerprint') != _digest(result.draft)
            or post.get('reviewed_course_fingerprint') != expected_before
            or post.get('result_fingerprint') != _digest(result.course)
            or post.get('lesson_sources_fingerprint') != _digest(result.lesson_sources)
            or post.get('course_title_fingerprint') != _digest(result.course['title'])
            or post.get('lesson_fingerprints') != {lesson['id']: _digest([lesson['title'], lesson['content']])
                                                   for lesson in result.course['lessons']}):
        raise ValueError('simple_v10_postedit_receipt_stale')
    before = copy.deepcopy(result.course)
    cards = _cards(before)
    review = post['review']
    expected_application = copy.deepcopy(review)
    expected_application['findings'] = [f for f in review['findings']
        if (f['domain'] == 'assessment' and f['target']['kind'] == 'question')
        or (f['domain'] == 'source' and f['target']['kind'] == 'source')]
    expected_application['narrative_sources'] = {row['lesson_id']: row['source_refs'] for row in result.lesson_sources}
    if post['application_review'] != expected_application:
        raise ValueError('simple_v10_application_review_stale')
    allowed = {f['target']['id'] for f in _question_findings(post['application_review'])}
    if set(post['before_questions']) != allowed or set(post['question_fingerprints']) != set(cards):
        raise ValueError('simple_v10_postedit_inventory_invalid')
    for lesson in before['lessons']:
        for index, question in enumerate(lesson['questions']):
            qid = question['id']
            if qid in allowed:
                previous = post['before_questions'][qid]
                if previous.get('id') != qid:
                    raise ValueError('simple_v10_postedit_inventory_invalid')
                lesson['questions'][index] = copy.deepcopy(previous)
            elif _digest(question) != post['question_fingerprints'][qid]:
                raise ValueError('simple_v10_unflagged_question_changed')
    if (_digest(before) != post['reviewed_course_fingerprint']
            or any(_digest(q) != post['question_fingerprints'][qid] for qid, q in _cards(before).items())):
        raise ValueError('simple_v10_postedit_inventory_invalid')
    compile_editorial_review(review, packet, before)
    compile_editorial_review(post['application_review'], packet, before)
    findings = inventory(packet.fingerprint, _digest(before), [('postedit_cards', review)])
    dispositions = compile_finding_dispositions(findings, post['repair_decisions'], packet, before, result.course)
    issues: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    common = {'unverified': True, 'semantic_approval': False, 'source_fingerprint': packet.fingerprint,
              'reviewed_draft_fingerprint': _digest(before), 'result_fingerprint': _digest(result.course)}
    for row in dispositions:
        f = row['finding']
        decision = row.get('decision') or {}
        issues.append({'id': 'simple-v10-post-' + row['id'], 'kind': 'editorial_review',
            'target_id': f['target']['id'] if f['target']['kind'] in ('question', 'lesson') else '',
            'message': f['problem'] + '\n' + (decision.get('reason') or f['correction']),
            'source_refs': copy.deepcopy(f['source_refs']), 'blocking': not row['model_resolved'],
            'evidence': {**common, 'model_disposition': row['claimed_status']}})
    source_hold = False
    for f in review['findings']:
        if f['domain'] == 'source' and f['target']['kind'] == 'source' and f['severity'] == 'material':
            source_hold = True
            issues.append({'id': 'simple-v10-source-' + _digest([packet.fingerprint, _digest(before), f])[:24],
                'kind': 'editorial_review', 'target_id': '', 'message': f['problem'],
                'source_refs': copy.deepcopy(f['source_refs']), 'blocking': True, 'evidence': common})
        elif f['domain'] == 'source' and f['severity'] == 'material':
            # Unsupported target scope remains visible without inventing source-human authority.
            issues.append({'id': 'simple-v10-unsupported-' + _digest([packet.fingerprint, _digest(before), f])[:24],
                'kind': 'editorial_review',
                'target_id': f['target']['id'] if f['target']['kind'] in ('question', 'lesson') else '',
                'message': f['problem'] + '\n' + f['correction'],
                'source_refs': copy.deepcopy(f['source_refs']), 'blocking': True, 'evidence': common})
    for row in post['editor_source_observations']:
        if (not isinstance(row, dict) or set(row) != {'question', 'source_refs'}
                or not isinstance(row['question'], str) or not row['question'].strip()
                or not row['source_refs'] or not set(row['source_refs']) <= {b.block_id for b in packet.blocks}):
            raise ValueError('simple_v10_editor_observation_invalid')
        observations.append({'id': 'simple-v10-editor-note-' + _digest([_digest(before), row])[:24],
            'kind': 'editorial_suggestion', 'target_id': '', 'message': row['question'],
            'source_refs': copy.deepcopy(row['source_refs']), 'blocking': False, 'evidence': common})
    if post['application_status'] == 'unapplied':
        issues.append({'id': 'simple-v10-card-application', 'kind': 'editorial_review', 'target_id': '',
            'message': 'Правки вопросов не применены. Проверьте сохранённые вопросы.',
            'source_refs': [next(b.block_id for b in packet.blocks if b.text.strip())],
            'blocking': True, 'evidence': {**common, 'application_error': post['application_error']}})
    return issues, observations, source_hold


async def run_simple_course_editor_v10(packet: Any, corpus: Any, intent: Any, stage: Any, *,
                                       reference_decisions: tuple[Any, ...] = (),
                                       planned_callback: Any = None) -> SimpleCourseResult:
    inner_count = 0

    async def planned(count: int) -> None:
        nonlocal inner_count
        inner_count = count
        if planned_callback:
            await planned_callback(count + 1)

    base = await run_simple_course_editor_v9(packet, corpus, intent, stage,
        reference_decisions=reference_decisions, planned_callback=planned)

    async def extra() -> None:
        if planned_callback:
            await planned_callback(inner_count + 2)

    return await complete_card_review_v10(packet, corpus, intent, base, stage, additional_stage_callback=extra)
