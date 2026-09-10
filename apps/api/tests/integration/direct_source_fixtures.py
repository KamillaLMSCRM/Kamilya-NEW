"""Local original-source fixtures for direct-source admission integration tests."""
from __future__ import annotations

import hashlib


class InMemoryOriginalStorage:
    """Minimal storage seam: production conversion still reads verified bytes."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.reads: list[str] = []

    def get_bytes(self, key: str) -> bytes | None:
        self.reads.append(key)
        return self.blobs.get(key)


async def seed_direct_source_documents(db_session, monkeypatch, documents, *, texts=None):
    """Attach truthful synthetic Markdown originals and patch only the storage seam."""
    blobs: dict[str, bytes] = {}
    texts = texts or {}
    for position, document in enumerate(documents):
        source_text = texts.get(document.id) or (
            f"# {document.title}\n\n"
            f"Synthetic training source {position + 1}. "
            "Follow the documented workplace safety procedure."
        )
        blob = source_text.encode("utf-8")
        key = f"integration-direct/{document.tenant_id}/{document.id}.md"
        document.filename = f"{document.id}.md"
        document.content_type = "text/markdown"
        document.s3_key = key
        document.size = len(blob)
        document.content_sha256 = hashlib.sha256(blob).hexdigest()
        blobs[key] = blob
    await db_session.flush()

    from app.core import storage as storage_module

    storage = InMemoryOriginalStorage(blobs)
    monkeypatch.setattr(storage_module, "get_storage", lambda: storage)
    return storage
