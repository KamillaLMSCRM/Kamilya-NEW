import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.course_approval.router import get_review_attempt_asset
from app.modules.course_approval.service import learner_safe_review_snapshot
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.documents.cleanup import _source_asset_keys
from app.modules.documents.service import list_document_usages
from app.modules.lessons.schemas import ContentBlockResponse
from app.modules.source_preparation import assets
from app.modules.source_preparation.domain import PreparedSource, digest


def fixture():
    tenant, document, course, lesson = uuid4(), uuid4(), uuid4(), uuid4()
    payload = b"image data"
    sha = hashlib.sha256(payload).hexdigest()
    descriptor = {"id": "asset-" + sha, "document_id": str(document), "sha256": sha,
                  "mime_type": "image/png", "storage_key": f"source-assets/{tenant}/{document}/{sha}.png",
                  "preparation_sha256": "a" * 64}
    snapshot = {"course": {"id": str(course), "tenant_id": str(tenant)},
                "source_documents": [{"id": str(document)}], "modules": [{"lessons": [
                    {"id": str(lesson), "content_blocks": [{"metadata": {"source_asset": descriptor}}]}]}]}
    return tenant, document, course, lesson, payload, descriptor, snapshot


def test_frozen_membership_and_key_validation():
    tenant, document, course, lesson, _, item, snapshot = fixture()
    assert assets._snapshot_descriptor(snapshot, course, lesson, tenant, item["id"]) == item
    assert assets._snapshot_descriptor(snapshot, course, uuid4(), tenant, item["id"]) is None
    assert assets._snapshot_descriptor(snapshot, uuid4(), lesson, tenant, item["id"]) is None
    assert assets._snapshot_descriptor(snapshot, course, lesson, uuid4(), item["id"]) is None
    assert assets._snapshot_descriptor(snapshot, course, lesson, tenant, "asset-" + "f" * 64) is None
    snapshot["source_documents"] = []
    assert assets._snapshot_descriptor(snapshot, course, lesson, tenant, item["id"]) is None
    assert assets._descriptor({**item, "storage_key": "other/path"}, tenant, item["id"]) is None
    assert assets._descriptor({**item, "sha256": "b" * 64}, tenant, item["id"]) is None


def test_review_snapshot_does_not_expose_storage_key():
    _, _, _, _, _, item, snapshot = fixture()
    safe = learner_safe_review_snapshot(snapshot)
    descriptor = safe["modules"][0]["lessons"][0]["content_blocks"][0]["metadata"]["source_asset"]
    assert "storage_key" not in descriptor and descriptor["id"] == item["id"]
    assert "storage_key" in item


def test_lesson_content_block_does_not_expose_storage_key():
    _, _, _, lesson, _, item, _ = fixture()
    result = ContentBlockResponse.model_validate({"id": uuid4(), "lesson_id": lesson, "block_type": "image",
        "order_index": 0, "metadata": {"source_asset": item}, "created_at": datetime.now(UTC)})
    assert "storage_key" not in json.loads(result.metadata)["source_asset"]
    assert "storage_key" in item


def test_stored_bytes_are_integrity_checked(monkeypatch):
    tenant, _, _, _, payload, item, _ = fixture()
    monkeypatch.setattr(assets, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _: payload))
    response = assets._response(assets._descriptor(item, tenant, item["id"]))
    assert response.body == payload and response.headers["cache-control"] == "private, no-store"
    monkeypatch.setattr(assets, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _: b"changed"))
    with pytest.raises(HTTPException) as error:
        assets._response(item)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_student_reads_only_membership_in_intact_release(monkeypatch):
    tenant, _, course, lesson, payload, item, snapshot = fixture()
    release = SimpleNamespace(snapshot=snapshot, snapshot_sha256=canonical_json_sha256(snapshot))
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [release])))
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant, role="student")
    monkeypatch.setattr(assets, "require_course_access", AsyncMock())
    monkeypatch.setattr(assets, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _: payload))
    assert (await assets.course_asset(db, course, lesson, item["id"], user)).body == payload
    with pytest.raises(HTTPException):
        await assets.course_asset(db, course, uuid4(), item["id"], user)
    release.snapshot_sha256 = "0" * 64
    with pytest.raises(HTTPException):
        await assets.course_asset(db, course, lesson, item["id"], user)


@pytest.mark.asyncio
async def test_access_denials_do_not_expose_asset(monkeypatch):
    tenant, _, course, lesson, _, item, _ = fixture()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant, role="student", assignment_access_enrollment_id=uuid4())
    db = SimpleNamespace(scalars=AsyncMock())
    monkeypatch.setattr(assets, "require_course_access", AsyncMock(side_effect=HTTPException(409, "expired")))
    with pytest.raises(HTTPException) as error:
        await assets.course_asset(db, course, lesson, item["id"], user)
    assert error.value.status_code == 404
    db.scalars.assert_not_awaited()

    monkeypatch.setattr(assets, "require_course_access", AsyncMock())
    db.scalars.return_value = SimpleNamespace(all=lambda: [])
    with pytest.raises(HTTPException) as error:
        await assets.course_asset(db, course, lesson, item["id"], user)
    assert error.value.status_code == 404
    params = db.scalars.await_args.args[0].compile().params
    assert user.assignment_access_enrollment_id in params.values()


