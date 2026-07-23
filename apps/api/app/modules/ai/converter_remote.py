"""Docling remote converter — calls VPS-hosted Docling service."""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DOCLING_URL = os.getenv("DOCLING_URL", "http://173.249.51.164:8600")
DOCLING_API_KEY = os.getenv("DOCLING_API_KEY", "")


class DocumentConverter:
    """Convert documents to markdown via remote Docling service on VPS."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or DOCLING_URL).rstrip("/")

    async def convert(self, file_path: str) -> dict:
        """Send file to VPS Docling for conversion."""
        filename = os.path.basename(file_path)

        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/octet-stream")}
            headers = (
                {"X-Docling-Key": DOCLING_API_KEY}
                if DOCLING_API_KEY
                else None
            )
            try:
                async with httpx.AsyncClient(timeout=300) as client:
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
                        },
                    }
            except httpx.ConnectError:
                logger.warning(f"Docling service unreachable at {self.base_url}, using fallback")
                return await _fallback_convert(file_path)
            except Exception as e:
                logger.warning(f"Docling conversion failed: {e}, using fallback")
                return await _fallback_convert(file_path)


async def _fallback_convert(file_path: str) -> dict:
    """Basic fallback when Docling is unavailable."""
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    if ext in (".txt", ".md"):
        content = Path(file_path).read_text(encoding="utf-8")
    else:
        content = f"[Document: {os.path.basename(file_path)} — Docling service unavailable]"

    return {
        "markdown": content,
        "metadata": {"filename": os.path.basename(file_path), "size": os.path.getsize(file_path)},
    }
