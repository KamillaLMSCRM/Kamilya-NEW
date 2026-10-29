from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.course_approval.service import decide
from app.modules.courses.router import publish_course, review_course
from app.modules.courses.schemas import CourseReviewRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["manual", "publish", "revision"])
@pytest.mark.parametrize("flag_enabled", [True, False])
async def test_marker_blocks_qa_tenant_on_real_endpoint(monkeypatch, operation, flag_enabled):
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(DEPLOYMENT_ENVIRONMENT="render-development")
    )
    monkeypatch.setattr("app.modules.courses.source_uncertainty.qa_source_holds_enabled", lambda tenant: flag_enabled)
    tenant, course_id = QA_TENANT, uuid4()
    course = SimpleNamespace(
        id=course_id, tenant_id=tenant, status="draft", source_analysis={"unresolved_source_uncertainty": {}}
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: course)),
        scalar=AsyncMock(return_value=course),
        commit=AsyncMock(),
        flush=AsyncMock(),
    )
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant)
    with pytest.raises(HTTPException) as e:
        if operation == "manual":
            await review_course(course_id, CourseReviewRequest(review_status="approved"), None, db, user)
        elif operation == "publish":
            await publish_course(course_id, request=None, db=db, user=user)
        else:
            await decide(
                db,
                attempt=SimpleNamespace(),
                revision=SimpleNamespace(course_id=course_id),
                reviewer=SimpleNamespace(),
                tenant_id=tenant,
                actor_id=user.id,
                decision="approve",
                reason=None,
                warning_acknowledged=False,
            )
    assert e.value.status_code == 409
    db.commit.assert_not_awaited()
    db.flush.assert_not_awaited()


def test_persisted_marker_guard_is_dev_qa_only_and_independent_of_feature_flag(monkeypatch):
    from app.modules.courses.source_uncertainty import is_qa_source_tenant

    settings = SimpleNamespace(DEPLOYMENT_ENVIRONMENT="render-development", AI_QA_LUNA_DEV_ENABLED=False)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    assert is_qa_source_tenant(QA_TENANT)
    assert not is_qa_source_tenant(uuid4())
    settings.DEPLOYMENT_ENVIRONMENT = "production"
    assert not is_qa_source_tenant(QA_TENANT)
