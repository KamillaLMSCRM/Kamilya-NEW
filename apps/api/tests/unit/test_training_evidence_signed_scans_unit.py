from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.modules.training_evidence import signed_scan_service
from app.modules.training_evidence.signed_scan_service import (
    _storage_key,
    _valid_magic_bytes,
    append_signed_scan,
)


@pytest.mark.parametrize(
    ("content_type", "content", "expected"),
    [
        ("application/pdf", b"%PDF-1.7\nbody", True),
        ("image/jpeg", b"\xff\xd8\xff\xe0body", True),
        ("image/png", b"\x89PNG\r\n\x1a\nbody", True),
        ("application/pdf", b"not a pdf", False),
        ("image/jpeg", b"%PDF-1.7", False),
    ],
)
def test_signed_scan_magic_bytes_are_type_bound(content_type, content, expected):
    assert _valid_magic_bytes(content, content_type) is expected


def test_signed_scan_storage_key_is_tenant_and_event_scoped_without_filename():
    tenant_id, event_id, scan_id = uuid4(), uuid4(), uuid4()
    key = _storage_key(tenant_id, event_id, scan_id, "application/pdf")

    assert key == f"training-evidence/{tenant_id}/{event_id}/signed-scans/{scan_id}.pdf"
    assert ".." not in key
    assert "signed-copy" not in key


def test_signed_scan_migration_requires_append_only_rls_ownership_and_guarded_downgrade():
    migration = Path("alembic/versions/0107_training_evidence_signed_scans.py").read_text(encoding="utf-8")

    assert 'down_revision = "0106"' in migration
    assert "training_evidence_signed_scans" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "REVOKE ALL ON TABLE training_evidence_signed_scans FROM PUBLIC, lms_app" in migration
    assert "GRANT SELECT, INSERT ON training_evidence_signed_scans TO lms_app" in migration
    assert "validate_training_evidence_signed_scan_ownership" in migration
    assert "trg_prevent_training_evidence_signed_scan_mutation" in migration
    assert "training_evidence_retention_purge_authorized()" in migration
    assert "downgrade refused" in migration
    assert 'ondelete="CASCADE"' in migration


@pytest.mark.asyncio
async def test_signed_scan_compensates_storage_if_database_commit_fails(monkeypatch):
    tenant_id, event_id, enrollment_id, learner_id, uploader_id = (uuid4() for _ in range(5))
    event = SimpleNamespace(
        id=event_id,
        record_type="original",
        procedure_type="training",
        enrollment_id=enrollment_id,
        user_id=learner_id,
    )
    enrollment = SimpleNamespace(id=enrollment_id)

    class FailingDb:
        def __init__(self):
            self.scalars = iter((event, enrollment))
            self.added = None
            self.rolled_back = False

        async def scalar(self, _statement):
            return next(self.scalars)

        def add(self, value):
            self.added = value

        async def flush(self):
            return None

        async def commit(self):
            raise RuntimeError("database unavailable after object storage write")

        async def rollback(self):
            self.rolled_back = True

    class FakeStorage:
        def __init__(self):
            self.put = []
            self.deleted = []

        def put_bytes(self, key, data, content_type):
            self.put.append((key, data, content_type))
            return key

        def delete_bytes(self, key):
            self.deleted.append(key)
            return True

    db = FailingDb()
    storage = FakeStorage()
    monkeypatch.setattr(signed_scan_service, "get_storage", lambda: storage)
    upload = UploadFile(
        filename="returned-copy.pdf",
        file=BytesIO(b"%PDF-1.7\nhand-signed"),
        headers=Headers({"content-type": "application/pdf"}),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await append_signed_scan(
            db,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            uploader_user_id=uploader_id,
            event_id=event_id,
            file=upload,
        )

    assert db.rolled_back is True
    assert db.added is not None
    assert storage.put and storage.deleted == [storage.put[0][0]]
