"""Document ingestion — parsing, chunking, embedding, vector store."""
from __future__ import annotations

import json
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DOCLING_URL = os.getenv("DOCLING_URL", "http://173.249.51.164:8600")


class DocumentConverter:
    """Convert documents to markdown — remote Docling on VPS, local fallback."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or DOCLING_URL).rstrip("/")

    async def convert(self, file_path: str) -> dict:
        """Convert document to markdown + metadata."""
        filename = os.path.basename(file_path)

        # Try remote Docling first
        try:
            import httpx
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                async with httpx.AsyncClient(timeout=300) as client:
                    resp = await client.post(f"{self.base_url}/convert", files=files)
                    resp.raise_for_status()
                    data = resp.json()
                    return {
                        "markdown": data["markdown"],
                        "metadata": {
                            "filename": filename,
                            "size": os.path.getsize(file_path),
                            "pages": data.get("pages", 0),
                            "tables": data.get("tables", 0),
                        },
                    }
        except Exception as e:
            logger.warning(f"Remote Docling unavailable ({e}), using local fallback")

        # Local fallback
        return await _local_convert(file_path)


async def _local_convert(file_path: str) -> dict:
    """Local fallback — try docling import, then basic text read."""
    ext = Path(file_path).suffix.lower()
    if ext in (".txt", ".md"):
        content = Path(file_path).read_text(encoding="utf-8")
    else:
        content = f"[Document: {os.path.basename(file_path)} — Docling service unavailable]"
    return {
        "markdown": content,
        "metadata": {"filename": os.path.basename(file_path), "size": os.path.getsize(file_path)},
    }



class DocumentChunker:
    """Split documents into chunks for embedding."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_markdown(self, markdown: str, doc_id: str, doc_name: str) -> list[dict]:
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

    async def _set_tenant_context(self, session, tenant_id: str | None) -> None:
        if tenant_id:
            from sqlalchemy import text
            await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})

    async def add_chunks(self, chunks: list[dict], embeddings: list[list[float]], tenant_id: str | None = None):
        """Add chunks with embeddings to Supabase.

        Defends against malformed vectors (NaN/inf) that occasionally
        come back from cloud embedding providers. Postgres pgvector
        rejects these with a cryptic 'NaN not allowed in vector'
        DataError, which used to mark the whole document as
        embedding_status='failed' and block any AI generation against
        it — see bug 2026-06-26: re-uploading the document didn't
        help because the failing chunk was consistently the same.
        Now we drop bad vectors at the door and log them so the
        document is at least partially usable.
        """
        from app.core.db import async_session_factory
        from sqlalchemy import text
        import hashlib
        import math
        import logging as _log
        _logger = _log.getLogger(__name__)

        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            dropped = 0
            inserted = 0
            last_doc_id = ""
            for chunk, emb in zip(chunks, embeddings):
                # Sanity-check the vector: reject NaN/inf in any component.
                # If the provider returned garbage, skip the chunk rather
                # than blow up the whole insert.
                if emb is None or any(
                    not isinstance(x, (int, float)) or math.isnan(x) or math.isinf(x)
                    for x in emb
                ):
                    _logger.warning(
                        "Skipping chunk with malformed embedding "
                        "(None/NaN/inf). doc_id=%s text_preview=%r",
                        chunk.get("metadata", {}).get("doc_id", "?"),
                        (chunk.get("text") or "")[:60],
                    )
                    dropped += 1
                    continue

                # Composite id: doc_id + text. Was previously just md5(text),
                # which collided across documents that share paragraphs
                # (any reused boilerplate like "## Overview" with identical
                # content produced the same chunk_id) — and ON CONFLICT DO
                # NOTHING then silently skipped every insert for that
                # overlap. Composite id ensures each (doc, chunk) pair is
                # unique; ON CONFLICT becomes a genuine no-op only when
                # the same chunk of the same doc is re-uploaded.
                meta = chunk.get("metadata", {})
                last_doc_id = meta.get("doc_id", "")
                chunk_id = hashlib.md5(
                    f"{last_doc_id}|{chunk['text']}".encode()
                ).hexdigest()
                await session.execute(
                    text(
                        """INSERT INTO document_embeddings (id, tenant_id, doc_id, text, headings, doc_name, embedding)
                           VALUES (:id, :tenant_id, :doc_id, :text, :headings, :doc_name, :embedding)
                           ON CONFLICT (id) DO NOTHING"""
                    ),
                    {
                        "id": chunk_id,
                        "tenant_id": tenant_id,
                        "doc_id": last_doc_id,
                        "text": chunk["text"],
                        "headings": meta.get("headings", ""),
                        "doc_name": meta.get("doc_name", ""),
                        "embedding": str(emb),
                    }
                )
                inserted += 1
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
            await self._set_tenant_context(session, tenant_id)

            # Verify rows landed — first inside the session (best-effort,
            # may see 0 under PgBouncer), then on a fresh session that
            # has to read from the committed transaction snapshot.
            cnt = await session.execute(
                text(
                    "SELECT COUNT(*) FROM document_embeddings "
                    "WHERE doc_id::text = :did"
                ),
                {"did": last_doc_id},
            )
            count_in_session = cnt.scalar()

            # Second check: open a NEW session and read from a different
            # connection. This is the ground-truth — if PgBouncer gave us
            # a different backend after commit, this is what other
            # workers / queries will see.
            from app.core.db import async_session_factory as _fresh_factory
            async with _fresh_factory() as fresh:
                await self._set_tenant_context(fresh, tenant_id)
                cnt2 = await fresh.execute(
                    text(
                        "SELECT COUNT(*) FROM document_embeddings "
                        "WHERE doc_id::text = :did"
                    ),
                    {"did": last_doc_id},
                )
                count_in_fresh = cnt2.scalar()
            print(
                f"[INGEST] add_chunks post-commit: inserted_attempted={inserted} "
                f"dropped={dropped} count_in_session={count_in_session} "
                f"count_in_fresh={count_in_fresh}",
                flush=True,
            )

            # Verify rows landed by counting from the same session, AFTER flush.
            # This block is intentionally a no-op after the new
            # diagnostic above (count_in_fresh) — kept only so the
            # function still exits cleanly. The fresh-session count is
            # the ground truth under PgBouncer.
            if dropped:
                _logger.warning(
                    "add_chunks: dropped %d malformed embeddings "
                    "(see warnings above). Document may have partial coverage.",
                    dropped,
                )
            return dropped

    async def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: dict | None = None,
        include: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """Query the vector store using pgvector cosine distance."""
        from app.core.db import async_session_factory
        from sqlalchemy import text
        emb = query_embeddings[0]

        where_clause = ""
        params: dict = {"n": n_results}
        if where:
            doc_id = where.get("doc_id")
            if doc_id:
                if isinstance(doc_id, dict) and "$in" in doc_id:
                    ids = doc_id["$in"]
                    placeholders = ", ".join(f":doc_id_{i}" for i in range(len(ids)))
                    where_clause = f"WHERE doc_id IN ({placeholders})"
                    for i, did in enumerate(ids):
                        params[f"doc_id_{i}"] = did
                else:
                    where_clause = "WHERE doc_id = :doc_id"
                    params["doc_id"] = doc_id

        emb_str = str(emb)
        # NOTE: Use CAST(:emb AS vector) instead of ':emb'::vector or :emb::vector.
        # - ':emb'::vector (f-string interpolation) works but looks like SQL injection
        #   to security scanners, and a previous audit (a1ea9c9) flagged it.
        # - :emb::vector (bind param with cast) raises "syntax error at or near ':'"
        #   because PostgreSQL parses :emb: as a placeholder + 'vector' as literal.
        # CAST(:emb AS vector) is the standard SQL form that works with bind params
        # and is also safe-looking for auditors. emb_str is a list of floats from
        # the embedding model, not user input, so the bind value is well-typed.
        sql = text(f"""
            SELECT text, doc_name, headings,
                   1 - (embedding <=> CAST(:emb AS vector)) as distance
            FROM document_embeddings
            {where_clause}
            ORDER BY distance
            LIMIT :n
        """)
        params["emb"] = emb_str

        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            result = await session.execute(sql, params)
            rows = result.fetchall()

        documents = [[row[0] for row in rows]]
        metadatas = [[{"doc_name": row[1], "headings": row[2]} for row in rows]]
        distances = [[row[3] for row in rows]]

        return {"documents": documents, "metadatas": metadatas, "distances": distances}

    async def get_all_chunks(
        self,
        doc_ids: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> list[tuple[str, dict]]:
        """Get all chunks, optionally filtered by doc_ids."""
        from app.core.db import async_session_factory
        from sqlalchemy import text
        params: dict = {}
        where = ""
        if doc_ids:
            if len(doc_ids) == 1:
                where = "WHERE doc_id = :doc_id"
                params["doc_id"] = doc_ids[0]
            else:
                placeholders = ", ".join(f":doc_id_{i}" for i in range(len(doc_ids)))
                where = f"WHERE doc_id IN ({placeholders})"
                for i, did in enumerate(doc_ids):
                    params[f"doc_id_{i}"] = did

        async with async_session_factory() as session:
            await self._set_tenant_context(session, tenant_id)
            result = await session.execute(text(f"SELECT text, doc_id, doc_name, headings FROM document_embeddings {where}"), params)
            rows = result.fetchall()

        return [(row[0], {"doc_id": row[1], "doc_name": row[2], "headings": row[3]}) for row in rows]


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
        headings = [l.lstrip("#").strip() for l in lines if l.startswith("#")]

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
      2. Voyage voyage-4-lite via ResilientEmbeddingsClient (fallback if Qwen down)
      3. Hash-based deterministic embedding (last resort — non-semantic, but
         keeps ingestion alive if both cloud providers are down)

    Used by retrieval (Architect, Writer) and by DocumentIngestion.
    """

    def __init__(self, qwen_url: str | None = None):
        # The legacy qwen_url arg is honored for tests but in production the
        # chain is built from settings (Qwen + optional Voyage).
        from app.core.config import get_settings
        if qwen_url is None:
            qwen_url = get_settings().QWEN_EMBEDDING_URL
        self.qwen_url = qwen_url
        # Built lazily on first embed() call so config changes are picked up
        # and we don't spin up an httpx client until needed.
        self._client = None

    def _get_client(self):
        if self._client is None:
            from app.modules.ai.llm_client import ResilientEmbeddingsClient
            self._client = ResilientEmbeddingsClient.from_settings()
        return self._client

    def _hash_embedding(self, text: str, dim: int = 4096) -> list[float]:
        """Deterministic hash-based embedding (last-resort, non-semantic).

        Uses a seeded random generator so the same text always produces
        the same vector. All values are explicitly clamped to a finite
        range — the previous bit-shuffle implementation could emit
        NaN/inf for some bit patterns, which Postgres pgvector rejects
        with a cryptic DataError and which used to mark the whole
        document as embedding_status='failed' (see bug 2026-06-26).
        """
        import hashlib
        import random
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        # Each component in [-1.0, 1.0). Never NaN, never inf.
        return [rng.uniform(-1.0, 1.0) for _ in range(dim)]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings with automatic failover Qwen → Voyage → hash."""
        from app.modules.ai.llm_client import AllProvidersFailedError
        try:
            return await self._get_client().embed_documents(texts)
        except AllProvidersFailedError:
            logger.error(
                "[EMBED_FAILOVER] All cloud embedding providers failed; "
                "using hash-based fallback (non-semantic)"
            )
            return [self._hash_embedding(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        from app.modules.ai.llm_client import AllProvidersFailedError
        try:
            return await self._get_client().embed_query(text)
        except AllProvidersFailedError:
            logger.error(
                "[EMBED_FAILOVER] All cloud embedding providers failed; "
                "using hash-based fallback (non-semantic)"
            )
            return self._hash_embedding(text)


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
        filename = os.path.basename(file_path)
        if not doc_id:
            doc_id = hashlib.md5(filename.encode()).hexdigest()[:12]

        print(f"[INGEST] start file={filename} doc_id={doc_id}", flush=True)

        # Step 1: Convert to markdown
        converted = await self.converter.convert(file_path)
        markdown = converted["markdown"]
        print(f"[INGEST] converted {len(markdown)} chars", flush=True)

        # Step 2: Chunk
        chunks = self.chunker.chunk_markdown(markdown, doc_id, filename)
        print(f"[INGEST] chunked {len(chunks)} chunks", flush=True)

        # Step 3: Embed (Qwen → Voyage → hash fallback)
        texts = [c["text"] for c in chunks]
        try:
            embeddings = await self.embeddings.embed(texts)
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
            dropped = await self.store.add_chunks(chunks, embeddings, tenant_id=tenant_id)
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
                    f"(None/NaN/inf). Doc will not be usable for AI generation."
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
        print(f"[INGEST] summary saved", flush=True)

        return {
            "doc_id": doc_id,
            "filename": filename,
            "chunks": len(chunks),
            "summary": summary,
            "embeddings_written": embeddings_written,
        }

    async def ingest_files(self, file_paths: list[str]) -> list[dict]:
        """Ingest multiple files."""
        results = []
        for fp in file_paths:
            result = await self.ingest_file(fp)
            results.append(result)
        return results
