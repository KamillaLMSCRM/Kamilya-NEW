"""Static fail-closed contract for active document revisions in all retrievers."""

from pathlib import Path


INGESTION = Path(__file__).parents[2] / "app" / "modules" / "ai" / "ingestion.py"


def test_semantic_fts_and_legacy_chunk_reads_require_active_document_revision() -> None:
    source = INGESTION.read_text(encoding="utf-8")
    predicate = "embedding_source_revision = 'document:' || ("
    assert source.count(predicate) == 3
    assert source.count("active_document.content_sha256") == 3
    assert source.count("active_document.id = document_embeddings.doc_id") == 3
    assert source.count("active_document.tenant_id = document_embeddings.tenant_id") == 3
