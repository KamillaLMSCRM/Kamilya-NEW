"""Original-source HTTP adapter must not consult vector-index readiness."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import router, source_analysis
from app.modules.ai.schemas import AIGenerateRequest, DocumentCompatibilityRequest


def analysis_for(ids):
    return source_analysis.CompatibilityAnalysis(
        status='unverified', score=None, requires_decision=len(ids) > 1, clusters=(),
        analysis_mode='direct_source', source_chunk_totals={doc_id: 3 for doc_id in ids},
        source_languages={doc_id: 'ru' for doc_id in ids},
    )


@pytest.mark.asyncio
async def test_compatibility_uses_original_metadata_and_no_semantic_score(monkeypatch):
    tenant_id, document_id = uuid4(), uuid4()
    analyze = AsyncMock(return_value=analysis_for([document_id]))
    indexed = AsyncMock(side_effect=AssertionError('Index must not be read'))
    monkeypatch.setattr(source_analysis, 'analyze_document_set', analyze)
    monkeypatch.setattr(source_analysis, 'document_chunk_totals', indexed)
    db = SimpleNamespace()
    result = await router.document_compatibility(
        DocumentCompatibilityRequest(documents=[document_id]), db=db,
        user=SimpleNamespace(tenant_id=tenant_id),
    )
    assert result.analysis_mode == 'direct_source'
    assert result.status == 'unverified' and result.score is None
    assert result.recommended_structure is not None
    indexed.assert_not_awaited()
    analyze.assert_awaited_once_with(db, tenant_id, [document_id], analysis_mode='direct_source')


@pytest.mark.asyncio
async def test_multiple_direct_sources_require_goal_without_claiming_mixed_topics(monkeypatch):
    tenant_id = uuid4()
    ids = [uuid4(), uuid4()]
    monkeypatch.setattr(source_analysis, 'analyze_document_set', AsyncMock(return_value=analysis_for(ids)))
    indexed = AsyncMock(side_effect=AssertionError('Index must not be read'))
    monkeypatch.setattr(source_analysis, 'document_chunk_totals', indexed)
    submit = AsyncMock()
    monkeypatch.setattr(router, 'submit_ai_job', submit)
    with pytest.raises(HTTPException) as failure:
        await router.generate_course(AIGenerateRequest(documents=ids), db=SimpleNamespace(), user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id))
    assert failure.value.status_code == 409
    assert failure.value.detail['code'] == 'source_combination_goal_required'
    assert failure.value.detail['analysis']['score'] is None
    submit.assert_not_awaited()
    indexed.assert_not_awaited()
