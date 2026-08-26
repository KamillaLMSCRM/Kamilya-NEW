"""Document ingestion — parsing, chunking, embedding, vector store."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.modules.ai.embedding_provenance import (
    VerifiedEmbeddingProvenance,
    serialize_embedding_provenance,
)
from app.modules.documents.archive_preflight import preflight_ooxml

if TYPE_CHECKING:
    from app.modules.ai.llm_client import EmbeddingBatchResult, ResilientEmbeddingsClient

logger = logging.getLogger(__name__)

DOCLING_URL = os.getenv("DOCLING_URL", "")
DOCLING_API_KEY = os.getenv("DOCLING_API_KEY", "")
DOCLING_TIMEOUT_SECONDS = float(os.getenv("DOCLING_TIMEOUT_SECONDS", "900"))


class DocumentIndexingTerminalError(RuntimeError):
    """Stable non-retryable failure for unusable converted document content."""

    error_code = "document_content_unavailable"


class DocumentOCRRequiredError(DocumentIndexingTerminalError):
    """A scanned PDF has no text layer and the OCR route was unavailable."""

    error_code = "ocr_required"


class DocumentNoContentError(DocumentIndexingTerminalError):
    """Conversion completed but produced no indexable content."""

    error_code = "no_chunks"


class DocumentConverter:
    """Convert documents to markdown — remote Docling on VPS, local fallback."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or DOCLING_URL).rstrip("/")

    async def convert(self, file_path: str) -> dict[str, Any]:
        """Convert document to markdown + metadata."""
        filename = os.path.basename(file_path)
        ext = Path(file_path).suffix.lower()

        # Re-check Office archives at the conversion boundary as well as at
        # upload time. Existing stored documents and internal callers can
        # otherwise bypass the public upload preflight and reach Docling or a
        # local OOXML parser with a decompression bomb or unsafe member path.
        if ext in (".docx", ".xlsx"):
            with open(file_path, "rb") as source:
                preflight_ooxml(source, ext)

        # Plain text formats are already markdown-compatible. Sending them
        # through remote Docling adds minutes of latency and can make the
        # browser abort otherwise tiny uploads.
        if ext in (".txt", ".md", ".csv"):
            return await _local_convert(file_path)

        # Try remote Docling first, but only when operators configured it.
        # A historical public-IP default made every Office/PDF upload wait for
        # a dead external service before the local fallback could run.
        try:
            if not self.base_url:
                return await _local_convert(file_path)
            import httpx
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                headers = (
                    {"X-Docling-Key": DOCLING_API_KEY}
                    if DOCLING_API_KEY
                    else None
                )
                async with httpx.AsyncClient(timeout=DOCLING_TIMEOUT_SECONDS) as client:
                    resp = await client.post(
                        f"{self.base_url}/convert",
                        files=files,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return {
                        "markdown": data["markdown"],
                        "metadata": {
                            "filename": filename,
                            "size": os.path.getsize(file_path),
                            "pages": data.get("pages", 0),
                            "tables": data.get("tables", 0),
                            "engine": data.get("engine", "docling"),
                            "engine_version": data.get("engine_version"),
                            "fallback_used": bool(data.get("fallback_used", False)),
                            "warnings": list(data.get("warnings") or []),
                            "profile": data.get("profile"),
                            "routing_reason": data.get("routing_reason"),
                        },
                    }
        except Exception as e:
            logger.warning("Remote Docling conversion failed error_type=%s", type(e).__name__)

        # Local fallback
        return await _local_convert(file_path)


async def _local_convert(file_path: str) -> dict[str, Any]:
    """Convert common source formats without an external document service."""
    ext = Path(file_path).suffix.lower()
    engine: str
    pages = 0
    tables = 0
    if ext in (".txt", ".md", ".csv"):
        content = Path(file_path).read_text(encoding="utf-8")
        engine = "plain_text"
    elif ext == ".docx":
        from docx import Document
        from docx.table import Table

        try:
            document = Document(file_path)
        except Exception as exc:
            raise RuntimeError("Document conversion is unavailable for .docx") from exc
        blocks: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                rows = [
                    [cell.text.replace("\n", " ").strip() for cell in row.cells]
                    for row in block.rows
                ]
                if not rows:
                    continue
                width = max(len(row) for row in rows)
                normalized = [row + [""] * (width - len(row)) for row in rows]
                blocks.append("| " + " | ".join(normalized[0]) + " |")
                blocks.append("| " + " | ".join(["---"] * width) + " |")
                blocks.extend(
                    "| " + " | ".join(row) + " |" for row in normalized[1:]
                )
                tables += 1
                continue

            text_value = block.text.strip()
            if not text_value:
                continue
            style_name = (block.style.name or "") if block.style else ""
            if style_name.lower().startswith("heading"):
                suffix = style_name.split()[-1]
                level = int(suffix) if suffix.isdigit() else 1
                blocks.append(f"{'#' * min(max(level, 1), 6)} {text_value}")
            else:
                blocks.append(text_value)
        content = "\n\n".join(blocks)
        engine = "python-docx"
    elif ext == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(file_path)
        except Exception as exc:
            raise RuntimeError("Document conversion is unavailable for .pdf") from exc
        pages = len(reader.pages)
        content = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        engine = "pypdf"
    else:
        raise RuntimeError(
            f"Document conversion is unavailable for {ext or 'this file type'}"
        )
    return {
        "markdown": content,
        "metadata": {
            "filename": os.path.basename(file_path),
            "size": os.path.getsize(file_path),
            "pages": pages,
            "tables": tables,
            "engine": engine,
            "engine_version": None,
            "fallback_used": ext not in (".txt", ".md", ".csv"),
            "warnings": [],
        },
    }



class DocumentChunker:
    """Split documents into chunks for embedding."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_markdown(self, markdown: str, doc_id: str, doc_name: str) -> list[dict[str, Any]]:
        """Split markdown into chunks with metadata."""
        chunks = []
        paragraphs = markdown.split("\n\n")

        current_chunk = ""
        current_headings: list[str] = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Track headings
            if para.startswith("#"):
                level = len(para.split(" ")[0])
                title = para.lstrip("#").strip()
                if level <= len(current_headings):
                    current_headings = current_headings[: level - 1]
                current_headings.append(title)

            # Check if adding this paragraph exceeds chunk size
            if len(current_chunk) + len(para) + 2 > self.chunk_size and current_chunk:
                chunks.append({
                    "text": current_chunk.strip(),
                    "metadata": {
                        "doc_id": doc_id,
                        "doc_name": doc_name,
                        "headings": json.dumps(current_headings, ensure_ascii=False),
                    },
                })
                # Keep overlap
                overlap_text = current_chunk[-self.chunk_overlap:] if self.chunk_overlap else ""
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk += "\n\n" + para if current_chunk else para

        # Final chunk
        if current_chunk.strip():
            chunks.append({
                "text": current_chunk.strip(),
                "metadata": {
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "headings": json.dumps(current_headings, ensure_ascii=False),
                },
            })

        return chunks


class VectorStore:
    """Supabase pgvector-backed vector store."""

    def __init__(self, persist_dir: str = "./chroma_data"):
        self.persist_dir = persist_dir

    @staticmethod
    def _active_index_visibility_clause() -> str:
        """Expose legacy rows or the exact atomically selected index revision."""
        return (
            "((document_embeddings.embedding_index_revision_id IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM embedding_active_revisions AS active_index "
            "WHERE active_index.tenant_id = document_embeddings.tenant_id "
            "AND active_index.document_id = document_embeddings.doc_id"
            ")) OR document_embeddings.embedding_index_revision_id = ("
            "SELECT active_index.active_revision_id "
            "FROM embedding_active_revisions AS active_index "
            "WHERE active_index.tenant_id = document_embeddings.tenant_id "
            "AND active_index.document_id = document_embeddings.doc_id"
            "))"
        )

    async def _set_tenant_context(self, session: Any, tenant_id: str | None) -> None:
        if tenant_id:
            from sqlalchemy import text
            await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})

    async def add_chunks(
        self,
        chunks: list[dict[str, Any]],
        embedding_batch: Any,
        tenant_id: str | None = None,
        index_revision_id: str | None = None,
        reindex_run_id: str | None = None,
    ) -> int:
        """Add chunks with embeddings to Supabase.

        The store only accepts a validated EmbeddingBatchResult. This
        fails closed before any database write if the embedding batch
        does not match the chunk count or the configured pgvector
        schema.
        """
        from sqlalchemy import text

        from app.core.config import get_settings
        from app.core.db import async_session_factory
        from app.modules.ai.llm_client import EmbeddingBatchResult

        if not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(embedding_batch, EmbeddingBatchResult):
            raise TypeError("embedding_batch_required")
        if (index_revision_id is None) != (reindex_run_id is None):
            raise ValueError("embedding_reindex_binding_required")
        if index_revision_id is not None:
            import re

            if not isinstance(index_revision_id, str) or not index_revision_id.strip():
                raise ValueError("invalid_embedding_index_revision_id")
            if not isinstance(reindex_run_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", reindex_run_id
            ):
                raise ValueError("invalid_embedding_reindex_run_id")

        expected_dimensions = get_settings().EMBEDDING_DIMENSIONS
        if len(chunks) != len(embedding_batch.vectors):
            raise ValueError("embedding_batch_chunk_count_mismatch")
        if embedding_batch.storage_dimensions != expected_dimensions:
            raise ValueError("embedding_batch_storage_dimension_mismatch")

        source_revisions: set[str] = set()
        chunk_indices: set[int] = set()
        document_ids: set[str] = set()
        for chunk in chunks:
            metadata = chunk.get("metadata", {})
            source_revision = metadata.get("source_revision")
            chunk_index = metadata.get("chunk_index")
            doc_id = metadata.get("doc_id")
            if not isinstance(source_revision, str) or not source_revision:
                raise ValueError("embedding_source_revision_required")
            if type(chunk_index) is not int or chunk_index < 0:
                raise ValueError("invalid_chunk_index")
            if not isinstance(doc_id, str) or not doc_id:
                raise ValueError("document_id_required")
            source_revisions.add(source_revision)
            chunk_indices.add(chunk_index)
            document_ids.add(doc_id)
        if len(source_revisions) != 1 or len(document_ids) != 1:
            raise ValueError("mixed_document_embedding_batch")
        if len(chunk_indices) != len(chunks):
            raise ValueError("duplicate_chunk_index")

        indexed_at = datetime.now(UTC)

        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            inserted = 0
            last_doc_id = ""
            rows: list[dict] = []
            for chunk, vector in zip(chunks, embedding_batch.vectors, strict=True):
                meta = chunk.get("metadata", {})
                last_doc_id = meta.get("doc_id", "")
                chunk_text = chunk["text"]
                chunk_index = meta["chunk_index"]
                source_revision = meta["source_revision"]
                chunk_identity = (
                    f"{tenant_id}|{last_doc_id}|{source_revision}|{chunk_index}|{chunk_text}"
                )
                if index_revision_id is not None:
                    chunk_identity += f"|{index_revision_id}|{reindex_run_id}"
                chunk_id = hashlib.sha256(chunk_identity.encode("utf-8")).hexdigest()
                provenance = serialize_embedding_provenance(
                    VerifiedEmbeddingProvenance(
                        space=embedding_batch.space,
                        native_dimensions=embedding_batch.native_dimensions,
                        storage_dimensions=embedding_batch.storage_dimensions,
                        content_sha256=hashlib.sha256(
                            chunk_text.encode("utf-8")
                        ).hexdigest(),
                        source_revision=source_revision,
                        indexed_at=indexed_at,
                    )
                )
                rows.append({
                    "id": chunk_id,
                    "tenant_id": tenant_id,
                    "doc_id": last_doc_id,
                    "text": chunk_text,
                    "headings": meta.get("headings", ""),
                    "doc_name": meta.get("doc_name", ""),
                    "embedding": str(list(vector)),
                    "chunk_index": chunk_index,
                    "embedding_index_revision_id": index_revision_id,
                    "embedding_reindex_run_id": reindex_run_id,
                    **provenance,
                })
                inserted += 1
            insert_stmt = text(
                """INSERT INTO document_embeddings (
                       id, tenant_id, doc_id, text, headings, doc_name, embedding,
                       embedding_provenance_state, embedding_provider, embedding_model,
                       embedding_revision, embedding_native_dimensions, embedding_storage_dimensions,
                       embedding_content_sha256, embedding_source_revision, embedding_indexed_at,
                       chunk_index, embedding_index_revision_id, embedding_reindex_run_id
                   )
                   VALUES (
                       :id, :tenant_id, :doc_id, :text, :headings, :doc_name, :embedding,
                       :embedding_provenance_state, :embedding_provider, :embedding_model,
                       :embedding_revision, :embedding_native_dimensions, :embedding_storage_dimensions,
                       :embedding_content_sha256, :embedding_source_revision, :embedding_indexed_at,
                       :chunk_index, :embedding_index_revision_id, :embedding_reindex_run_id
                   )
                   ON CONFLICT (id) DO UPDATE SET
                       tenant_id = EXCLUDED.tenant_id,
                       doc_id = EXCLUDED.doc_id,
                       text = EXCLUDED.text,
                       headings = EXCLUDED.headings,
                       doc_name = EXCLUDED.doc_name,
                       embedding = EXCLUDED.embedding,
                       embedding_provenance_state = EXCLUDED.embedding_provenance_state,
                       embedding_provider = EXCLUDED.embedding_provider,
                       embedding_model = EXCLUDED.embedding_model,
                       embedding_revision = EXCLUDED.embedding_revision,
                       embedding_native_dimensions = EXCLUDED.embedding_native_dimensions,
                       embedding_storage_dimensions = EXCLUDED.embedding_storage_dimensions,
                       embedding_content_sha256 = EXCLUDED.embedding_content_sha256,
                       embedding_source_revision = EXCLUDED.embedding_source_revision,
                       embedding_indexed_at = EXCLUDED.embedding_indexed_at,
                       chunk_index = EXCLUDED.chunk_index,
                       embedding_index_revision_id = EXCLUDED.embedding_index_revision_id,
                       embedding_reindex_run_id = EXCLUDED.embedding_reindex_run_id
                   WHERE document_embeddings.tenant_id = EXCLUDED.tenant_id"""
            )
            for start in range(0, len(rows), 100):
                await session.execute(insert_stmt, rows[start:start + 100])
            # IMPORTANT: explicit flush before the SELECT below. Without it,
            # SQLAlchemy's text() SELECT inside the same session may not see
            # the freshly-INSERTed rows in asyncpg — the unit-of-work
            # hasn't pushed to the connection yet, and session.execute()
            # inside the same transaction can return 0 rows even when the
            # COMMIT (called below) eventually writes them. Reproduced on
            # 2026-06-26: ingested 25 chunks, session commit reported OK,
            # post-commit SELECT in the SAME session returned 0 — because
            # the SELECT ran before the flush actually pushed to pgwire.
            #
            # NOTE: under PgBouncer transaction pooling, flush() before
            # commit() can race with the connection handoff. If we see
            # 'count_in_session=0' here despite successful INSERTs, the
            # workaround is to commit first and trust the diagnostic
            # SELECT on a fresh connection (we add one below).
            await session.flush()
            await session.commit()
            # Verify exact IDs on a fresh transaction/connection. RLS remains
            # active through the tenant context, so a cross-tenant conflict or
            # incomplete write cannot be mistaken for success.
            from app.core.db import async_session_factory as _fresh_factory
            async with _fresh_factory() as fresh:
                await self._set_tenant_context(fresh, tenant_id)
                verification_sql = (
                    "SELECT COUNT(*) FROM document_embeddings "
                    "WHERE id = ANY(CAST(:ids AS text[])) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND doc_id = CAST(:doc_id AS text) "
                    "AND embedding_source_revision = :source_revision "
                    "AND embedding_provenance_state = 'verified'"
                )
                verification_params: dict[str, Any] = {
                    "ids": [row["id"] for row in rows],
                    "tenant_id": tenant_id,
                    "doc_id": last_doc_id,
                    "source_revision": next(iter(source_revisions)),
                }
                if index_revision_id is not None:
                    verification_sql += (
                        " AND embedding_index_revision_id = :index_revision_id"
                        " AND embedding_reindex_run_id = :reindex_run_id"
                    )
                    verification_params.update(
                        {
                            "index_revision_id": index_revision_id,
                            "reindex_run_id": reindex_run_id,
                        }
                    )
                cnt2 = await fresh.execute(
                    text(verification_sql),
                    verification_params,
                )
                count_in_fresh = cnt2.scalar()
            if count_in_fresh != len(rows):
                logger.error(
                    "add_chunks verification failed: expected=%d verified=%d",
                    len(rows),
                    count_in_fresh,
                )
                raise RuntimeError("embedding_write_verification_failed")
            print(
                f"[INGEST] add_chunks post-commit: inserted_attempted={inserted} "
                f"dropped=0 verified_in_fresh={count_in_fresh}",
                flush=True,
            )

            return 0

    async def query(
        self,
        query_embedding_batch,
        n_results: int = 10,
        where: dict | None = None,
        include: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """Query only embeddings from the exact verified semantic space."""
        from sqlalchemy import text

        from app.core.config import get_settings
        from app.core.db import async_session_factory
        from app.modules.ai.llm_client import EmbeddingBatchResult

        if not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(query_embedding_batch, EmbeddingBatchResult):
            raise TypeError("embedding_batch_required")
        if len(query_embedding_batch.vectors) != 1:
            raise ValueError("single_query_embedding_required")
        if query_embedding_batch.storage_dimensions != get_settings().EMBEDDING_DIMENSIONS:
            raise ValueError("embedding_batch_storage_dimension_mismatch")

        emb = query_embedding_batch.vectors[0]

        clauses = [
            "embedding_provenance_state = 'verified'",
            self._active_index_visibility_clause(),
            "embedding_source_revision = 'document:' || ("
            "SELECT active_document.content_sha256 FROM documents AS active_document "
            "WHERE active_document.id::text = document_embeddings.doc_id "
            "AND active_document.tenant_id = document_embeddings.tenant_id"
            ")",
            "embedding_provider = :embedding_provider",
            "embedding_model = :embedding_model",
            "embedding_revision = :embedding_revision",
            "embedding_native_dimensions = :embedding_native_dimensions",
            "embedding_storage_dimensions = :embedding_storage_dimensions",
        ]
        params: dict = {
            "n": n_results,
            "embedding_provider": query_embedding_batch.space.provider,
            "embedding_model": query_embedding_batch.space.model,
            "embedding_revision": query_embedding_batch.space.revision,
            "embedding_native_dimensions": query_embedding_batch.native_dimensions,
            "embedding_storage_dimensions": query_embedding_batch.storage_dimensions,
        }
        if where:
            doc_id = where.get("doc_id")
            if doc_id:
                if isinstance(doc_id, dict) and "$in" in doc_id:
                    ids = doc_id["$in"]
                    if not ids:
                        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
                    placeholders = ", ".join(f":doc_id_{i}" for i in range(len(ids)))
                    clauses.append(f"doc_id IN ({placeholders})")
                    for i, did in enumerate(ids):
                        params[f"doc_id_{i}"] = did
                else:
                    clauses.append("doc_id = :doc_id")
                    params["doc_id"] = doc_id

        # pgvector accepts bracketed vector input. Embedding providers and
        # synthetic gates may return either lists or tuples, so normalize both.
        emb_str = str(list(emb))
        # NOTE: Use CAST(:emb AS vector) instead of ':emb'::vector or :emb::vector.
        # - ':emb'::vector (f-string interpolation) works but looks like SQL injection
        #   to security scanners, and a previous audit (a1ea9c9) flagged it.
        # - :emb::vector (bind param with cast) raises "syntax error at or near ':'"
        #   because PostgreSQL parses :emb: as a placeholder + 'vector' as literal.
        # CAST(:emb AS vector) is the standard SQL form that works with bind params
        # and is also safe-looking for auditors. emb_str is a list of floats from
        # the embedding model, not user input, so the bind value is well-typed.
        sql = text(f"""
            SELECT id, text, doc_id, tenant_id, doc_name, headings,
                   embedding_provider, embedding_model, embedding_revision,
                   embedding_native_dimensions, embedding_storage_dimensions,
                   embedding_content_sha256, embedding_source_revision,
                   embedding_indexed_at, chunk_index,
                   embedding <=> CAST(:emb AS vector) as distance
            FROM document_embeddings
            WHERE {' AND '.join(clauses)}
            ORDER BY distance ASC
            LIMIT :n
        """)
        params["emb"] = emb_str

        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            result = await session.execute(sql, params)
            rows = result.fetchall()

        documents = [[row[1] for row in rows]]
        metadatas = [[{
            "chunk_id": str(row[0]),
            "doc_id": str(row[2]),
            "tenant_id": str(row[3]),
            "doc_name": row[4],
            "headings": row[5],
            "embedding_provider": row[6],
            "embedding_model": row[7],
            "embedding_revision": row[8],
            "embedding_native_dimensions": row[9],
            "embedding_storage_dimensions": row[10],
            "embedding_content_sha256": row[11],
            "embedding_source_revision": row[12],
            "embedding_indexed_at": (
                row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13])
            ),
            "chunk_index": row[14],
        } for row in rows]]
        distances = [[row[15] for row in rows]]

        return {"documents": documents, "metadatas": metadatas, "distances": distances}

    async def search_full_text(
        self,
        *,
        query_text: str,
        tenant_id: str | None,
        doc_ids: list[str],
        limit: int = 30,
    ) -> list[tuple[str, dict]]:
        """Return a bounded PostgreSQL FTS candidate set inside one tenant scope."""
        from sqlalchemy import text

        from app.core.db import async_session_factory

        if not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(query_text, str) or not query_text.strip():
            raise ValueError("full_text_query_required")
        if (
            not isinstance(doc_ids, list)
            or not doc_ids
            or any(not isinstance(doc_id, str) or not doc_id for doc_id in doc_ids)
        ):
            raise ValueError("document_ids_required")
        if type(limit) is not int or limit < 1 or limit > 100:
            raise ValueError("invalid_full_text_limit")

        unique_doc_ids = list(dict.fromkeys(doc_ids))
        params: dict = {
            "query_text": query_text.strip(),
            "tenant_id": tenant_id,
            "limit": limit,
        }
        placeholders = ", ".join(
            f":doc_id_{index}" for index in range(len(unique_doc_ids))
        )
        for index, doc_id in enumerate(unique_doc_ids):
            params[f"doc_id_{index}"] = doc_id

        statement = text(
            f"""
            WITH query AS (
                SELECT
                    websearch_to_tsquery('russian'::regconfig, :query_text) ||
                    websearch_to_tsquery('simple'::regconfig, :query_text) AS value
            )
            SELECT id, text, doc_id, tenant_id, doc_name, headings,
                   embedding_provider, embedding_model, embedding_revision,
                   embedding_native_dimensions, embedding_storage_dimensions,
                   embedding_content_sha256, embedding_source_revision,
                   embedding_indexed_at, chunk_index,
                   ts_rank_cd(embedding_fts, query.value) AS lexical_score
            FROM document_embeddings
            CROSS JOIN query
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND embedding_provenance_state = 'verified'
              AND {self._active_index_visibility_clause()}
              AND embedding_source_revision = 'document:' || (
                  SELECT active_document.content_sha256
                  FROM documents AS active_document
                  WHERE active_document.id::text = document_embeddings.doc_id
                    AND active_document.tenant_id = document_embeddings.tenant_id
              )
              AND doc_id IN ({placeholders})
              AND embedding_fts @@ query.value
            ORDER BY lexical_score DESC, doc_id ASC, chunk_index ASC, id ASC
            LIMIT :limit
            """
        )
        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            result = await session.execute(statement, params)
            rows = result.fetchall()

        return [
            (
                row[1],
                {
                    "chunk_id": str(row[0]),
                    "doc_id": str(row[2]),
                    "tenant_id": str(row[3]),
                    "doc_name": row[4],
                    "headings": row[5],
                    "embedding_provider": row[6],
                    "embedding_model": row[7],
                    "embedding_revision": row[8],
                    "embedding_native_dimensions": row[9],
                    "embedding_storage_dimensions": row[10],
                    "embedding_content_sha256": row[11],
                    "embedding_source_revision": row[12],
                    "embedding_indexed_at": (
                        row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13])
                    ),
                    "chunk_index": row[14],
                    "postgres_fts_score": float(row[15]),
                },
            )
            for row in rows
        ]

    async def get_all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> list[tuple[str, dict]]:
        """Get all chunks, optionally filtered by doc_ids."""
        from sqlalchemy import text

        from app.core.db import async_session_factory

        if not tenant_id:
            raise ValueError("tenant_id_required")
        params: dict = {}
        clauses = [
            "embedding_provenance_state = 'verified'",
            self._active_index_visibility_clause(),
            "embedding_source_revision = 'document:' || ("
            "SELECT active_document.content_sha256 FROM documents AS active_document "
            "WHERE active_document.id::text = document_embeddings.doc_id "
            "AND active_document.tenant_id = document_embeddings.tenant_id"
            ")",
        ]
        if doc_ids:
            if len(doc_ids) == 1:
                clauses.append("doc_id = :doc_id")
                params["doc_id"] = doc_ids[0]
            else:
                placeholders = ", ".join(f":doc_id_{i}" for i in range(len(doc_ids)))
                clauses.append(f"doc_id IN ({placeholders})")
                for i, did in enumerate(doc_ids):
                    params[f"doc_id_{i}"] = did
        where = "WHERE " + " AND ".join(clauses)

        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            result = await session.execute(
                text(
                    f"SELECT id, text, doc_id, tenant_id, doc_name, headings, "
                    f"embedding_provider, embedding_model, embedding_revision, "
                    f"embedding_native_dimensions, embedding_storage_dimensions, "
                    f"embedding_content_sha256, embedding_source_revision, "
                    f"embedding_indexed_at, chunk_index "
                    f"FROM document_embeddings {where}"
                ),
                params,
            )
            rows = result.fetchall()

        return [
            (
                row[1],
                {
                    "chunk_id": str(row[0]),
                    "doc_id": str(row[2]),
                    "tenant_id": str(row[3]),
                    "doc_name": row[4],
                    "headings": row[5],
                    "embedding_provider": row[6],
                    "embedding_model": row[7],
                    "embedding_revision": row[8],
                    "embedding_native_dimensions": row[9],
                    "embedding_storage_dimensions": row[10],
                    "embedding_content_sha256": row[11],
                    "embedding_source_revision": row[12],
                    "embedding_indexed_at": (
                        row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13])
                    ),
                    "chunk_index": row[14],
                },
            )
            for row in rows
        ]

    async def get_context_window(
        self,
        *,
        doc_id: str,
        source_revision: str,
        chunk_index: int,
        radius: int = 1,
        tenant_id: str | None = None,
    ) -> list[tuple[str, dict]]:
        """Read one bounded, version-scoped neighboring chunk window."""
        from sqlalchemy import text

        from app.core.db import async_session_factory

        if not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(doc_id, str) or not doc_id:
            raise ValueError("document_id_required")
        digest = source_revision.removeprefix("document:") if isinstance(source_revision, str) else ""
        if (
            not isinstance(source_revision, str)
            or not source_revision.startswith("document:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("invalid_document_source_revision")
        if type(chunk_index) is not int or chunk_index < 0:
            raise ValueError("invalid_chunk_index")
        if type(radius) is not int or radius < 0 or radius > 3:
            raise ValueError("invalid_context_radius")

        sql = text(
            f"""
            SELECT id, text, doc_id, tenant_id, doc_name, headings,
                   embedding_provider, embedding_model, embedding_revision,
                   embedding_native_dimensions, embedding_storage_dimensions,
                   embedding_content_sha256, embedding_source_revision,
                   embedding_indexed_at, chunk_index
            FROM document_embeddings
            WHERE embedding_provenance_state = 'verified'
              AND {self._active_index_visibility_clause()}
              AND doc_id = :doc_id
              AND embedding_source_revision = :source_revision
              AND chunk_index BETWEEN :lower_index AND :upper_index
            ORDER BY chunk_index ASC, id ASC
            """
        )
        params = {
            "doc_id": doc_id,
            "source_revision": source_revision,
            "lower_index": max(0, chunk_index - radius),
            "upper_index": chunk_index + radius,
        }
        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            result = await session.execute(sql, params)
            rows = result.fetchall()

        return [
            (
                row[1],
                {
                    "chunk_id": str(row[0]),
                    "doc_id": str(row[2]),
                    "tenant_id": str(row[3]),
                    "doc_name": row[4],
                    "headings": row[5],
                    "embedding_provider": row[6],
                    "embedding_model": row[7],
                    "embedding_revision": row[8],
                    "embedding_native_dimensions": row[9],
                    "embedding_storage_dimensions": row[10],
                    "embedding_content_sha256": row[11],
                    "embedding_source_revision": row[12],
                    "embedding_indexed_at": (
                        row[13].isoformat() if hasattr(row[13], "isoformat") else str(row[13])
                    ),
                    "chunk_index": row[14],
                },
            )
            for row in rows
        ]


class Summarizer:
    """Generate educational summaries for documents."""

    def __init__(self, llm_client=None):
        self.llm = llm_client

    async def summarize(self, markdown: str, doc_id: str, doc_name: str) -> dict:
        """Generate educational profile for a document."""
        # TODO: Call Qwen 3.5 when available
        # For now, return basic summary
        word_count = len(markdown.split())
        lines = markdown.split("\n")
        headings = [line.lstrip("#").strip() for line in lines if line.startswith("#")]

        return {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "summary": f"Document with {word_count} words",
            "word_count": word_count,
            "toc": "\n".join(f"- {h}" for h in headings[:20]),
            "chapters": {},
            "educational_summary": {
                "target_audience": "General audience",
                "global_description": f"Document about {headings[0] if headings else 'various topics'}",
                "core_topics": headings[:5],
                "extractable_skills": [],
            },
        }


class EmbeddingsProvider:
    """Embeddings with automatic fallback chain.

    Chain (June 2026):
      1. Qwen self-hosted (primary)
      1. Voyage voyage-4-lite via ResilientEmbeddingsClient (managed primary)
      2. Qwen self-hosted embeddings (fallback)
    Used by retrieval (Architect, Writer) and by DocumentIngestion.
    If both providers fail, indexing fails explicitly. Synthetic vectors are
    not valid for semantic retrieval or document compatibility decisions.
    """

    def __init__(self, qwen_url: str | None = None):
        # The legacy qwen_url arg is honored for tests but in production the
        # chain is built from settings (Voyage -> Cohere -> Qwen).
        from app.core.config import get_settings
        if qwen_url is None:
            qwen_url = get_settings().QWEN_EMBEDDING_URL
        self.qwen_url = qwen_url
        # Built lazily on first embed() call so config changes are picked up
        # and we don't spin up an httpx client until needed.
        self._client: ResilientEmbeddingsClient | None = None

    async def _get_client(self) -> ResilientEmbeddingsClient:
        if self._client is None:
            from app.modules.ai.llm_client import ResilientEmbeddingsClient
            self._client = await ResilientEmbeddingsClient.from_settings_async()
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings with automatic failover from Qwen to Voyage."""
        from app.modules.ai.llm_client import AllProvidersFailedError
        try:
            client = await self._get_client()
            return await client.embed_documents(texts)
        except AllProvidersFailedError:
            logger.error(
                "[EMBED_FAILOVER] All cloud embedding providers failed; "
                "document cannot be indexed semantically"
            )
            raise

    async def embed_documents_with_provenance(self, texts: list[str]) -> EmbeddingBatchResult:
        """Embed documents and retain the exact provider selected by failover."""
        from app.modules.ai.llm_client import AllProvidersFailedError

        try:
            client = await self._get_client()
            return await client.embed_documents_with_provenance(texts)
        except AllProvidersFailedError:
            logger.error(
                "[EMBED_FAILOVER] All cloud embedding providers failed; "
                "document cannot be indexed semantically"
            )
            raise

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        from app.modules.ai.llm_client import AllProvidersFailedError
        try:
            client = await self._get_client()
            return await client.embed_query(text)
        except AllProvidersFailedError:
            logger.error(
                "[EMBED_FAILOVER] All cloud embedding providers failed; "
                "semantic query cannot be executed"
            )
            raise

    async def embed_query_with_provenance(self, text: str) -> EmbeddingBatchResult:
        """Embed one semantic query and retain the selected embedding space."""
        from app.modules.ai.llm_client import AllProvidersFailedError

        try:
            client = await self._get_client()
            return await client.embed_query_with_provenance(text)
        except AllProvidersFailedError:
            logger.error(
                "[EMBED_FAILOVER] All cloud embedding providers failed; "
                "semantic query cannot be executed"
            )
            raise


class DocumentIngestion:
    """Full ingestion pipeline: parse → chunk → embed → store → summarize."""

    def __init__(
        self,
        persist_dir: str = "./chroma_data",
        summaries_dir: str = "./summaries",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        qwen_embeddings_url: str | None = None,
    ):
        self.persist_dir = persist_dir
        self.summaries_dir = summaries_dir
        self.converter = DocumentConverter()
        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.store = VectorStore(persist_dir)
        self.summarizer = Summarizer()
        self.embeddings = EmbeddingsProvider(qwen_url=qwen_embeddings_url)

    async def ingest_file(
        self, file_path: str, doc_id: str | None = None, tenant_id: str | None = None
    ) -> dict:
        """Ingest a single file through the full pipeline."""
        if not tenant_id:
            raise ValueError("tenant_id_required")
        filename = os.path.basename(file_path)
        if not doc_id:
            doc_id = hashlib.md5(filename.encode()).hexdigest()[:12]

        print(f"[INGEST] start doc_id={doc_id}", flush=True)

        # Step 1: Convert to markdown
        converted = await self.converter.convert(file_path)
        markdown = converted["markdown"]
        conversion_metadata = dict(converted.get("metadata") or {})
        print(
            f"[INGEST] converted {len(markdown)} chars "
            f"engine={conversion_metadata.get('engine', 'unknown')} "
            f"fallback={conversion_metadata.get('fallback_used', False)}",
            flush=True,
        )

        # Step 2: Chunk
        chunks = self.chunker.chunk_markdown(markdown, doc_id, filename)
        source_revision = f"document:{hashlib.sha256(markdown.encode('utf-8')).hexdigest()}"
        for chunk_index, chunk in enumerate(chunks):
            metadata = chunk.setdefault("metadata", {})
            metadata["source_revision"] = source_revision
            metadata["chunk_index"] = chunk_index
        print(f"[INGEST] chunked {len(chunks)} chunks", flush=True)

        if not chunks:
            conversion_engine = str(conversion_metadata.get("engine") or "")
            if Path(file_path).suffix.lower() == ".pdf" and conversion_engine == "pypdf":
                raise DocumentOCRRequiredError(
                    "This scanned PDF has no text layer and requires OCR. "
                    "The OCR service is currently unavailable; retry after it is restored."
                )
            raise DocumentNoContentError(
                "Document conversion produced no indexable text. "
                "Upload a document containing readable text."
            )

        # Step 3: Embed (Qwen → Voyage → hash fallback)
        texts = [c["text"] for c in chunks]
        try:
            embedding_batch = await self.embeddings.embed_documents_with_provenance(texts)
            embeddings = embedding_batch.as_lists()
            print(
                f"[INGEST] embedded {len(embeddings)} vectors "
                f"(dim={len(embeddings[0]) if embeddings else 0})",
                flush=True,
            )
        except Exception as e:
            # If the embedding chain blew up (not just failed-over), surface
            # it loudly. Status will be set to 'failed' by the caller.
            print(f"[INGEST] EMBED RAISED: {type(e).__name__}: {e}", flush=True)
            raise

        # Step 4: Store in pgvector
        try:
            dropped = await self.store.add_chunks(
                chunks,
                embedding_batch,
                tenant_id=tenant_id,
            )
            print(
                f"[INGEST] stored (dropped={dropped})",
                flush=True,
            )
            embeddings_written = len(chunks) - dropped
            if embeddings_written == 0 and len(chunks) > 0:
                # Every chunk's embedding was malformed. Surface this so
                # the upload router can mark embedding_status='failed'
                # instead of pretending the doc is good to use.
                raise RuntimeError(
                    f"All {len(chunks)} embeddings were malformed "
                    f"(None/NaN/inf/wrong dimensions). "
                    f"Doc will not be usable for AI generation."
                )
        except Exception as e:
            print(f"[INGEST] STORE RAISED: {type(e).__name__}: {e}", flush=True)
            raise

        # Step 5: Generate summary
        summary = await self.summarizer.summarize(markdown, doc_id, filename)
        os.makedirs(self.summaries_dir, exist_ok=True)
        summary_path = os.path.join(self.summaries_dir, f"{doc_id}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print("[INGEST] summary saved", flush=True)

        return {
            "doc_id": doc_id,
            "filename": filename,
            "chunks": len(chunks),
            "summary": summary,
            "embeddings_written": embeddings_written,
            "conversion": conversion_metadata,
        }

    async def ingest_files(
        self,
        file_paths: list[str],
        *,
        tenant_id: str,
    ) -> list[dict]:
        """Ingest multiple files."""
        results = []
        for fp in file_paths:
            result = await self.ingest_file(fp, tenant_id=tenant_id)
            results.append(result)
        return results
