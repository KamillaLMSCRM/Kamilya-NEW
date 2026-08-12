"""Driver-specific duplicate-document error recognition."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers

from app.modules.documents import router as documents_router
from app.modules.documents.router import (
    _is_active_document_hash_unique_violation,
    upload_document,
)


def _integrity_error_with_cause(constraint_name: str) -> IntegrityError:
    cause = RuntimeError("unique violation")
    cause.constraint_name = constraint_name
    orig = RuntimeError("asyncpg adapter error")
    orig.__cause__ = cause
    return IntegrityError("insert", {}, orig)


def test_recognizes_asyncpg_nested_constraint_name() -> None:
    assert _is_active_document_hash_unique_violation(
        _integrity_error_with_cause("uq_documents_active_tenant_content_sha256")
    )


def test_recognizes_psycopg_diag_constraint_name() -> None:
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name="uq_documents_active_tenant_content_sha256"))
    assert _is_active_document_hash_unique_violation(IntegrityError("insert", {}, orig))


def test_rejects_unrelated_integrity_error() -> None:
    assert not _is_active_document_hash_unique_violation(_integrity_error_with_cause("some_other_unique_index"))


@pytest.mark.asyncio
async def test_upload_loser_returns_duplicate_without_writing_or_deleting_blob(
    monkeypatch,
) -> None:
    winner = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        title="Existing policy",
        filename="existing.txt",
        version=1,
    )

    class FakeSession:
        scalar_calls = 0

        async def scalar(self, statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else winner

        async def execute(self, statement, params=None):
            return None

        def add(self, value):
            return None

        async def rollback(self):
            return None

    class StorageStub:
        stored: list[str] = []
        deleted: list[str] = []

        def put_bytes(self, key, content, content_type):
            self.stored.append(key)

        def delete_bytes(self, key):
            self.deleted.append(key)

    async def lose_unique_race(*args, **kwargs):
        raise _integrity_error_with_cause("uq_documents_active_tenant_content_sha256")

    async def allow_document(*args, **kwargs):
        return None

    storage = StorageStub()
    monkeypatch.setattr(documents_router, "create_ai_job", lose_unique_race)
    monkeypatch.setattr(documents_router, "get_storage", lambda: storage)
    monkeypatch.setattr(
        "app.core.demo_limits.assert_can_create_document",
        allow_document,
    )
    file = UploadFile(
        file=BytesIO(b"same file"),
        filename="renamed.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    with pytest.raises(HTTPException) as error:
        await upload_document(
            file=file,
            title="Renamed",
            description="",
            category="general",
            new_version_of=None,
            db=FakeSession(),
            user=SimpleNamespace(
                id="22222222-2222-2222-2222-222222222222",
                tenant_id="33333333-3333-3333-3333-333333333333",
            ),
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "duplicate_document"
    assert storage.stored == []
    assert storage.deleted == []
