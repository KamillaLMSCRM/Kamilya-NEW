"""Publication regression from a complete synthetic production107 course."""
import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.courses.draft_review import learning_content_snapshot, read_draft_review
from app.modules.courses.source_uncertainty import get_active_source_defects, resolve_source_uncertainty
from tests.unit.test_course_source_uncertainty_api import _build_test_app, _make_course, _make_user


def saved_analysis():
    return json.loads((Path(__file__).parents[1] / 'fixtures/legacy_model_observations107.json').read_text(encoding='utf-8'))


def saved_post_analysis():
    source = saved_analysis()
    owner = source['evidence_v3']
    row = owner['draft_review']['issues'][1]
    disposition = copy.deepcopy(owner['simple_review']['revision_receipt']['review_finding_dispositions'][0])
    row['id'] = 'simple-v10-post-' + disposition['id']
    row['message'] = disposition['finding']['problem'] + '\n' + disposition['decision']['reason']
    source_fp, draft_fp, result_fp = (disposition[k] for k in ('source_fingerprint', 'draft_fingerprint', 'result_fingerprint'))
    owner['simple_review']['postedit_card_review'] = {
        'policy': 'simple-postedit-card-review-v1', 'semantic_approval': False,
        'source_fingerprint': source_fp, 'reviewed_course_fingerprint': draft_fp, 'result_fingerprint': result_fp,
        'repair_receipt': {'source_fingerprint': source_fp, 'draft_fingerprint': draft_fp,
            'result_fingerprint': result_fp, 'semantic_approval': False, 'finding_dispositions': [disposition]}}
    return source


@pytest.mark.parametrize('factory', [saved_analysis, saved_post_analysis])
def test_saved_course_projects_only_owned_nonblocking_observations_without_rewriting_history(factory):
    source = factory()
    original = copy.deepcopy(source)
    manifest = read_draft_review(source)
    assert source == original
    assert [row['id'] for row in manifest['issues']] == ['simple-editorial-review']
    assert manifest['observations'] == original['evidence_v3']['draft_review']['issues'][1:]
    assert manifest['human_review_required'] is True
    assert source['unresolved_source_uncertainty'] == original['unresolved_source_uncertainty']
    assert [row['defect_id'] for row in get_active_source_defects(source)] == ['simple-editorial-review']
    snapshot = {'course': {'source_analysis': source}, 'modules': []}
    assert learning_content_snapshot(snapshot)['course']['source_analysis'] == original
    resolved = resolve_source_uncertainty(source, reason='Reviewed every lesson and answer against approved source.',
        methodologist_user_id='methodologist', expected_content_hash='a' * 64, actual_content_hash='a' * 64,
        verified_revision='rev1', available_revisions=['rev1'], defect_resolutions=[{
            'defect_id': 'simple-editorial-review', 'action': 'manual_verification_passed',
            'rationale': 'Complete source, lesson and answer review passed.'}])
    assert resolved['evidence_v3']['draft_review'] == original['evidence_v3']['draft_review']


@pytest.mark.parametrize('fault', ['receipt', 'policy', 'source', 'result', 'approval', 'decision', 'duplicate'])
def test_legacy_post_projection_requires_exact_owned_repair_receipt(fault):
    source = saved_post_analysis()
    post = source['evidence_v3']['simple_review']['postedit_card_review']
    if fault == 'receipt':
        post.pop('repair_receipt')
    elif fault == 'policy':
        post['policy'] = []
    elif fault in {'source', 'result'}:
        post[fault + '_fingerprint'] = 'b' * 64
    elif fault == 'approval':
        post['repair_receipt']['semantic_approval'] = True
    elif fault == 'decision':
        post['repair_receipt']['finding_dispositions'][0]['decision']['reason'] = 'Altered claim'
    elif fault == 'duplicate':
        post['repair_receipt']['finding_dispositions'] *= 2
    with pytest.raises(ValueError, match='draft_review_manifest_'):
        read_draft_review(source)