@pytest.mark.asyncio
async def test_historical_release_blocks_document_deletion():
    tenant, document, course, _, _, _, _ = fixture()
    empty = SimpleNamespace(all=lambda: [])
    historical = SimpleNamespace(all=lambda: [(course, "Old course", "published")])
    db = SimpleNamespace(execute=AsyncMock(side_effect=[empty, empty, historical, empty, empty, empty]))
    result = await list_document_usages(db, tenant, document)
    assert result.summary.total == 1 and result.summary.courses == 1
    assert result.items[0].type == "course_source" and result.items[0].id == str(course)

    db = SimpleNamespace(execute=AsyncMock(side_effect=[empty, empty, empty, historical, empty, empty]))
    assert (await list_document_usages(db, tenant, document)).summary.total == 1


def test_cleanup_only_accepts_owned_committed_storage_intents():
    tenant, document, _, _, _, item, _ = fixture()
    intent = SimpleNamespace(payload={"key": "source-asset-storage:" + item["sha256"],
                                      "result": {"sha256": item["sha256"], "storage_key": item["storage_key"]}})
    assert _source_asset_keys([intent, intent], tenant, document) == {item["storage_key"]}
    with pytest.raises(ValueError, match="storage_intent"):
        _source_asset_keys([intent], uuid4(), document)


@pytest.mark.asyncio
async def test_preview_requires_verified_manifest_for_original(monkeypatch):
    tenant, document, _, _, payload, item, _ = fixture()
    source_sha = "b" * 64
    block_id = "block-" + "1" * 24
    part_id = "part-" + digest(source_sha + block_id + block_id)[:24]
    manifest = {"original_blob_sha256": source_sha, "blocks": [{"id": block_id, "text": "text", "kind": "text"}],
                "parts": [{"id": part_id, "title": "A", "role": "learning", "reason": "A",
                           "first_block": block_id, "last_block": block_id}],
                "assets": [{**{k: item[k] for k in ("id", "sha256", "mime_type", "storage_key")},
                            "width": 1, "height": 1, "caption": "figure", "kind": "figure",
                            "text": "", "description": ""}]}
    package = PreparedSource.model_validate(manifest)
    event = SimpleNamespace(original_blob_sha256=source_sha, kind="analysis_block", payload={
        "key": f"source-preparation-v1:manifest:{source_sha}", "result": {"manifest": package.model_dump()}})
    monkeypatch.setattr(assets, "owned_document", AsyncMock(return_value=SimpleNamespace(content_sha256=source_sha)))
    monkeypatch.setattr(assets, "history", AsyncMock(return_value=[event]))
    monkeypatch.setattr(assets, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _: payload))
    assert (await assets.preview_asset(None, tenant, document, item["id"], package.sha256)).body == payload
    with pytest.raises(HTTPException):
        await assets.preview_asset(None, tenant, document, item["id"], "c" * 64)


@pytest.mark.asyncio
async def test_review_asset_requires_assigned_attempt_and_frozen_snapshot(monkeypatch):
    tenant, _, course, lesson, payload, item, snapshot = fixture()
    revision_id, attempt_id, reviewer_id = uuid4(), uuid4(), uuid4()
    sha = canonical_json_sha256(snapshot)
    attempt = SimpleNamespace(revision_id=revision_id, snapshot_sha256=sha)
    revision = SimpleNamespace(id=revision_id, course_id=course, snapshot=snapshot, snapshot_sha256=sha)
    user = SimpleNamespace(id=reviewer_id, tenant_id=tenant, review_revision_id=revision_id,
                           reviewer_email="reviewer@example.test")
    monkeypatch.setattr(assets, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _: payload))

    def database(assignment=True, outcome="pending"):
        return SimpleNamespace(scalar=AsyncMock(side_effect=[attempt, revision,
            object() if assignment else None, object(), SimpleNamespace(outcome=outcome)]))

    db = database()
    assert (await get_review_attempt_asset(attempt_id, lesson, item["id"], db, user)).body == payload
    query_params = [call.args[0].compile().params for call in db.scalar.await_args_list]
    assert reviewer_id in query_params[0].values() and tenant in query_params[0].values()
    assert "reviewer@example.test" in query_params[2].values()

    for db in (database(assignment=False), database(outcome="cancelled")):
        with pytest.raises(HTTPException) as error:
            await get_review_attempt_asset(attempt_id, lesson, item["id"], db, user)
        assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        await get_review_attempt_asset(attempt_id, uuid4(), item["id"], database(), user)
    user.review_revision_id = uuid4()
    with pytest.raises(HTTPException):
        await get_review_attempt_asset(attempt_id, lesson, item["id"], database(), user)
    user.review_revision_id = revision_id
    attempt.snapshot_sha256 = "0" * 64
    with pytest.raises(HTTPException):
        await get_review_attempt_asset(attempt_id, lesson, item["id"], database(), user)
