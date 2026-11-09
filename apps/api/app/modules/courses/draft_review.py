"""Versioned generation-time findings, separate from human/publication state."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.modules.ai.v3.revision_policy import is_autonomous_editorial_policy

DRAFT_REVIEW_VERSION = 'p30-editorial-draft-v1'


def read_draft_review(analysis: object) -> dict[str, Any] | None:
    if not isinstance(analysis, dict):
        return None
    found = []
    for key in ('evidence_v3', 'diagnostics'):
        owner = analysis.get(key)
        if isinstance(owner, dict) and 'draft_review' in owner:
            value = owner['draft_review']
            if (not isinstance(value, dict) or value.get('version') != DRAFT_REVIEW_VERSION
                    or value.get('generation_status') != 'draft_prepared'
                    or value.get('self_review_status') not in {'passed', 'needs_attention'}
                    or value.get('human_review_required') is not True):
                raise ValueError('draft_review_manifest_invalid')
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
