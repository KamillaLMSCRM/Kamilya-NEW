from uuid import uuid4

import pytest

from app.modules.ai import pipeline
from app.modules.ai.v3.native_profile_binding import KEY as PROFILE_KEY
from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_KEY
from app.modules.ai.v3.revision_policy import (
    CANONICAL_EDITORIAL_REVIEW_POLICY,
    EDITORIAL_ORDINARY_EXTENDED_MARKER,
    EDITORIAL_ORDINARY_KEY,
    EDITORIAL_ORDINARY_MARKER,
    EDITORIAL_PRACTICAL_REVIEW_POLICY,
    editorial_route_worker_valid,
)
from tests.unit.test_v3_native_final_source import install_fake_writer, native_fixture


def test_ordinary_route_rejects_mixed_or_mismatched_markers():
    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    args = dict(settings=None, tenant_id=uuid4(), user_id=uuid4(), course_id=None,
                stored=None, dispatched=None, ordinary_stored=EDITORIAL_ORDINARY_MARKER,
                ordinary_dispatched=EDITORIAL_ORDINARY_MARKER)
    assert editorial_route_worker_valid(**args)
    assert editorial_route_worker_valid(**(args | {
        'ordinary_stored': EDITORIAL_ORDINARY_EXTENDED_MARKER,
        'ordinary_dispatched': EDITORIAL_ORDINARY_EXTENDED_MARKER,
    }))
    for change in ({'tenant_id': QA_TENANT}, {'user_id': None}, {'course_id': uuid4()},
                   {'ordinary_stored': None}, {'ordinary_dispatched': 'forged'},
                   {'ordinary_dispatched': EDITORIAL_ORDINARY_EXTENDED_MARKER},
                   {'stored': 'qa'}, {'qa_dispatched': 'unknown'}, {'qa_stored': 'unknown'}):
        assert not editorial_route_worker_valid(**(args | change))


@pytest.mark.asyncio
@pytest.mark.parametrize('review_policy', [EDITORIAL_PRACTICAL_REVIEW_POLICY, CANONICAL_EDITORIAL_REVIEW_POLICY])
@pytest.mark.parametrize('drift', ['none', 'stored', 'dispatched', 'policy', 'qa', 'source', 'owner', 'profile', 'pending'])
async def test_ordinary_editorial_final_save_keeps_all_fences(monkeypatch, drift, review_policy):
    monkeypatch.setattr("app.core.config.get_settings", lambda: None)
    state, job, document = native_fixture(review_policy)
    monkeypatch.setattr("app.modules.ai.qa_luna_dev_route.QA_TENANT", uuid4())
    state.source_analysis[EDITORIAL_ORDINARY_KEY] = EDITORIAL_ORDINARY_MARKER
    job.params['source_analysis'][EDITORIAL_ORDINARY_KEY] = EDITORIAL_ORDINARY_MARKER
    tenant, actor = job.tenant_id, job.user_id
    if drift == 'stored':
        job.params['source_analysis'][EDITORIAL_ORDINARY_KEY] = 'forged'
    elif drift == 'dispatched':
        state.source_analysis[EDITORIAL_ORDINARY_KEY] = 'forged'
    elif drift == 'policy':
        job.params['source_analysis']['v3_review_policy'] = (
            CANONICAL_EDITORIAL_REVIEW_POLICY if review_policy == EDITORIAL_PRACTICAL_REVIEW_POLICY
            else EDITORIAL_PRACTICAL_REVIEW_POLICY)
    elif drift == 'qa':
        state.source_analysis[QA_KEY] = 'unknown'
    elif drift == 'source':
        document.content_sha256 = 'c' * 64
    elif drift == 'owner':
        job.user_id = uuid4()
    elif drift == 'profile':
        job.result[PROFILE_KEY]['fingerprint'] = 'c' * 64
    elif drift == 'pending':
        job.result['v3_pending_stages'] = None
    added = install_fake_writer(monkeypatch, job, document)
    if drift == 'none':
        await pipeline._save_generation_to_db(state, tenant, actor)
        assert added and job.course_id is not None
    else:
        with pytest.raises((ValueError, pipeline.DirectSourceError)):
            await pipeline._save_generation_to_db(state, tenant, actor)
        assert not added and job.course_id is None
