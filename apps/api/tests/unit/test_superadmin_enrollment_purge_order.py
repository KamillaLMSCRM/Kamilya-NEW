"""Reproduce populated tenant FK failures through the actual service seam."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.admin.superadmin.router import delete_tenant
from app.modules.admin.superadmin.service import SuperadminService


class PopulatedTenantDb:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.enrollments = True
        self.children = {"assignment_access_credentials", "enrollment_access_policies",
                         "course_assignment_notification_outbox"}
        self.events = []
        self.get = AsyncMock(return_value=SimpleNamespace(
            id=tenant_id, name="Disposable", slug="disposable-purge", status="active", plan="free",
            trial_started_at=None, trial_ends_at=None, paid_until=None, max_users=3,
            max_courses_per_month=1, billing_contact_email=None, billing_company_name=None,
            billing_identifier=None, notes="synthetic", settings={}, created_at=None, updated_at=None,
        ))
        self.commit = AsyncMock(side_effect=lambda: self.events.append("commit"))

    async def execute(self, statement, params=None):
        sql = str(statement).strip()
        if "information_schema.columns" in sql:
            # Fixed catalog including existing and optional release children.
            names = {"quiz_choices", "questions", "content_blocks", "quiz_attempts", "quiz_assignments",
                     "certificates", "progress", "enrollments", "position_quizzes", "position_courses",
                     "department_courses", "position_jd_versions", "document_change_reviews",
                     "document_source_policies", "quizzes", "lessons", "modules", "courses", "documents",
                     "generated_content", "ai_jobs", "kiosk_links", "tenant_integrations_audit",
                     "tenant_integrations", "tenant_llm_usage", "tenant_settings", "provider_keys",
                     "user_sessions", "user_invitations", "user_roles", "workbench_assignment_plans",
                     "registration_legal_acceptances", "users", "departments", "tenant_usage", "tenant_leads",
                     "tenants"} | self.children
            return [(name, "tenant_id") for name in names]
        assert params["tenant_id"] == str(self.tenant_id)
        if "superadmin_purge_tenant_enrollment_access" in sql:
            assert params["confirm_slug"] == "disposable-purge"
            self.events.extend(sorted(self.children))
            self.children.clear()
        elif "superadmin_purge_tenant_content_releases" in sql:
            if self.enrollments:
                raise RuntimeError("fk_enrollments_content_release_id")
            self.events.append("release_purge")
        elif sql.startswith("DELETE FROM "):
            table = sql.split()[2]
            if table == "enrollments":
                if self.children:
                    raise RuntimeError("enrollment_child_fk")
                self.enrollments = False
            self.children.discard(table)
            self.events.append(table)
        return object()


@pytest.mark.asyncio
async def test_enrollment_children_and_enrollments_precede_release_purge():
    db = PopulatedTenantDb(uuid4())
    await SuperadminService(db).delete_tenant(db.tenant_id)
    for child in ("assignment_access_credentials", "enrollment_access_policies",
                  "course_assignment_notification_outbox", "quiz_attempts", "certificates", "progress"):
        assert db.events.index(child) < db.events.index("enrollments")
    assert db.events.index("enrollments") < db.events.index("release_purge") < db.events.index("courses")
    assert db.events[-2:] == ["tenants", "commit"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_dependency_failure_never_commits_service_transaction():
    db = PopulatedTenantDb(uuid4())
    original = db.execute

    async def fail(statement, params=None):
        if str(statement).strip().startswith("DELETE FROM enrollments "):
            raise RuntimeError("synthetic_dependency_failure")
        return await original(statement, params)

    db.execute = fail
    with pytest.raises(RuntimeError, match="synthetic_dependency_failure"):
        await SuperadminService(db).delete_tenant(db.tenant_id)
    db.commit.assert_not_awaited()
    assert "release_purge" not in db.events


@pytest.mark.asyncio
async def test_delete_error_rolls_back_without_exposing_database_exception():
    service = MagicMock()
    service.get_tenant = AsyncMock(return_value=SimpleNamespace(slug="disposable-purge"))
    service.delete_tenant = AsyncMock(side_effect=RuntimeError("sensitive_database_exception_sentinel"))
    service.db.rollback = AsyncMock()
    with pytest.raises(HTTPException) as caught:
        await delete_tenant(uuid4(), request=SimpleNamespace(client=None), confirm_slug="disposable-purge",
                            user=SimpleNamespace(id=uuid4()), svc=service)
    assert caught.value.status_code == 500
    assert caught.value.detail == "tenant_delete_failed"
    service.db.rollback.assert_awaited_once()
