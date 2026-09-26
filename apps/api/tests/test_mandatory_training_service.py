from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.mandatory_training import service
from app.modules.mandatory_training.repository import CourseContext, EmployeeContext
from app.modules.mandatory_training.requirements import (
    EffectiveRequirement,
    EnrollmentAssignment,
)
from app.modules.mandatory_training.schemas import MandatoryTrainingFilter


def _employee(*, tenant_id, unit_id, position_id, first_name, last_name):
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        personnel_number=f"PN-{first_name}",
        is_active=True,
        position_id=position_id,
    )
    return EmployeeContext(
        user=user,
        position_name="Specialist",
        organization_unit_id=unit_id,
        organization_unit_path_ids=(unit_id,),
        organization_unit_path_names=("Operations",),
    )


@pytest.mark.asyncio
async def test_matrix_and_summary_share_explainable_expected_vs_actual_rows(monkeypatch):
    tenant_id = uuid4()
    unit_id = uuid4()
    position_id = uuid4()
    required_course_id = uuid4()
    manual_course_id = uuid4()
    manual_enrollment_id = uuid4()
    employee = _employee(
        tenant_id=tenant_id,
        unit_id=unit_id,
        position_id=position_id,
        first_name="Aida",
        last_name="Sadykova",
    )
    filters = MandatoryTrainingFilter()

    async def employee_contexts(_db, actual_tenant_id, actual_filters, *, max_users):
        assert actual_tenant_id == tenant_id
        assert actual_filters is filters
        assert max_users == service.MAX_SCOPE_USERS
        return [employee]

    async def requirements(_db, users):
        assert users == [employee.user]
        return {
            employee.user.id: {
                required_course_id: EffectiveRequirement(
                    course_id=required_course_id,
                    source="department",
                    source_ref_id=unit_id,
                    scope_path=(unit_id,),
                ),
                manual_course_id: EffectiveRequirement(
                    course_id=manual_course_id,
                    source="department",
                    source_ref_id=unit_id,
                    scope_path=(unit_id,),
                ),
            }
        }

    async def enrollments(_db, actual_tenant_id, user_ids):
        assert actual_tenant_id == tenant_id
        assert list(user_ids) == [employee.user.id]
        return {
            employee.user.id: [
                EnrollmentAssignment(
                    enrollment_id=manual_enrollment_id,
                    course_id=manual_course_id,
                    source="manual",
                    status="enrolled",
                )
            ]
        }

    async def courses(_db, actual_tenant_id, course_ids):
        assert actual_tenant_id == tenant_id
        assert set(course_ids) == {required_course_id, manual_course_id}
        return {
            required_course_id: CourseContext(title="Safety", delivery_type="native"),
            manual_course_id: CourseContext(title="Mentoring", delivery_type="scorm"),
        }

    async def source_names(
        _db,
        actual_tenant_id,
        *,
        position_ids,
        unit_ids,
    ):
        assert actual_tenant_id == tenant_id
        assert set(position_ids) == set()
        assert set(unit_ids) == {unit_id}
        return {}, {unit_id: "Operations"}

    async def operational_rows(_db, actual_tenant_id, enrollment_ids):
        assert actual_tenant_id == tenant_id
        assert tuple(enrollment_ids) == (manual_enrollment_id,)
        return {
            manual_enrollment_id: {
                "progress_percent": 40,
                "computed_status": "in_progress",
                "assignment_due_at": None,
                "deadline_state": "none",
                "deadline_status": "not_applicable",
                "certificate_status": "none",
                "latest_evidence_event_id": None,
                "evidence_confirmation_status": "pending",
                "evidence_signed_copy_status": "awaiting_return",
                "evidence_state": "forming",
            }
        }

    monkeypatch.setattr(service, "list_employee_contexts", employee_contexts)
    monkeypatch.setattr(service, "resolve_effective_requirements_for_users", requirements)
    monkeypatch.setattr(service, "list_current_enrollments", enrollments)
    monkeypatch.setattr(service, "load_course_contexts", courses)
    monkeypatch.setattr(service, "load_source_names", source_names)
    monkeypatch.setattr(service, "list_training_log_by_enrollment_ids", operational_rows)

    page = await service.get_mandatory_training_page(
        object(),
        tenant_id,
        filters,
        limit=50,
        offset=0,
    )
    summary = await service.get_mandatory_training_summary(object(), tenant_id, filters)

    assert page.total == 2
    rows = {row.course_id: row for row in page.items}
    required = rows[required_course_id]
    assert required.requirement_state == "missing_enrollment"
    assert required.action_required == "materialize"
    assert required.progress_percent is None
    assert required.deadline_state is None
    assert required.evidence_state is None
    assert required.assignment_reason.model_dump() == {
        "kind": "department",
        "source_ref_id": unit_id,
        "source_name": "Operations",
        "scope_path_ids": [unit_id],
        "scope_path_names": ["Operations"],
        "reason_code": "mandatory_training.reason.department",
    }
    assert rows[manual_course_id].requirement_state == "protected_assignment"
    assert rows[manual_course_id].assignment_reason.kind == "manual"
    assert rows[manual_course_id].assignment_reason.source_ref_id is None
    assert rows[manual_course_id].assignment_reason.source_name is None
    assert rows[manual_course_id].assignment_reason.scope_path_ids == []
    assert rows[manual_course_id].progress_percent == 40
    assert rows[manual_course_id].computed_status == "in_progress"
    assert rows[manual_course_id].deadline_state == "none"
    assert rows[manual_course_id].evidence_confirmation_status == "pending"
    assert rows[manual_course_id].evidence_state == "forming"
    assert summary.model_dump() == {
        "total": 2,
        "materialized": 0,
        "missing_enrollment": 1,
        "protected_assignment": 1,
        "stale_managed_enrollment": 0,
        "action_materialize": 1,
        "action_review_stale": 0,
    }


