from __future__ import annotations

import pytest

from app.modules.ai.ingestion import _local_convert


@pytest.mark.asyncio
async def test_binary_document_is_never_indexed_as_placeholder(tmp_path) -> None:
    source = tmp_path / "policy.pdf"
    source.write_bytes(b"%PDF-1.7")

    with pytest.raises(RuntimeError, match="conversion is unavailable"):
        await _local_convert(str(source))


@pytest.mark.asyncio
async def test_plain_text_document_keeps_local_fallback(tmp_path) -> None:
    source = tmp_path / "policy.md"
    source.write_text("# Approved policy", encoding="utf-8")

    converted = await _local_convert(str(source))

    assert converted["markdown"] == "# Approved policy"
