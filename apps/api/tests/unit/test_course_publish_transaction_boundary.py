"""Transaction-boundary regressions for course publication."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.courses.models import Course
from app.modules.courses.router import canonical_json_sha256, publish_course, unpublish_course
from app.modules.courses.schemas import CourseResponse

NOW = datetime(2026, 10, 4, 10, tzinfo=UTC)


def uid(number: int) -> UUID:
    return UUID(int=number)


def _course(*, tenant_id: UUID, status: str = "draft") -> Course:
    return Course(
        id=uid(10),
        tenant_id=tenant_id,
        title="Atomic publication",
        description="Published course",
        status=status,
        delivery_type="native",
        ai_generated=False,
        source_document_ids=[],
        source_strategy="single_topic",
        source_analysis={},
        review_status="approved",
        created_at=NOW,
        updated_at=NOW,
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "unit-test"})


class _Result:
    def __init__(self, value: Course):
        self.value = value

    def scalar_one_or_none(self) -> Course:
        return self.value


class _TransactionLocalDB:
    """Minimal async-session double that rejects all access after commit."""

    def __init__(
        self,
        course: Course,
        scalars: list[object],
        *,
        nested_error: BaseException | None = None,
        commit_error: BaseException | None = None,
    ) -> None:
        self.course = course
        self.scalars = list(scalars)
        self.committed = False
        self.commit_count = 0
        self.in_nested = False
        self.nested_error = nested_error
        self.commit_error = commit_error
        self.execute = AsyncMock(side_effect=self._execute)
        self.scalar = AsyncMock(side_effect=self._scalar)
        self.flush = AsyncMock(side_effect=self._flush)
        self.refresh = AsyncMock(side_effect=self._check)
        self.add = Mock(side_effect=self._check)

    def _check(self, *_args: object, **_kwargs: object) -> None:
        if self.committed:
            raise AssertionError("database access after commit")

    async def _execute(self, *_args: object, **_kwargs: object) -> _Result:
        self._check()
        return _Result(self.course)

    async def _flush(self, *_args: object, **_kwargs: object) -> None:
        self._check()
        if self.in_nested and self.nested_error is not None:
            raise self.nested_error

    async def _scalar(self, *_args: object, **_kwargs: object) -> object:
        self._check()
        return self.scalars.pop(0) if self.scalars else None

    async def commit(self) -> None:
        self._check()
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True
        self.commit_count += 1

    async def rollback(self) -> None:
        self.committed = False

    def begin_nested(self) -> _Savepoint:
        self._check()
        return _Savepoint(self)


class _Savepoint:
    def __init__(self, db: _TransactionLocalDB) -> None:
        self.db = db

    async def __aenter__(self) -> _Savepoint:
        self.db._check()
        self.db.in_nested = True
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        self.db.in_nested = False
        return False


def _release() -> SimpleNamespace:
    return SimpleNamespace(id=uid(20), version=1, snapshot_sha256="a" * 64, published_at=NOW)


def _patch_publication(release: object):
    return patch.multiple(
        "app.modules.courses.router",
        activate_course_assignments=AsyncMock(),
        log_action=AsyncMock(),
    ), patch("app.modules.courses.release_service.create_course_release", new=AsyncMock(return_value=release))


@pytest.mark.asyncio
async def test_keyed_success_keeps_idempotency_and_publication_in_one_commit() -> None:
    tenant_id, user_id = uid(2), uid(3)
    course = _course(tenant_id=tenant_id)
    db = _TransactionLocalDB(course, [None, None, None])
    release = _release()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="methodologist")
    with (
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
        patch("app.modules.courses.router.activate_course_assignments", new=AsyncMock()),
        patch("app.modules.courses.router.log_action", new=AsyncMock()),
        patch("app.modules.courses.release_service.create_course_release", new=AsyncMock(return_value=release)),
    ):
        result = await publish_course(course.id, request=_request(), db=db, user=user, idempotency_key="publish-1")

    assert db.commit_count == 1
    assert course.status == "published"
    assert result.id == course.id
    assert CourseResponse.model_validate(result, from_attributes=True).status == "published"


@pytest.mark.asyncio
async def test_unkeyed_success_commits_once_and_returns_shape_before_session_expiry() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id)
    db = _TransactionLocalDB(course, [None, None, None])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with (
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
        patch("app.modules.courses.router.activate_course_assignments", new=AsyncMock()),
        patch("app.modules.courses.router.log_action", new=AsyncMock()),
        patch("app.modules.courses.release_service.create_course_release", new=AsyncMock(return_value=_release())),
    ):
        result = await publish_course(course.id, request=_request(), db=db, user=user)

    assert db.commit_count == 1
    assert CourseResponse.model_validate(result, from_attributes=True).id == course.id


@pytest.mark.asyncio
async def test_matching_replay_does_not_republish_or_commit() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    key = "publish-replay"
    prior = SimpleNamespace(request_fingerprint=canonical_json_sha256({"course_id": str(course.id)}))
    db = _TransactionLocalDB(course, [prior, course])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")
    hydrate = AsyncMock(return_value=None)

    with patch("app.modules.courses.router._hydrate_reviewer", new=hydrate):
        result = await publish_course(course.id, request=_request(), db=db, user=user, idempotency_key=key)

    assert CourseResponse.model_validate(result, from_attributes=True).id == course.id
    assert db.commit_count == 0
    db.execute.assert_not_awaited()
    hydrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_mismatch_is_409_before_publication() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id)
    prior = SimpleNamespace(request_fingerprint="different")
    db = _TransactionLocalDB(course, [prior])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with pytest.raises(HTTPException) as exc:
        await publish_course(course.id, request=_request(), db=db, user=user, idempotency_key="publish-1")

    assert exc.value.status_code == 409
    assert exc.value.detail == "idempotency_conflict"
    assert db.commit_count == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_locked_already_published_matching_key_returns_replay_without_new_release() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    prior = SimpleNamespace(request_fingerprint=canonical_json_sha256({"course_id": str(course.id)}))
    db = _TransactionLocalDB(course, [None, prior])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")
    release_factory = AsyncMock(return_value=_release())

    with (
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
        patch("app.modules.courses.release_service.create_course_release", new=release_factory),
    ):
        result = await publish_course(course.id, request=_request(), db=db, user=user, idempotency_key="race-key")

    assert CourseResponse.model_validate(result, from_attributes=True).status == "published"
    assert db.commit_count == 0
    release_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_savepoint_idempotency_conflict_returns_409_without_publication_commit() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id)
    duplicate = IntegrityError("insert", {}, Exception("duplicate key"))
    db = _TransactionLocalDB(course, [None, None, None], nested_error=duplicate)
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with (
        patch("app.modules.courses.router.activate_course_assignments", new=AsyncMock()),
        patch("app.modules.courses.router.log_action", new=AsyncMock()),
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
        patch("app.modules.courses.release_service.create_course_release", new=AsyncMock(return_value=_release())),
    ):
        with pytest.raises(HTTPException) as exc:
            await publish_course(course.id, request=_request(), db=db, user=user, idempotency_key="duplicate-key")

    assert exc.value.status_code == 409
    assert exc.value.detail == "idempotency_conflict"
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_commit_failure_does_not_return_success_dto() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id)
    db = _TransactionLocalDB(course, [None, None, None], commit_error=RuntimeError("commit failed"))
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with (
        patch("app.modules.courses.router.activate_course_assignments", new=AsyncMock()),
        patch("app.modules.courses.router.log_action", new=AsyncMock()),
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
        patch("app.modules.courses.release_service.create_course_release", new=AsyncMock(return_value=_release())),
    ):
        with pytest.raises(RuntimeError, match="commit failed"):
            await publish_course(course.id, request=_request(), db=db, user=user)

    assert db.commit_count == 0


def _unpublish_patches():
    return (
        patch("app.modules.courses.router.refresh_course_assignments", new=AsyncMock()),
        patch("app.modules.courses.router.log_action", new=AsyncMock()),
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
    )


@pytest.mark.asyncio
async def test_unpublish_locked_matching_replay_skips_refresh_and_audit() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="draft")
    prior = SimpleNamespace(request_fingerprint=canonical_json_sha256({"course_id": str(course.id)}))
    db = _TransactionLocalDB(course, [None, prior])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")
    refresh, audit = AsyncMock(), AsyncMock()
    with (
        patch("app.modules.courses.router.refresh_course_assignments", new=refresh),
        patch("app.modules.courses.router.log_action", new=audit),
        patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)),
    ):
        result = await unpublish_course(course.id, request=_request(), db=db, user=user, idempotency_key="race-key")
    assert result.status == "draft"
    assert db.commit_count == 0
    refresh.assert_not_awaited()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unpublish_keyed_success_keeps_replay_row_and_publication_in_one_commit() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    db = _TransactionLocalDB(course, [None])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with _unpublish_patches()[0], _unpublish_patches()[1], _unpublish_patches()[2]:
        result = await unpublish_course(course.id, request=_request(), db=db, user=user, idempotency_key="unpublish-1")

    assert db.commit_count == 1
    assert CourseResponse.model_validate(result, from_attributes=True).status == "draft"


@pytest.mark.asyncio
async def test_unpublish_unkeyed_success_commits_once_and_returns_dto() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    db = _TransactionLocalDB(course, [])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with _unpublish_patches()[0], _unpublish_patches()[1], _unpublish_patches()[2]:
        result = await unpublish_course(course.id, request=_request(), db=db, user=user)

    assert db.commit_count == 1
    assert CourseResponse.model_validate(result, from_attributes=True).id == course.id


@pytest.mark.asyncio
async def test_unpublish_matching_replay_does_not_commit_or_repeat_mutation() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="draft")
    prior = SimpleNamespace(request_fingerprint=canonical_json_sha256({"course_id": str(course.id)}))
    db = _TransactionLocalDB(course, [prior, course])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with patch("app.modules.courses.router._hydrate_reviewer", new=AsyncMock(return_value=None)):
        result = await unpublish_course(course.id, request=_request(), db=db, user=user, idempotency_key="unpublish-1")

    assert db.commit_count == 0
    assert CourseResponse.model_validate(result, from_attributes=True).status == "draft"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unpublish_mismatched_key_is_409_before_mutation() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    db = _TransactionLocalDB(course, [SimpleNamespace(request_fingerprint="different")])
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with pytest.raises(HTTPException) as exc:
        await unpublish_course(course.id, request=_request(), db=db, user=user, idempotency_key="unpublish-1")

    assert exc.value.status_code == 409
    assert db.commit_count == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unpublish_savepoint_conflict_is_409_without_commit() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    duplicate = IntegrityError("insert", {}, Exception("duplicate key"))
    db = _TransactionLocalDB(course, [None], nested_error=duplicate)
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with _unpublish_patches()[0], _unpublish_patches()[1], _unpublish_patches()[2]:
        with pytest.raises(HTTPException) as exc:
            await unpublish_course(course.id, request=_request(), db=db, user=user, idempotency_key="duplicate-key")

    assert exc.value.status_code == 409
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_unpublish_commit_failure_does_not_return_success_dto() -> None:
    tenant_id = uid(2)
    course = _course(tenant_id=tenant_id, status="published")
    db = _TransactionLocalDB(course, [], commit_error=RuntimeError("commit failed"))
    user = SimpleNamespace(id=uid(3), tenant_id=tenant_id, role="methodologist")

    with _unpublish_patches()[0], _unpublish_patches()[1], _unpublish_patches()[2]:
        with pytest.raises(RuntimeError, match="commit failed"):
            await unpublish_course(course.id, request=_request(), db=db, user=user)

    assert db.commit_count == 0
