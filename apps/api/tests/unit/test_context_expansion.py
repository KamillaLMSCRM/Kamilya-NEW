from types import SimpleNamespace

import pytest

from app.modules.ai.context_expansion import expand_context_windows

REVISION = "document:" + "d" * 64


def _metadata(
    chunk_id,
    index,
    *,
    doc_id="doc-1",
    tenant_id="tenant-1",
    revision=REVISION,
):
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "tenant_id": tenant_id,
        "doc_name": "source.pdf",
        "headings": '["Раздел"]',
        "embedding_provider": "qwen-self-hosted",
        "embedding_model": "Qwen3-Embedding-8B",
        "embedding_revision": "Qwen3-Embedding-8B",
        "embedding_native_dimensions": 2,
        "embedding_storage_dimensions": 2,
        "embedding_content_sha256": "a" * 64,
        "embedding_source_revision": revision,
        "embedding_indexed_at": "2026-08-23T00:00:00+00:00",
        "chunk_index": index,
    }


class _Store:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def get_context_window(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def _hit(**overrides):
    values = {
        "chunk_id": "center",
        "doc_id": "doc-1",
        "tenant_id": "tenant-1",
        "source_revision": REVISION,
        "chunk_index": 4,
        "embedding_provider": "qwen-self-hosted",
        "embedding_model": "Qwen3-Embedding-8B",
        "embedding_revision": "Qwen3-Embedding-8B",
        "embedding_native_dimensions": 2,
        "embedding_storage_dimensions": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_expansion_enforces_exact_anchor_scope_and_document_order() -> None:
    store = _Store([
        ("before", _metadata("before", 3)),
        ("center", _metadata("center", 4)),
        ("after", _metadata("after", 5)),
        ("foreign", _metadata("foreign", 4, doc_id="doc-2")),
        ("foreign-tenant", _metadata("foreign-tenant", 4, tenant_id="tenant-2")),
        ("old", _metadata("old", 4, revision="document:" + "e" * 64)),
        ("far", _metadata("far", 8)),
    ])

    windows = await expand_context_windows(
        store,
        [_hit()],
        tenant_id="tenant-1",
        radius=1,
    )

    assert store.calls == [{
        "doc_id": "doc-1",
        "source_revision": REVISION,
        "chunk_index": 4,
        "radius": 1,
        "tenant_id": "tenant-1",
    }]
    assert [chunk.chunk_id for chunk in windows[0].chunks] == ["before", "center", "after"]
    assert [chunk.is_anchor for chunk in windows[0].chunks] == [False, True, False]
    assert {chunk.tenant_id for chunk in windows[0].chunks} == {"tenant-1"}
    assert windows[0].tenant_id == "tenant-1"


@pytest.mark.asyncio
async def test_expansion_budget_always_keeps_anchor_and_prefers_nearest() -> None:
    store = _Store([
        ("x" * 20, _metadata("before", 3)),
        ("anchor", _metadata("center", 4)),
        ("y" * 20, _metadata("after", 5)),
    ])

    windows = await expand_context_windows(
        store,
        [_hit()],
        tenant_id="tenant-1",
        radius=1,
        max_chars_per_window=6,
    )

    assert [chunk.chunk_id for chunk in windows[0].chunks] == ["center"]


@pytest.mark.asyncio
async def test_expansion_rejects_missing_anchor_or_invalid_input() -> None:
    with pytest.raises(ValueError, match="context_anchor_not_found"):
        await expand_context_windows(
            _Store([("neighbor", _metadata("neighbor", 3))]),
            [_hit()],
            tenant_id="tenant-1",
        )

    store = _Store([])
    with pytest.raises(ValueError, match="incomplete_context_anchor"):
        await expand_context_windows(
            store,
            [_hit(source_revision="")],
            tenant_id="tenant-1",
        )
    with pytest.raises(ValueError, match="tenant_id_required"):
        await expand_context_windows(store, [_hit()], tenant_id="")
    with pytest.raises(ValueError, match="invalid_context_radius"):
        await expand_context_windows(store, [_hit()], tenant_id="tenant-1", radius=4)
    with pytest.raises(ValueError, match="context_anchor_tenant_mismatch"):
        await expand_context_windows(
            store,
            [_hit(tenant_id="tenant-2")],
            tenant_id="tenant-1",
        )
    assert store.calls == []


@pytest.mark.asyncio
async def test_expansion_rejects_mismatched_or_invalid_embedding_space() -> None:
    wrong_provider = _metadata("wrong-provider", 3)
    wrong_provider["embedding_provider"] = "other-provider"
    invalid_dimensions = _metadata("invalid-dimensions", 5)
    invalid_dimensions["embedding_native_dimensions"] = 4
    invalid_dimensions["embedding_storage_dimensions"] = 2
    store = _Store([
        ("wrong", wrong_provider),
        ("anchor", _metadata("center", 4)),
        ("invalid", invalid_dimensions),
    ])

    windows = await expand_context_windows(
        store,
        [_hit()],
        tenant_id="tenant-1",
        radius=1,
    )

    assert [chunk.chunk_id for chunk in windows[0].chunks] == ["center"]

    with pytest.raises(ValueError, match="incomplete_context_anchor"):
        await expand_context_windows(
            _Store([]),
            [_hit(embedding_native_dimensions=0)],
            tenant_id="tenant-1",
        )


@pytest.mark.asyncio
async def test_expansion_deduplicates_overlapping_context_windows() -> None:
    store = _Store([
        ("first", _metadata("first", 3)),
        ("center", _metadata("center", 4)),
        ("second", _metadata("second", 5)),
    ])
    windows = await expand_context_windows(
        store,
        [_hit(), _hit(chunk_id="second", chunk_index=5)],
        tenant_id="tenant-1",
        radius=1,
    )

    assert [chunk.chunk_id for chunk in windows[0].chunks] == ["first", "center"]
    assert [chunk.chunk_id for chunk in windows[1].chunks] == ["second"]
    identities = [
        (chunk.tenant_id, chunk.doc_id, chunk.source_revision, chunk.chunk_id)
        for window in windows
        for chunk in window.chunks
    ]
    assert len(identities) == len(set(identities))
