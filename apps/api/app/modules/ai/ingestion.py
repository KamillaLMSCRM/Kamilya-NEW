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
    """ChromaDB vector store wrapper."""

    def __init__(self, persist_dir: str = "./chroma_data"):
        self.persist_dir = persist_dir
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            try:
                import chromadb
                client = chromadb.PersistentClient(path=self.persist_dir)
                self._collection = client.get_or_create_collection(
                    name="kamilya_documents",
                    metadata={"hnsw:space": "cosine"},
                )
            except ImportError:
                logger.warning("ChromaDB not installed")
                return None
        return self._collection

    def add_chunks(self, chunks: list[dict], embeddings: list[list[float]]):
        """Add chunks with embeddings to the store."""
        collection = self._get_collection()
        if collection is None:
            return

        ids = [hashlib.md5(c["text"].encode()).hexdigest() for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]

        collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> dict:
        """Query the vector store."""
        collection = self._get_collection()
        if collection is None:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        kwargs: dict[str, Any] = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        if include:
            kwargs["include"] = include

        return collection.query(**kwargs)

    def get_all_chunks(self, doc_ids: list[str] | None = None) -> list[tuple[str, dict]]:
        """Get all chunks, optionally filtered by doc_ids."""
        collection = self._get_collection()
        if collection is None:
            return []

        where = None
        if doc_ids:
            if len(doc_ids) == 1:
                where = {"doc_id": doc_ids[0]}
            else:
                where = {"doc_id": {"$in": doc_ids}}

        kwargs: dict[str, Any] = {}
        if where:
            kwargs["where"] = where

        result = collection.get(**kwargs)
        pairs = []
        for doc, meta in zip(result.get("documents", []), result.get("metadatas", [])):
            pairs.append((doc, meta))
        return pairs


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


class DocumentIngestion:
    """Full ingestion pipeline: parse → chunk → embed → store → summarize."""

    def __init__(
        self,
        persist_dir: str = "./chroma_data",
        summaries_dir: str = "./summaries",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.persist_dir = persist_dir
        self.summaries_dir = summaries_dir
        self.converter = DocumentConverter()
        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.store = VectorStore(persist_dir)
        self.summarizer = Summarizer()

    async def ingest_file(
        self, file_path: str, doc_id: str | None = None
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

        # Step 3: Embed (placeholder — will use Qwen Embeddings when available)
        embeddings = [[0.0] * 1024] * len(chunks)  # Placeholder
        logger.info(f"  Embedded: {len(embeddings)} vectors")

        # Step 4: Store in ChromaDB
        self.store.add_chunks(chunks, embeddings)
        logger.info(f"  Stored in ChromaDB")

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
