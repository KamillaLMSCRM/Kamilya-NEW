from __future__ import annotations

import pytest

from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.response_contracts import response_contract


@pytest.mark.asyncio
async def test_structured_auxiliary_engine_wires_exact_formats_and_legacy_default() -> None:
    typed_formats = []

    async def typed(messages, response_format):
        typed_formats.append(response_format)
        return {}

    pipeline = V3GenerationPipeline(typed, structured_auxiliary_output=True)
    await pipeline.repair_prose([{"id": "v1", "old": "old"}], ["source"])
    assert [response_contract(value) for value in typed_formats] == ["aux:prose_repair"]

    legacy_formats = []

    async def legacy(_messages, response_format):
        legacy_formats.append(response_format)
        return {}

    legacy_pipeline = V3GenerationPipeline(legacy)
    await legacy_pipeline.repair_prose([{"id": "v1", "old": "old"}], ["source"])
    assert legacy_formats == [{"type": "json_object"}]
