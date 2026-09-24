from __future__ import annotations

import inspect
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.learning_actions import router, service
from app.modules.learning_insights import service as insights_service

API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = API_ROOT / "alembic" / "versions" / "0163_learning_actions.py"


def test_action_routes_are_methodologist_only_and_expose_the_public_seams():
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in router.router.routes}
    assert ("/admin/learning-actions", ("GET",)) in routes
    assert ("/admin/learning-actions", ("POST",)) in routes
    assert ("/admin/learning-actions/{action_id}/close", ("POST",)) in routes
    assert 'require_role("methodologist")' in inspect.getsource(router)


def test_target_identity_is_exact_and_stable():
    enrollment_id = "d36a8f11-a60e-40d0-8505-1739c5df215c"
    assert service.enrollment_target_key(enrollment_id) == f"enrollment:{enrollment_id}"
    assert service.question_target_key(
        course_id="fa66d118-f43c-4da0-9a96-9ab186d6c969",
        quiz_id="31d6b68e-5116-4359-8db8-cb6601d954a6",
        content_release_id=None,
        question_id="aaec9a68-3765-4891-9cc1-d08e4db7fe2c",
        question_key="a" * 64,
    ) != service.question_target_key(
        course_id="fa66d118-f43c-4da0-9a96-9ab186d6c969",
        quiz_id="31d6b68e-5116-4359-8db8-cb6601d954a6",
        content_release_id="e84cb859-3951-478a-9f1c-46c8de3bf7e6",
        question_id="aaec9a68-3765-4891-9cc1-d08e4db7fe2c",
        question_key="a" * 64,
    )


def test_course_insights_query_excludes_predecessor_enrollment_attempts():
    statement = insights_service.build_course_attempt_statement(tenant_id=uuid4(), course_id=uuid4())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "quiz_attempts.enrollment_id = enrollments.id" in sql
    assert "previous_enrollment_id" in sql
    assert "NOT (EXISTS" in sql or "NOT EXISTS" in sql


def test_course_insights_empty_department_scope_remains_an_empty_cohort():
    statement = insights_service.build_course_attempt_statement(
        tenant_id=uuid4(),
        course_id=uuid4(),
        department_scope_ids=set(),
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "false" in sql.lower()


def test_migration_adds_tenant_rls_and_durable_append_only_actions():
    source = MIGRATION.read_text(encoding="utf-8").lower()
    assert re.search(r"revision\s*=\s*['\"]0163['\"]", source)
    assert re.search(r"down_revision\s*=\s*['\"]0162['\"]", source)
    assert "force row level security" in source
    assert "create policy" in source
    assert "learning_action_events" in source
    assert "grant select, insert on {events}" in source
    assert "learning_action_events.actor_id" in source
    assert "u.tenant_id=learning_action_events.tenant_id" in source
    assert "grant select, insert on {actions}" in source
    assert "grant update, delete on" not in source
    assert "grant update (status,resolution,resolution_note,outcome_snapshot,updated_at,closed_at)" in source
    assert "where status = 'open'" in source
    assert "target_key" in source
