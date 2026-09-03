"""Database-backed tenant integrity checks for course approval actors."""

import pytest
from sqlalchemy.exc import IntegrityError

# Register the Enrollment mapper before flushing WorkflowWorkItem, whose
# optional enrollment_id foreign key is resolved by SQLAlchemy's metadata.
from app.models.enrollment import Enrollment  # noqa: F401


@pytest.mark.asyncio
async def test_runtime_role_rejects_cross_tenant_internal_actor_reference(
    db_session, make_tenant, make_user, make_course, set_current_tenant
):
    from app.modules.course_approval.models import CourseApprovalPolicy

    tenant_a = await make_tenant(name="Approval RLS A")
    tenant_b = await make_tenant(name="Approval RLS B")
    actor_a = await make_user(tenant_a, role="admin")
    actor_b = await make_user(tenant_b, role="admin")
    course_a = await make_course(tenant_a, actor_a)

    await set_current_tenant(tenant_a)
    db_session.add(CourseApprovalPolicy(tenant_id=tenant_a.id, course_id=course_a.id, updated_by=actor_b.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_runtime_role_rejects_cross_tenant_reviewer_recipient_reference(
    db_session, make_tenant, make_user, make_course, set_current_tenant
):
    from app.modules.course_approval.models import (
        CourseApprovalRevision,
        WorkflowDelivery,
        WorkflowWorkItem,
    )
    from app.modules.courses.release_service import canonical_json_sha256

    tenant_a = await make_tenant(name="Approval RLS C")
    tenant_b = await make_tenant(name="Approval RLS D")
    actor_a = await make_user(tenant_a, role="admin")
    recipient_b = await make_user(tenant_b, role="methodologist")
    course_a = await make_course(tenant_a, actor_a)
    snapshot = {"course": {"id": str(course_a.id)}, "modules": []}
    await set_current_tenant(tenant_a)
    revision = CourseApprovalRevision(
        tenant_id=tenant_a.id,
        course_id=course_a.id,
        revision_number=1,
        snapshot=snapshot,
        snapshot_sha256=canonical_json_sha256(snapshot),
        source_fingerprint=canonical_json_sha256(snapshot),
        created_by=actor_a.id,
    )
    db_session.add(revision)
    await db_session.flush()
    item = WorkflowWorkItem(tenant_id=tenant_a.id, kind="reviewer", review_revision_id=revision.id)
    db_session.add(item)
    await db_session.flush()
    db_session.add(WorkflowDelivery(tenant_id=tenant_a.id, work_item_id=item.id, channel="cabinet", recipient_user_id=recipient_b.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
