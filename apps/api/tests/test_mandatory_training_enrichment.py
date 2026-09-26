from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.mandatory_training import service
from app.modules.mandatory_training.requirements import EffectiveRequirement


@pytest.mark.asyncio
async def test_training_log_enrichment_uses_same_reason_and_projection_contract(monkeypatch):
    tenant_id = uuid4()
    user_id = uuid4()
    position_id = uuid4()
    unit_id = uuid4()
    required_course_id = uuid4()
    manual_course_id = uuid4()
    required_enrollment_id = uuid4()
    manual_enrollment_id = uuid4()
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        position_id=position_id,
        organization_unit_id=unit_id,
    )
    scalar_result = SimpleNamespace(all=lambda: [user])
    db = SimpleNamespace(scalars=AsyncMock(return_value=scalar_result))

    async def requirements(_db, users):
        assert users == [user]

        def department_requirement(course_id):
            return EffectiveRequirement(
                course_id=course_id,
                source="department",
                source_ref_id=unit_id,
                scope_path=(unit_id,),
            )

        return {
            user_id: {
                required_course_id: department_requirement(required_course_id),
                manual_course_id: department_requirement(manual_course_id),
            }
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

    monkeypatch.setattr(service, "resolve_effective_requirements_for_users", requirements)
    monkeypatch.setattr(service, "load_source_names", source_names)
    rows = [
        {
            "user_id": user_id,
            "course_id": required_course_id,
            "enrollment_id": required_enrollment_id,
            "enrollment_source": "department",
            "enrollment_status": "enrolled",
        },
        {
            "user_id": user_id,
            "course_id": manual_course_id,
            "enrollment_id": manual_enrollment_id,
            "enrollment_source": "manual",
            "enrollment_status": "enrolled",
        },
    ]

    enriched = await service.enrich_training_log_rows(db, tenant_id, rows)

    required, manual = enriched
    assert required["requirement_state"] == "materialized"
    assert required["action_required"] == "none"
    assert required["assignment_reason"] == {
        "kind": "department",
        "source_ref_id": unit_id,
        "source_name": "Operations",
        "scope_path_ids": [unit_id],
        "scope_path_names": ["Operations"],
        "reason_code": "mandatory_training.reason.department",
    }
    assert manual["requirement_state"] == "protected_assignment"
    assert manual["assignment_reason"]["kind"] == "manual"
    assert manual["assignment_reason"]["source_ref_id"] is None
    assert manual["assignment_reason_kind"] == "manual"
    assert manual["assignment_reason_source_name"] is None
