from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.announcements.router import _recipient_query


def _compiled(query):
    return query.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"render_postcompile": True},
    )


def test_tenant_wide_recipients_do_not_require_enrollment():
    tenant_id = uuid4()

    compiled = _compiled(_recipient_query(tenant_id, None))
    sql = str(compiled)

    assert "JOIN enrollments" not in sql
    assert "users.tenant_id" in sql
    assert "users.is_active IS true" in sql
    assert "users.status" in sql
    assert "users.email IS NOT NULL" in sql
    assert tenant_id in compiled.params.values()


def test_course_recipients_require_same_tenant_enrollment():
    tenant_id = uuid4()
    course_id = uuid4()

    compiled = _compiled(_recipient_query(tenant_id, course_id))
    sql = str(compiled)

    assert "JOIN enrollments" in sql
    assert "enrollments.user_id = users.id" in sql
    assert "enrollments.tenant_id" in sql
    assert "enrollments.course_id" in sql
    assert tenant_id in compiled.params.values()
    assert course_id in compiled.params.values()
