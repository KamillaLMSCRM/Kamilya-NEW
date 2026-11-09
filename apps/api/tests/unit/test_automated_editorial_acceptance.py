import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_service import practical_artifacts
from app.modules.ai.v3.revision_policy import (
    AUTONOMOUS_EDITORIAL_REVIEW_POLICY,
    COHERENT_EDITORIAL_REVIEW_POLICY,
    JOINT_EDITORIAL_REVIEW_POLICY,
)
from app.modules.courses.automated_editorial_acceptance import (
    KEY,
    automatic_acceptance_is_current,
    bind_automated_acceptance,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def clean_course(case, review_policy=AUTONOMOUS_EDITORIAL_REVIEW_POLICY):
    corpus, packet, course = case
    result = PracticalCycleResult(course,
        {'source_notes': [], 'narrative_sources': {lesson['id']: [b.block_id for b in packet.blocks] for lesson in course['lessons']}},
        PracticalReviewDecision(True, False, (), (), False, ()),
        ({'autonomous_editorial': True, 'verified_course_fingerprint': _digest(course)},),
        'automated_editorial_review_passed', standalone_review=True, editorial_review=True)
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64,
        editorial_policy=review_policy)
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), source_analysis={'evidence_v3': artifacts.diagnostics})


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['none', 'content', 'source', 'missing', 'duplicate', 'foreign'])
@pytest.mark.parametrize('review_policy', [AUTONOMOUS_EDITORIAL_REVIEW_POLICY, JOINT_EDITORIAL_REVIEW_POLICY, COHERENT_EDITORIAL_REVIEW_POLICY])
async def test_current_saved_content_proof_is_required_and_changes_invalidate_it(case, monkeypatch, drift, review_policy):
    course = clean_course(case, review_policy)
    job = SimpleNamespace(course_id=course.id, tenant_id=course.tenant_id, status='completed', stage='completed', result={})
    db = SimpleNamespace(flush=AsyncMock(), scalars=AsyncMock())
    compute = AsyncMock(return_value='a' * 64)
    monkeypatch.setattr('app.modules.courses.source_uncertainty.compute_course_content_snapshot_hash', compute)
    await bind_automated_acceptance(db, course=course, job=job)
    db.flush.assert_awaited_once()
    assert job.result[KEY]['content_hash'] == 'a' * 64
    content_hash = 'a' * 64
    jobs = [job]
    if drift == 'content':
        content_hash = 'b' * 64
    elif drift == 'source':
        course.source_analysis = copy.deepcopy(course.source_analysis)
        manifest = course.source_analysis['evidence_v3']['draft_review']
        manifest['source_fingerprint'] = 'c' * 64
        manifest['automated_acceptance']['source_fingerprint'] = 'c' * 64
    elif drift == 'missing':
        job.result = {}
    elif drift == 'duplicate':
        jobs *= 2
    elif drift == 'foreign':
        job.tenant_id = uuid4()
    db.scalars.return_value = SimpleNamespace(all=lambda: jobs)
    assert await automatic_acceptance_is_current(db, course=course, content_hash=content_hash) is (drift == 'none')


@pytest.mark.asyncio
async def test_failed_snapshot_never_writes_acceptance_or_commits(case, monkeypatch):
    course = clean_course(case)
    job = SimpleNamespace(course_id=course.id, tenant_id=course.tenant_id, status='completed', stage='completed', result={})
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr('app.modules.courses.source_uncertainty.compute_course_content_snapshot_hash',
        AsyncMock(side_effect=RuntimeError('snapshot_unknown')))
    with pytest.raises(RuntimeError, match='snapshot_unknown'):
        await bind_automated_acceptance(db, course=course, job=job)
    assert KEY not in job.result
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['none', 'content', 'source'])
@pytest.mark.parametrize('review_policy', [AUTONOMOUS_EDITORIAL_REVIEW_POLICY, JOINT_EDITORIAL_REVIEW_POLICY, COHERENT_EDITORIAL_REVIEW_POLICY])
async def test_ordinary_approval_requires_current_receipt_and_source_locks(case, monkeypatch, drift, review_policy):
    from fastapi import HTTPException

    from app.modules.courses.source_uncertainty import require_current_draft_review

    course = clean_course(case, review_policy)
    job = SimpleNamespace(course_id=course.id, tenant_id=course.tenant_id, status='completed', stage='completed', result={})
    db = SimpleNamespace(flush=AsyncMock(), scalars=AsyncMock())
    current = AsyncMock(return_value='a' * 64)
    monkeypatch.setattr('app.modules.courses.source_uncertainty.compute_course_content_snapshot_hash', current)
    await bind_automated_acceptance(db, course=course, job=job)
    db.scalars.return_value = SimpleNamespace(all=lambda: [job])
    source_lock = AsyncMock(return_value=([], {}, []))
    monkeypatch.setattr('app.modules.courses.router._extract_course_source_revisions', source_lock)
    if drift == 'content':
        current.return_value = 'b' * 64
    elif drift == 'source':
        source_lock.side_effect = ValueError('source_changed')
    if drift == 'none':
        await require_current_draft_review(db, course)
    else:
        with pytest.raises(HTTPException) as error:
            await require_current_draft_review(db, course)
        assert error.value.status_code == 409
    assert source_lock.await_args.kwargs['for_update'] is True


@pytest.mark.parametrize('review_policy', [AUTONOMOUS_EDITORIAL_REVIEW_POLICY, JOINT_EDITORIAL_REVIEW_POLICY, COHERENT_EDITORIAL_REVIEW_POLICY])
def test_embedded_receipt_cannot_be_swapped_between_autonomous_protocols(case, review_policy):
    from app.modules.courses.draft_review import read_draft_review

    course = clean_course(case, review_policy)
    manifest = course.source_analysis['evidence_v3']['draft_review']
    other = (JOINT_EDITORIAL_REVIEW_POLICY if review_policy == AUTONOMOUS_EDITORIAL_REVIEW_POLICY
             else AUTONOMOUS_EDITORIAL_REVIEW_POLICY)
    manifest['automated_acceptance']['policy'] = other
    with pytest.raises(ValueError, match='manifest_invalid'):
        read_draft_review(course.source_analysis)
