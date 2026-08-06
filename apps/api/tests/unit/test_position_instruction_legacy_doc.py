from uuid import UUID

import pytest
from fastapi import HTTPException

from app.modules.positions import jd_router


@pytest.mark.asyncio
async def test_document_upload_restores_transaction_local_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, str]] = []

    async def restore(db: object, tenant_id: str) -> None:
        calls.append((db, tenant_id))

    monkeypatch.setattr(jd_router, "_set_tenant_security_context", restore)
    db = object()

    await jd_router._restore_tenant_context_after_document_upload(
        db,
        UUID("61cfa933-0d0b-45ab-bd11-353c4f3193f3"),
    )

    assert calls == [(db, "61cfa933-0d0b-45ab-bd11-353c4f3193f3")]


@pytest.mark.asyncio
async def test_legacy_doc_upload_defers_analysis_to_document_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_local_analysis(content: bytes, filename: str) -> dict:
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    monkeypatch.setattr(jd_router, "_analyze_jd_content", fail_local_analysis)

    result = await jd_router._analyze_instruction_for_upload(b"legacy", "expert.doc")

    assert result == {
        "name": "",
        "department": "",
        "level": "",
        "responsibilities": "",
        "requirements": "",
        "issues": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["expert.docx", "expert.pdf"])
async def test_instruction_upload_does_not_hide_other_extraction_failures(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    async def fail_local_analysis(content: bytes, current_filename: str) -> dict:
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    monkeypatch.setattr(jd_router, "_analyze_jd_content", fail_local_analysis)

    with pytest.raises(HTTPException) as exc_info:
        await jd_router._analyze_instruction_for_upload(b"broken", filename)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_instruction_upload_does_not_hide_ai_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_local_analysis(content: bytes, filename: str) -> dict:
        raise HTTPException(status_code=503, detail="AI unavailable")

    monkeypatch.setattr(jd_router, "_analyze_jd_content", fail_local_analysis)

    with pytest.raises(HTTPException) as exc_info:
        await jd_router._analyze_instruction_for_upload(b"legacy", "expert.doc")

    assert exc_info.value.status_code == 503
