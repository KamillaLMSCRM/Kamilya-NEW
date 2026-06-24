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


class DocumentConverter:
    """Convert documents to markdown using Docling."""

    def __init__(self):
        self._converter = None

    def _get_converter(self):
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter as DoclingConverter
                self._converter = DoclingConverter()
            except ImportError:
                logger.warning("Docling not installed, using fallback parser")
                self._converter = _FallbackConverter()
        return self._converter

    async def convert(self, file_path: str) -> dict:
        """Convert document to markdown + metadata."""
        converter = self._get_converter()
        result = converter.convert(file_path)
        return {
            "markdown": result.document.export_to_markdown() if hasattr(result, "document") else str(result),
            "metadata": {
                "filename": os.path.basename(file_path),
                "size": os.path.getsize(file_path),
            },
        }


class _FallbackConverter:
    """Fallback when Docling is not installed."""

    def convert(self, file_path: str):
        ext = Path(file_path).suffix.lower()
        if ext == ".txt":
            content = Path(file_path).read_text(encoding="utf-8")
        elif ext == ".md":
            content = Path(file_path).read_text(encoding="utf-8")
        else:
            content = f"[Document: {os.path.basename(file_path)} — install Docling for full parsing]"

        class _Result:
            def __init__(self, text):
                class _Doc:
                    def export_to_markdown(self):
                        return text
                self.document = _Doc()

        return _Result(content)


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

    async def add_chunks(self, chunks: list[dict], embeddings: list[list[float]], tenant_id: str | None = None):
        """Add chunks with embeddings to Supabase."""
        from app.core.db import async_session_factory
        from sqlalchemy import text
        import hashlib
        async with async_session_factory() as session:
            for chunk, emb in zip(chunks, embeddings):
                chunk_id = hashlib.md5(chunk["text"].encode()).hexdigest()
                meta = chunk.get("metadata", {})
                await session.execute(
                    text(
                        """INSERT INTO document_embeddings (id, tenant_id, doc_id, text, headings, doc_name, embedding)
                           VALUES (:id, :tenant_id, :doc_id, :text, :headings, :doc_name, :embedding)
                           ON CONFLICT (id) DO NOTHING"""
                    ),
                    {
                        "id": chunk_id,
                        "tenant_id": tenant_id,
                        "doc_id": meta.get("doc_id", ""),
                        "text": chunk["text"],
                        "headings": meta.get("headings", ""),
                        "doc_name": meta.get("doc_name", ""),
                        "embedding": str(emb),
                    }
                )
            await session.commit()

    async def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: dict | None = None,
        include: list[str] | None = None,
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
        sql = text(f"""
            SELECT text, doc_name, headings,
                   1 - (embedding <=> :emb::vector) as distance
            FROM document_embeddings
            {where_clause}
            ORDER BY distance
            LIMIT :n
        """)
        params["emb"] = emb_str

        async with async_session_factory() as session:
            result = await session.execute(sql, params)
            rows = result.fetchall()

        documents = [[row[0] for row in rows]]
        metadatas = [[{"doc_name": row[1], "headings": row[2]} for row in rows]]
        distances = [[row[3] for row in rows]]

        return {"documents": documents, "metadatas": metadatas, "distances": distances}

    async def get_all_chunks(self, doc_ids: list[str] | None = None) -> list[tuple[str, dict]]:
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
    """Embeddings with automatic fallback: Qwen → simple hash-based."""

    def __init__(self, qwen_url: str | None = None):
        from app.core.config import get_settings
        if qwen_url is None:
            qwen_url = get_settings().QWEN_EMBEDDING_URL
        self.qwen_url = qwen_url
        self._qwen_available: bool | None = None

    async def _try_qwen(self, texts: list[str]) -> list[list[float]] | None:
        """Try Qwen embeddings API. Returns None if unavailable."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.qwen_url}/embeddings",
                    json={"model": "Qwen3-Embedding-8B", "input": texts},
                    headers={"Authorization": "Bearer not-needed"},
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
        except Exception:
            return None

    def _hash_embedding(self, text: str, dim: int = 4096) -> list[float]:
        """Deterministic hash-based embedding (for BM25-like text matching)."""
        import hashlib
        h = hashlib.sha512(text.encode("utf-8")).digest()
        # Expand to desired dimension
        raw = []
        for i in range(0, dim * 4, 4):
            chunk = h[i % len(h):] + h[:i % len(h)]
            raw.append(int.from_bytes(chunk[:4], "big"))
        # Normalize to [-1, 1]
        import struct
        return [struct.unpack("f", struct.pack("I", v & 0xFFFFFFFF))[0] for v in raw[:dim]]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings with automatic fallback."""
        if self._qwen_available is not False:
            result = await self._try_qwen(texts)
            if result is not None:
                self._qwen_available = True
                logger.info("Using Qwen embeddings")
                return result
            self._qwen_available = False
            logger.warning("Qwen embeddings unavailable, falling back to hash-based")

        return [self._hash_embedding(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        results = await self.embed([text])
        return results[0]


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

        logger.info(f"Ingesting document: {filename} (id={doc_id})")

        # Step 1: Convert to markdown
        converted = await self.converter.convert(file_path)
        markdown = converted["markdown"]
        logger.info(f"  Converted: {len(markdown)} chars")

        # Step 2: Chunk
        chunks = self.chunker.chunk_markdown(markdown, doc_id, filename)
        logger.info(f"  Chunked: {len(chunks)} chunks")

        # Step 3: Embed (Qwen → hash fallback)
        texts = [c["text"] for c in chunks]
        embeddings = await self.embeddings.embed(texts)
        logger.info(f"  Embedded: {len(embeddings)} vectors (dim={len(embeddings[0]) if embeddings else 0})")

        # Step 4: Store in Supabase pgvector
        await self.store.add_chunks(chunks, embeddings, tenant_id=tenant_id)
        logger.info(f"  Stored in Supabase pgvector")

        # Step 5: Generate summary
        summary = await self.summarizer.summarize(markdown, doc_id, filename)
        os.makedirs(self.summaries_dir, exist_ok=True)
        summary_path = os.path.join(self.summaries_dir, f"{doc_id}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info(f"  Summary saved: {summary_path}")

        return {
            "doc_id": doc_id,
            "filename": filename,
            "chunks": len(chunks),
            "summary": summary,
        }

    async def ingest_files(self, file_paths: list[str]) -> list[dict]:
        """Ingest multiple files."""
        results = []
        for fp in file_paths:
            result = await self.ingest_file(fp)
            results.append(result)
        return results