@pytest.mark.parametrize('fault', ['receipt', 'policy', 'id', 'message', 'target', 'refs', 'status',
                                  'evidence', 'source', 'draft', 'result', 'duplicate', 'conflict', 'approval'])
def test_legacy_projection_rejects_unowned_or_altered_dispositions(fault):
    source = saved_analysis()
    owner = source['evidence_v3']
    manifest = owner['draft_review']
    row = manifest['issues'][1]
    disposition = owner['simple_review']['revision_receipt']['review_finding_dispositions'][0]
    if fault == 'receipt':
        owner.pop('simple_review')
    elif fault == 'policy':
        owner['v3_review_policy'] = 'unknown-policy'
    elif fault in {'id', 'message', 'target'}:
        row[{'target': 'target_id'}.get(fault, fault)] = 'altered'
    elif fault == 'refs':
        row['source_refs'] = ['foreign-ref']
    elif fault == 'status':
        disposition['model_resolved'] = False
    elif fault == 'evidence':
        disposition['evidence_valid'] = False
    elif fault in {'source', 'draft', 'result'}:
        row['evidence'][{'draft': 'reviewed_draft'}.get(fault, fault) + '_fingerprint'] = 'b' * 64
    elif fault == 'duplicate':
        manifest['observations'].append(copy.deepcopy(row))
    elif fault == 'conflict':
        source['diagnostics'] = copy.deepcopy(owner)
        source['diagnostics']['draft_review']['issues'][1]['message'] = 'Different historical copy'
    elif fault == 'approval':
        row['evidence']['semantic_approval'] = True
    with pytest.raises(ValueError, match='draft_review_manifest_'):
        read_draft_review(source)


@pytest.mark.parametrize('fault', ['policy', 'status', 'target', 'id'])
@pytest.mark.parametrize('bad', [None, [], {}])
def test_malformed_legacy_json_rejects_predictably(fault, bad):
    source = saved_analysis()
    owner = source['evidence_v3']
    disposition = owner['simple_review']['revision_receipt']['review_finding_dispositions'][0]
    if fault == 'policy':
        owner['v3_review_policy'] = bad
    elif fault == 'status':
        disposition['claimed_status'] = bad
    elif fault == 'target':
        disposition['finding']['target']['kind'] = bad
    else:
        disposition['id'] = bad
        owner['draft_review']['issues'][1]['id'] = 'simple-v9-model-' + str(bad)
    with pytest.raises(ValueError, match='draft_review_manifest_'):
        read_draft_review(source)


@pytest.mark.asyncio
async def test_saved_manifest_crosses_actual_snapshot_inspect_resolve_and_audit(monkeypatch):
    tenant, course_id = uuid4(), uuid4()
    user = _make_user(tenant_id=tenant)
    course = _make_course(course_id, tenant, source_analysis=saved_analysis())
    original = copy.deepcopy(course.source_analysis['evidence_v3'])
    audit = []
    app, session = _build_test_app(course, user, audit, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        inspected = await client.get(f'/courses/{course_id}/source-uncertainty')
        assert inspected.status_code == 200, inspected.text
        details = inspected.json()
        assert len(details['active_defects']) == 1 and len(details['draft_review']['observations']) == 2
        assert details['has_active_hold'] is True
        resolved = await client.post(f'/courses/{course_id}/resolve-source-uncertainty', json={
            'reason': 'Every lesson and question checked against the approved source.',
            'expected_content_hash': details['content_snapshot_hash'], 'verified_revision': 'rev-2026-qa1',
            'defect_resolutions': [{'defect_id': 'simple-editorial-review',
                'action': 'manual_verification_passed', 'rationale': 'Complete source and content review passed.'}]})
        assert resolved.status_code == 200, resolved.text
    assert session.query_had_lock and session.committed
    assert len(audit) == 1 and audit[0]['action'] == 'resolve_source_uncertainty'
    assert course.source_analysis['evidence_v3']['draft_review'] == original['draft_review']
    assert course.source_analysis['evidence_v3']['simple_review'] == original['simple_review']
