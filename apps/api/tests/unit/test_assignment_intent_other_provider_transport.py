"""Bounded provider adaptation preserves non-DeepSeek JSON schema requests."""

import pytest

from app.modules.ai import llm_client as llm


@pytest.mark.asyncio
async def test_bounded_non_deepseek_schema_preserves_messages_and_schema(monkeypatch):
    cfg = llm.LLMProviderConfig("other", "https://other.invalid", "synthetic", "first", timeout=120,
                                max_retries=2)
    original = llm.ResilientLLMClient([cfg], temperature=0.25, max_tokens=1200)
    messages = [{"role": "user", "content": "synthetic"}]
    response_format = {"type": "json_schema", "json_schema": {"name": "example"}}
    seen = []

    async def request(self, payload):
        assert self.config == llm.replace(cfg, max_retries=0)
        seen.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(llm.LLMClient, "_request", request)
    await original.ainvoke(messages, config={"max_tokens": 1000},
                           response_format=response_format, provider_deadline_seconds=0.1)
    assert seen == [{"model": "first", "messages": [{"role": "user", "content": "synthetic"}],
                     "temperature": 0.25, "max_tokens": 1000, "response_format": response_format}]
    assert messages == [{"role": "user", "content": "synthetic"}]
    assert response_format == {"type": "json_schema", "json_schema": {"name": "example"}}
    assert original._clients[0].config is cfg and original._clients[0].max_retries == 2
