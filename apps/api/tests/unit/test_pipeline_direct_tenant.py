from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import pipeline
from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


@pytest.mark.asyncio
async def test_direct_pipeline_forwards_trusted_tenant_to_semantic_writer(monkeypatch):
    tenant_id, user_id, doc_id = uuid4(), uuid4(), str(uuid4())
    monkeypatch.setattr(pipeline, '_update_job_db', AsyncMock())
    monkeypatch.setattr(pipeline, '_check_cancelled_async', AsyncMock())
    monkeypatch.setattr(pipeline, 'load_direct_source_corpus', AsyncMock(return_value=SimpleNamespace(
        total_chunks=1, documents=[SimpleNamespace(category='general')], tenant_id=str(tenant_id))))
    monkeypatch.setattr(pipeline.ResilientLLMClient, 'from_settings_async', AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, 'run_direct_architect', AsyncMock(return_value=CourseStructure(
        title='Synthetic', modules=[Module(title='Module', lessons=[Lesson(title='Lesson', source_doc_ids=[doc_id])])])))
    writer = AsyncMock(return_value=CourseContent(title='Synthetic', modules=[ModuleContent(
        title='Module', lessons=[LessonContent(title='Lesson', content='Synthetic source material.')])]))
    monkeypatch.setattr(pipeline, 'write_direct_course', writer)
    monkeypatch.setattr(pipeline, 'ReviewerAgent', lambda **kwargs: SimpleNamespace(
        review_lesson=AsyncMock(return_value={'quality_score': 9, 'issues': []})))
    monkeypatch.setattr(pipeline, 'generate_course_assessment', AsyncMock(return_value=object()))
    save = AsyncMock()
    monkeypatch.setattr(pipeline, '_save_generation_to_db', save)
    state = await pipeline.run_generation_pipeline(
        str(uuid4()), documents=[doc_id], tenant_id=tenant_id, user_id=user_id,
        source_analysis={'analysis_mode': 'direct_source'})
    assert state.errors == []
    assert writer.await_count == 1
    assert writer.call_args.kwargs['tenant_id'] == tenant_id
    save.assert_awaited_once_with(state, tenant_id, user_id)
