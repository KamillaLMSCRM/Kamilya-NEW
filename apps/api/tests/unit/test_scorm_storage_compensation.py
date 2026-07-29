from __future__ import annotations

import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile


def _scorm12_zip() -> bytes:
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="M1"
 xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
 xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
 <metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>
 <organizations default="O1"><organization identifier="O1"><title>Course</title>
  <item identifier="I1" identifierref="R1"><title>Lesson</title></item>
 </organization></organizations>
 <resources><resource identifier="R1" type="webcontent"
  adlcp:scormtype="sco" href="index.html"><file href="index.html"/></resource></resources>
</manifest>"""
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("imsmanifest.xml", manifest)
        archive.writestr("index.html", "<html></html>")
    return output.getvalue()


@pytest.mark.asyncio
async def test_scorm_import_deletes_uploaded_object_when_database_work_fails():
    from app.modules.scorm.router import import_scorm_package

    class StorageStub:
        def __init__(self):
            self.put_key = None
            self.deleted_key = None

        def put_bytes(self, key, data, content_type):
            self.put_key = key

        def delete_bytes(self, key):
            self.deleted_key = key
            return True

    tenant_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )
    upload = UploadFile(filename="course.zip", file=BytesIO(_scorm12_zip()))
    storage = StorageStub()
    db = AsyncMock()
    db.add = Mock()

    async def flush_with_course_id():
        for call in db.add.call_args_list:
            entity = call.args[0]
            if entity.__class__.__name__ == "Course" and entity.id is None:
                entity.id = uuid4()

    db.flush.side_effect = flush_with_course_id

    with (
        patch("app.core.trial_limits.assert_can_create_courses", AsyncMock()),
        patch("app.modules.scorm.router.get_storage", return_value=storage),
        patch("app.modules.scorm.router.log_action", AsyncMock(side_effect=RuntimeError("audit failed"))),
    ):
        with pytest.raises(RuntimeError, match="audit failed"):
            await import_scorm_package(
                request=request,
                file=upload,
                title=None,
                status="draft",
                db=db,
                user=user,
            )

    assert storage.put_key is not None
    assert storage.deleted_key == storage.put_key
    db.rollback.assert_awaited_once()
