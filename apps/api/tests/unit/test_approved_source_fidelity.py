"""Native prepared-source metadata survives approval and the course save contract."""
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.modules.ai.direct_source import DirectSourceError, build_direct_source_corpus
from app.modules.ai.source_fidelity import ConversionFidelity
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_service import practical_artifacts
from app.modules.ai.v3.revision_policy import COHERENT_EDITORIAL_REVIEW_POLICY
from app.modules.courses.automated_editorial_acceptance import clean_manifest
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text, text_hash

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
NATIVE = {'pages': 9, 'engine': 'native-source-preparation', 'profile': 'visual_and_text',
          'warnings': [], 'fallback_used': False, 'engine_version': 'source-preparation-v1'}


@pytest.mark.asyncio
@pytest.mark.parametrize('metadata,expected', [
    (NATIVE, 'clean'),
    ({}, 'unverified'),
    ({**NATIVE, 'warnings': ['Image text uncertain']}, 'degraded'),
    ({key: value for key, value in NATIVE.items() if key != 'warnings'}, 'unverified'),
    ({**NATIVE, 'warnings': 'not a typed list'}, 'unverified'),
    (asdict(ConversionFidelity.from_metadata(NATIVE)), 'clean'),
    ({**NATIVE, 'metadata_present': False, 'metadata_verified': False}, 'unverified'),
])
async def test_approved_native_fidelity_controls_real_artifact_hold(case, metadata, expected):
    original, _, course = case
    source = original.documents[0]
    text = source.source_text
    working, spans = render_text(text, [])
    doc = SimpleNamespace(id=source.doc_id, tenant_id=original.tenant_id, title=source.title,
        filename=source.filename, category=source.category, lifecycle_status='active', content_sha256=text_hash(text))
    approved = ApprovedEditorialDocument(source.doc_id, 'document:' + doc.content_sha256, 'approval',
        text, working, text_hash(working), tuple(spans), metadata)
    storage = Mock()
    corpus = await build_direct_source_corpus([doc], tenant_id=original.tenant_id, storage=storage,
                                              approved_documents={source.doc_id: approved})
    assert corpus.documents[0].conversion_fidelity.status == expected
    assert corpus.documents[0].source_text == text
    storage.get_bytes.assert_not_called()
    packet = build_practical_source_packet(corpus)
    result = PracticalCycleResult(course,
        {'source_notes': [], 'narrative_sources': {lesson['id']: [b.block_id for b in packet.blocks]
                                                 for lesson in course['lessons']}},
        PracticalReviewDecision(True, False, (), (), False, ()),
        ({'autonomous_editorial': True, 'verified_course_fingerprint': _digest(course)},),
        'automated_editorial_review_passed', standalone_review=True, editorial_review=True)
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64, editorial_policy=COHERENT_EDITORIAL_REVIEW_POLICY)
    assert artifacts.diagnostics['requires_source_review'] is (expected != 'clean')
    assert (clean_manifest({'evidence_v3': artifacts.diagnostics}) is not None) is (expected == 'clean')


@pytest.mark.asyncio
async def test_approved_lossy_scanned_fallback_is_still_blocked(case):
    original, _, _ = case
    source = original.documents[0]
    text = source.source_text
    working, spans = render_text(text, [])
    doc = SimpleNamespace(id=source.doc_id, tenant_id=original.tenant_id, title=source.title,
        filename=source.filename, category=source.category, lifecycle_status='active', content_sha256=text_hash(text))
    approved = ApprovedEditorialDocument(source.doc_id, 'document:' + doc.content_sha256, 'approval',
        text, working, text_hash(working), tuple(spans), {**NATIVE, 'profile': 'scanned_or_low_text', 'fallback_used': True})
    with pytest.raises(DirectSourceError, match='editorial_unproved'):
        await build_direct_source_corpus([doc], tenant_id=original.tenant_id, storage=Mock(),
                                        approved_documents={source.doc_id: approved})
