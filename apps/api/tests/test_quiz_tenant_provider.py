"""Course-quiz requests must resolve the caller's tenant provider."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.quizzes import ai


@pytest.mark.asyncio
async def test_quiz_factory_receives_trusted_tenant(monkeypatch):
    tenant_id = uuid4()
    client = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(
        content='{"title":"Synthetic quiz","questions":[{"text":"Which rule?","type":"MCQ","choices":[{"text":"Two people","is_correct":true},{"text":"One person","is_correct":false}]}]}',
        response_metadata={},
    )))
    factory = AsyncMock(return_value=client)
    monkeypatch.setattr(ai.ResilientLLMClient, 'from_settings_async', factory)
    await ai.generate_quiz_draft(
        tenant_id=tenant_id, lesson_title='Synthetic', lesson_content='Carry with two people.',
        num_questions=1, difficulty='medium', language='en', guidance=None,
    )
    factory.assert_awaited_once_with(tenant_id=tenant_id, temperature=0.4, max_tokens=4096)
