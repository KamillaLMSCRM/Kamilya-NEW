from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import pipeline
from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failed", "cancelled"])
async def test_direct_pipeline_forwards_trusted_tenant_to_semantic_writer(monkeypatch, outcome):
    tenant_id, user_id, doc_id = uuid4(), uuid4(), str(uuid4())
    monkeypatch.setattr(pipeline, '_update_job_db', AsyncMock())
    monkeypatch.setattr(pipeline, '_check_cancelled_async', AsyncMock())
    monkeypatch.setattr(pipeline, 'load_direct_source_corpus', AsyncMock(return_value=SimpleNamespace(
        total_chunks=1, documents=[SimpleNamespace(category='general')], tenant_id=str(tenant_id))))
    monkeypatch.setattr(pipeline.ResilientLLMClient, 'from_settings_async', AsyncMock(return_value=object()))
    checkpoints = SimpleNamespace(clear=AsyncMock(), aclose=AsyncMock())
    from unittest.mock import Mock
    checkpoint_factory = Mock(return_value=checkpoints)
    monkeypatch.setattr(pipeline, '_source_map_checkpoint_store', checkpoint_factory)
    monkeypatch.setattr(pipeline, 'run_direct_architect', AsyncMock(return_value=CourseStructure(
        title='Synthetic', modules=[Module(title='Module', lessons=[Lesson(title='Lesson', source_doc_ids=[doc_id])])])))
    writer = AsyncMock(return_value=CourseContent(title='Synthetic', modules=[ModuleContent(
        title='Module', lessons=[LessonContent(title='Lesson', content='Synthetic source material.')])]))
    monkeypatch.setattr(pipeline, 'write_direct_course', writer)
    monkeypatch.setattr(pipeline, 'ReviewerAgent', lambda **kwargs: SimpleNamespace(
        review_lesson=AsyncMock(return_value={'quality_score': 9, 'issues': []})))
    monkeypatch.setattr(pipeline, 'generate_course_assessment', AsyncMock(return_value=object()))
    save = AsyncMock()
    async def save_success(state, *_args):
        state.status = 'completed'
    save.side_effect = save_success
    monkeypatch.setattr(pipeline, '_save_generation_to_db', save)
    if outcome != 'success':
        import asyncio
        # Existing course avoids unrelated quota-refund DB work in a failed fixture.
        error = asyncio.CancelledError() if outcome == 'cancelled' else pipeline.DirectSourceError('synthetic_fault')
        pipeline.run_direct_architect.side_effect = error
    state = await pipeline.run_generation_pipeline(
        str(uuid4()), documents=[doc_id], tenant_id=tenant_id, user_id=user_id,
        course_id=str(uuid4()) if outcome == 'failed' else None,
        source_analysis={'analysis_mode': 'direct_source'})
    checkpoints.aclose.assert_awaited_once()
    assert pipeline.run_direct_architect.call_args.kwargs['checkpoint_store'] is checkpoints
    assert checkpoint_factory.call_args.args[1] == tenant_id
    if outcome == 'failed':
        checkpoints.clear.assert_not_awaited()
        assert state.status == 'failed'
        return
    checkpoints.clear.assert_awaited_once()
    if outcome == 'cancelled':
        assert state.status == 'cancelled'
        return
    assert state.errors == []
    assert writer.await_count == 1
    assert writer.call_args.kwargs['tenant_id'] == tenant_id
    save.assert_awaited_once_with(state, tenant_id, user_id)


def test_checkpoint_factory_namespaces_settings_and_job(monkeypatch):
    from unittest.mock import Mock
    factory = Mock()
    monkeypatch.setattr(pipeline, 'SourceMapCheckpointStore', factory)
    llm = SimpleNamespace(cache_fingerprint=lambda: 'a' * 64)
    tenant, job = uuid4(), str(uuid4())
    pipeline._source_map_checkpoint_store(llm, tenant, job, {'language': 'ru'})
    first = factory.call_args.args
    pipeline._source_map_checkpoint_store(llm, tenant, job, {'language': 'kk'})
    assert first[:2] == factory.call_args.args[:2] == (str(tenant), job)
    assert first[2] != factory.call_args.args[2]
    assert pipeline._source_map_checkpoint_store(object(), tenant, job, {}) is None
    assert pipeline._source_map_checkpoint_store(llm, None, job, {}) is None
