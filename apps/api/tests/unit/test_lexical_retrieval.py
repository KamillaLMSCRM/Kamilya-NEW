import pytest

from app.modules.ai.lexical_retrieval import retrieve_lexical_hits


class _Store:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    async def get_all_chunks(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def _row(chunk_id, doc_id, text, heading="", doc_name="source.pdf"):
    return (
        text,
        {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "doc_name": doc_name,
            "headings": [heading] if heading else [],
        },
    )


@pytest.mark.asyncio
async def test_lexical_retrieval_enforces_exact_tenant_and_document_scope() -> None:
    store = _Store(
        [
            _row("inside", "doc-1", "Порядок предоставления микрокредита"),
            _row("foreign", "doc-9", "Порядок предоставления микрокредита"),
            ("Порядок предоставления", {"doc_id": "doc-1"}),
        ]
    )

    hits = await retrieve_lexical_hits(
        store,
        ["предоставление микрокредита"],
        tenant_id="tenant-1",
        doc_ids=["doc-1", "doc-1"],
    )

    assert store.calls == [{"doc_ids": ["doc-1"], "tenant_id": "tenant-1"}]
    assert [(hit.chunk_id, hit.doc_id) for hit in hits] == [("inside", "doc-1")]
    assert hits[0].matched_terms == ("предоставлен", "микрокредит")


@pytest.mark.asyncio
async def test_preferred_heading_boost_beats_equal_body_match() -> None:
    store = _Store(
        [
            _row("other", "doc-1", "Общие положения правил", "ПОРЯДОК ВЫПЛАТ"),
            _row("preferred", "doc-1", "Общие положения правил", "1. ОБЩИЕ ПОЛОЖЕНИЯ"),
        ]
    )

    hits = await retrieve_lexical_hits(
        store,
        ["общие положения"],
        tenant_id="tenant-1",
        doc_ids=["doc-1"],
        preferred_headings=["ОБЩИЕ ПОЛОЖЕНИЯ"],
    )

    assert [hit.chunk_id for hit in hits] == ["preferred"]
    assert hits[0].preferred_heading_match is True
    assert hits[0].score > 0


@pytest.mark.asyncio
async def test_bm25_length_normalization_avoids_long_text_bias_and_ties_are_stable() -> None:
    store = _Store(
        [
            _row("long", "doc-1", "эвакуация " + "посторонний " * 100),
            _row("short-b", "doc-2", "эвакуация порядок"),
            _row("short-a", "doc-2", "эвакуация порядок"),
        ]
    )

    hits = await retrieve_lexical_hits(
        store,
        ["эвакуация"],
        tenant_id="tenant-1",
        doc_ids=["doc-2", "doc-1"],
    )

    assert [hit.chunk_id for hit in hits] == ["short-a", "short-b", "long"]
    assert hits[0].score == hits[1].score
    assert hits[1].score > hits[2].score


@pytest.mark.asyncio
async def test_invalid_scope_fails_before_store_access() -> None:
    store = _Store()

    for kwargs, error in (
        ({"tenant_id": "", "doc_ids": ["doc-1"]}, "tenant_id_required"),
        ({"tenant_id": "tenant-1", "doc_ids": []}, "selected_doc_ids_required"),
        ({"tenant_id": "tenant-1", "doc_ids": ["doc-1"], "limit": 0}, "invalid_lexical_limit"),
    ):
        with pytest.raises(ValueError, match=error):
            await retrieve_lexical_hits(store, ["порядок"], **kwargs)

    assert store.calls == []


@pytest.mark.asyncio
async def test_limit_and_malformed_headings_are_safe_and_deterministic() -> None:
    rows = [
        ("пожарная безопасность", {"chunk_id": "c", "doc_id": "doc-1", "headings": "{"}),
        _row("b", "doc-1", "пожарная безопасность"),
        _row("a", "doc-1", "пожарная безопасность"),
    ]
    store = _Store(rows)

    hits = await retrieve_lexical_hits(
        store,
        ["пожарная безопасность"],
        tenant_id="tenant-1",
        doc_ids=["doc-1"],
        limit=2,
    )

    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert all(hit.headings == () for hit in hits)


@pytest.mark.asyncio
async def test_russian_inflections_and_kazakh_letters_are_searchable() -> None:
    store = _Store(
        [
            _row("ru", "doc-1", "Правила эвакуации утверждены"),
            _row("kk", "doc-1", "Қауіпсіздік талаптары бекітілген"),
        ]
    )

    russian = await retrieve_lexical_hits(
        store,
        ["правило эвакуация"],
        tenant_id="tenant-1",
        doc_ids=["doc-1"],
    )
    kazakh = await retrieve_lexical_hits(
        store,
        ["қауіпсіздік талап"],
        tenant_id="tenant-1",
        doc_ids=["doc-1"],
    )

    assert russian[0].chunk_id == "ru"
    assert set(russian[0].matched_terms) == {"правил", "эвакуац"}
    assert kazakh[0].chunk_id == "kk"
    assert "қауіпсіздік" in kazakh[0].matched_terms


@pytest.mark.asyncio
async def test_exact_heading_and_document_metadata_signals_are_explicit() -> None:
    store = _Store(
        [
            _row("exact", "doc-1", "путь эвакуации указан", "Другое"),
            _row("heading", "doc-2", "общий текст", "Путь эвакуации"),
            _row(
                "metadata",
                "doc-3",
                "общий текст",
                doc_name="путь-эвакуации.pdf",
            ),
        ]
    )

    hits = await retrieve_lexical_hits(
        store,
        ["путь эвакуации"],
        tenant_id="tenant-1",
        doc_ids=["doc-1", "doc-2", "doc-3"],
    )

    by_id = {hit.chunk_id: hit for hit in hits}
    assert by_id["exact"].exact_phrase_match is True
    assert by_id["heading"].heading_term_match is True
    assert by_id["metadata"].metadata_term_match is True
