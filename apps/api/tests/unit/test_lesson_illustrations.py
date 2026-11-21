import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image, PngImagePlugin

from app.modules.courses.release_service import canonical_json_sha256
from app.modules.lessons import illustrations as images
from app.modules.source_preparation import assets


def picture(format_name="PNG"):
    stream = BytesIO()
    options = {}
    if format_name == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("note", "metadata must not be delivered")
        options["pnginfo"] = info
    Image.new("RGB", (7, 5), (50, 80, 140)).save(stream, format_name, **options)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_upload_is_tenant_course_lesson_scoped_and_reuses_exact_bytes(monkeypatch):
    tenant, course, lesson = uuid4(), uuid4(), uuid4()
    blobs = {}
    storage = SimpleNamespace(put_bytes=lambda key, raw, mime: blobs.update({key: (raw, mime)}))
    monkeypatch.setattr(images, "get_storage", lambda: storage)
    db = SimpleNamespace(scalar=AsyncMock(return_value=lesson))
    file = picture()
    first = await images.upload_illustration(db, tenant, course, lesson, UploadFile(BytesIO(file)))
    second = await images.upload_illustration(db, tenant, course, lesson, UploadFile(BytesIO(file)))
    assert first == second and len(blobs) == 1
    key, (raw, mime) = next(iter(blobs.items()))
    assert key.startswith(f"lesson-illustrations/{tenant}/{course}/{lesson}/")
    assert mime == "image/png"
    with Image.open(BytesIO(raw)) as saved:
        assert saved.size == (7, 5) and saved.info == {}
    assert {tenant, course, lesson} <= set(db.scalar.await_args.args[0].compile().params.values())
    db.scalar.return_value = None
    denied = UploadFile(BytesIO(file))
    with pytest.raises(HTTPException) as error:
        await images.upload_illustration(db, uuid4(), course, lesson, denied)
    assert error.value.status_code == 404 and denied.file.tell() == 0 and len(blobs) == 1


@pytest.mark.parametrize(("file", "expected"), (
    (b"<svg><script/></svg>", 422),
    (picture()[:33], 422),
    (b"x" * (images.MAX_IMAGE_BYTES + 1), 413),
), ids=("svg", "truncated", "oversized"))
@pytest.mark.asyncio
async def test_invalid_bytes_never_reach_storage(monkeypatch, file, expected):
    lesson = uuid4()
    db = SimpleNamespace(scalar=AsyncMock(return_value=lesson))
    storage = Mock()
    monkeypatch.setattr(images, "get_storage", storage)
    with pytest.raises(HTTPException) as error:
        await images.upload_illustration(db, uuid4(), uuid4(), lesson, UploadFile(BytesIO(file)))
    assert error.value.status_code == expected
    storage.assert_not_called()


@pytest.mark.asyncio
async def test_learner_reads_only_an_illustration_in_their_intact_publication(monkeypatch):
    tenant, course, lesson = uuid4(), uuid4(), uuid4()
    raw, extension, _ = images._normalize(picture("JPEG"))
    asset = f"illustration-{hashlib.sha256(raw).hexdigest()}.{extension}"
    url = images.lesson_image_url(course, lesson, asset)
    lesson_snapshot = {"id": str(lesson), "content": f'![Alt]({url} "Caption")'}
    snapshot = {"course": {"id": str(course), "tenant_id": str(tenant)}, "source_documents": [],
                "modules": [{"lessons": [lesson_snapshot]}]}
    release = SimpleNamespace(snapshot=snapshot, snapshot_sha256=canonical_json_sha256(snapshot))
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [release])))
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant, role="student")
    monkeypatch.setattr(assets, "require_course_access", AsyncMock())
    read = Mock(return_value=raw)
    monkeypatch.setattr(assets, "get_storage", lambda: SimpleNamespace(get_bytes=read))
    response = await assets.course_asset(db, course, lesson, asset, user)
    assert response.body == raw and response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    read.reset_mock()
    for chosen_tenant, chosen_lesson, chosen_asset in (
        (uuid4(), lesson, asset), (tenant, uuid4(), asset), (tenant, lesson, "illustration-" + "b" * 64 + ".jpg"),
    ):
        user.tenant_id = chosen_tenant
        with pytest.raises(HTTPException) as error:
            await assets.course_asset(db, course, chosen_lesson, chosen_asset, user)
        assert error.value.status_code == 404
    lesson_snapshot["content"] = "Unpublished change"
    with pytest.raises(HTTPException):
        await assets.course_asset(db, course, lesson, asset, user)
    read.assert_not_called()