@pytest.mark.asyncio
async def test_matrix_filters_before_pagination_and_clamps_page_bounds(monkeypatch):
    tenant_id = uuid4()
    unit_id = uuid4()
    position_id = uuid4()
    course_ids = [uuid4(), uuid4()]
    employee = _employee(
        tenant_id=tenant_id,
        unit_id=unit_id,
        position_id=position_id,
        first_name="Baur",
        last_name="Amanov",
    )

    monkeypatch.setattr(
        service,
        "list_employee_contexts",
        lambda *_args, **_kwargs: pytest.fail("async adapter must be awaited"),
    )

    async def employee_contexts(*_args, **_kwargs):
        return [employee]

    async def requirements(*_args, **_kwargs):
        return {
            employee.user.id: {
                course_id: EffectiveRequirement(
                    course_id=course_id,
                    source="organization",
                    source_ref_id=uuid4(),
                )
                for course_id in course_ids
            }
        }

    async def enrollments(*_args, **_kwargs):
        return {}

    async def courses(*_args, **_kwargs):
        return {
            course_id: CourseContext(title=f"Course {index}", delivery_type="native")
            for index, course_id in enumerate(course_ids)
        }

    async def source_names(*_args, **_kwargs):
        return {}, {}

    monkeypatch.setattr(service, "list_employee_contexts", employee_contexts)
    monkeypatch.setattr(service, "resolve_effective_requirements_for_users", requirements)
    monkeypatch.setattr(service, "list_current_enrollments", enrollments)
    monkeypatch.setattr(service, "load_course_contexts", courses)
    monkeypatch.setattr(service, "load_source_names", source_names)

    page = await service.get_mandatory_training_page(
        object(),
        tenant_id,
        MandatoryTrainingFilter(action_required="materialize"),
        limit=0,
        offset=-5,
    )

    assert page.total == 2
    assert page.limit == 1
    assert page.offset == 0
    assert len(page.items) == 1
    assert page.items[0].assignment_reason.kind == "organization"
    assert page.items[0].assignment_reason.source_name is None
