"""Versioned generation-time findings, separate from human/publication state."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.modules.ai.v3.revision_policy import (
    SIMPLE_COURSE_REVIEW_V9_POLICY,
    SIMPLE_COURSE_REVIEW_V10_POLICY,
    SIMPLE_COURSE_REVIEW_V11_POLICY,
    is_autonomous_editorial_policy,
)

DRAFT_REVIEW_VERSION = 'p30-editorial-draft-v1'


def _legacy_model_observation(owner: dict[str, Any], manifest: dict[str, Any], row: object) -> bool:
    """Recognize only the old serializer's misplaced, receipt-backed observation.

    This is a read projection, never a resolution or a rewrite of stored evidence.
    A false blocking flag alone cannot downgrade an unresolved finding.
    """
    if not isinstance(row, dict) or row.get('blocking') is not False:
        return False
    review = owner.get('simple_review')
    if owner.get('v3_review_policy') not in (
        SIMPLE_COURSE_REVIEW_V9_POLICY, SIMPLE_COURSE_REVIEW_V10_POLICY, SIMPLE_COURSE_REVIEW_V11_POLICY,
    ) or not isinstance(review, dict):
        return False
    source = manifest.get('source_fingerprint')
    result = manifest.get('draft_fingerprint')
    post = review.get('postedit_card_review')
    post_row = isinstance(row.get('id'), str) and row['id'].startswith('simple-v10-post-')
    if post_row:
        if (not isinstance(post, dict) or post.get('policy') != 'simple-postedit-card-review-v1'
                or post.get('source_fingerprint') != source or post.get('result_fingerprint') != result
                or post.get('semantic_approval') is not False):
            return False
        receipt = post.get('repair_receipt')
        draft = post.get('reviewed_course_fingerprint')
        receipt_key, prefix = 'finding_dispositions', 'simple-v10-post-'
    else:
        receipt = review.get('revision_receipt')
        draft = review.get('draft_fingerprint')
        receipt_key, prefix = 'review_finding_dispositions', 'simple-v9-model-'
    if not isinstance(receipt, dict) or not isinstance(receipt.get(receipt_key), list):
        return False
    if (any(not isinstance(v, str) or len(v) != 64 for v in (source, draft, result))
            or review.get('source_fingerprint') != source
            or receipt.get('source_fingerprint') != source or receipt.get('draft_fingerprint') != draft):
        return False
    if post_row and (receipt.get('result_fingerprint') != result or receipt.get('semantic_approval') is not False):
        return False
    matches = [v for v in receipt[receipt_key] if isinstance(v, dict)
               and isinstance(v.get('id'), str) and v['id']
               and row.get('id') == prefix + v['id']]
    if len(matches) != 1:
        return False
    disposition = matches[0]
    finding, decision = disposition.get('finding'), disposition.get('decision')
    if (disposition.get('model_resolved') is not True or disposition.get('evidence_valid') is not True
            or disposition.get('semantic_approval') is not False or disposition.get('status') != 'UNVERIFIED'
            or disposition.get('claimed_status') not in ('CORRECTED', 'ALREADY_SATISFIED', 'NOT_MATERIAL')
            or disposition.get('source_fingerprint') != source or disposition.get('draft_fingerprint') != draft
            or disposition.get('result_fingerprint') != result
            or not isinstance(finding, dict) or not isinstance(decision, dict)
            or not isinstance(finding.get('target'), dict)
            or not isinstance(finding.get('problem'), str) or not isinstance(decision.get('reason'), str)
            or decision.get('finding_id') != disposition['id']
            or decision.get('status') != disposition.get('claimed_status')):
        return False
    expected = {'id': prefix + disposition['id'], 'kind': 'editorial_review',
        'target_id': finding['target'].get('id') if finding['target'].get('kind') in ('lesson', 'question') else '',
        'message': finding['problem'] + ('\n' if post_row else '\nРешение ИИ-редактора: ') + decision['reason'],
        'source_refs': finding.get('source_refs'), 'blocking': False,
        'evidence': {'unverified': True, 'model_disposition': disposition['claimed_status'],
            'semantic_approval': False, 'source_fingerprint': source,
            'reviewed_draft_fingerprint': draft, 'result_fingerprint': result}}
    return row == expected


def read_draft_review(analysis: object) -> dict[str, Any] | None:
    if not isinstance(analysis, dict):
        return None
    raw = [analysis[key]['draft_review'] for key in ('evidence_v3', 'diagnostics')
           if isinstance(analysis.get(key), dict) and 'draft_review' in analysis[key]]
    if raw and any(value != raw[0] for value in raw):
        raise ValueError('draft_review_manifest_conflict')
    found = []
    for key in ('evidence_v3', 'diagnostics'):
        owner = analysis.get(key)
        if isinstance(owner, dict) and 'draft_review' in owner:
            value = deepcopy(owner['draft_review'])
            if (not isinstance(value, dict) or value.get('version') != DRAFT_REVIEW_VERSION
                    or value.get('generation_status') != 'draft_prepared'
                    or value.get('self_review_status') not in ('passed', 'needs_attention')
                    or value.get('human_review_required') is not True):
                raise ValueError('draft_review_manifest_invalid')
            if isinstance(value.get('issues'), list) and isinstance(value.get('observations'), list):
                projected = [row for row in value['issues'] if _legacy_model_observation(owner, value, row)]
                value['issues'] = [row for row in value['issues'] if row not in projected]
                value['observations'].extend(projected)
            if value.get('content_review_required') is False:
                receipt = value.get('automated_acceptance')
                if (not is_autonomous_editorial_policy(owner.get('v3_review_policy'))
                        or value.get('self_review_status') != 'passed' or value.get('issues') != []
                        or not isinstance(receipt, dict) or receipt != {
                            'policy': owner.get('v3_review_policy'),
                            'source_fingerprint': value.get('source_fingerprint'),
                            'draft_fingerprint': value.get('draft_fingerprint')}
                        or any(not isinstance(value.get(key), str) or len(value[key]) != 64
                               for key in ('source_fingerprint', 'draft_fingerprint'))):
                    raise ValueError('draft_review_manifest_invalid')
            if ('source_clarification_required' in value
                    and type(value['source_clarification_required']) is not bool):
                raise ValueError('draft_review_manifest_invalid')
            ids = []
            for field, blocking in (('issues', True), ('observations', False)):
                rows = value.get(field)
                if not isinstance(rows, list):
                    raise ValueError('draft_review_manifest_invalid')
                for row in rows:
                    if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                            or not row['id'] or not isinstance(row.get('message'), str)
                            or not row['message'].strip() or row.get('blocking') is not blocking
                            or not isinstance(row.get('source_refs'), list)
                            or any(not isinstance(ref, str) or not ref for ref in row['source_refs'])):
                        raise ValueError('draft_review_manifest_invalid')
                    ids.append(row['id'])
            if len(ids) != len(set(ids)):
                raise ValueError('draft_review_manifest_invalid')
            found.append(value)
    if found and any(value != found[0] for value in found):
        raise ValueError('draft_review_manifest_conflict')
    return deepcopy(found[0]) if found else None


def resolution_is_current(analysis: object, content_hash: str) -> bool:
    if not isinstance(analysis, dict) or 'unresolved_source_uncertainty' in analysis:
        return False
    resolution = analysis.get('source_uncertainty_resolution')
    return bool(isinstance(resolution, dict) and resolution.get('status') == 'resolved'
                and resolution.get('content_hash') == content_hash
                and resolution.get('resolved_by') and resolution.get('verified_revision')
                and isinstance(resolution.get('reason'), str) and len(resolution['reason'].strip()) >= 10)


def learning_content_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """P30 content identity excludes review bookkeeping, never learning content."""
    result = deepcopy(snapshot)
    course = result.get('course', {})
    analysis = course.get('source_analysis') if isinstance(course, dict) else None
    if not isinstance(analysis, dict) or read_draft_review(analysis) is None:
        return result
    for field in ('review_status', 'reviewed_by', 'reviewed_at', 'review_comment'):
        course.pop(field, None)
    for key in ('evidence_v3', 'diagnostics'):
        sub = analysis.get(key)
        if isinstance(sub, dict):
            sub.pop('defect_resolutions', None)
    for module in result.get('modules', []):
        for lesson in module.get('lessons', []):
            lesson.pop('source_validation_status', None)
            for quiz in lesson.get('quizzes', []):
                quiz.pop('review_status', None)
    return result
