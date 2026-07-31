"""Regression coverage for tenant context in direct test factories."""

import pytest
from sqlalchemy import text


async def _current_tenant_id(db_session) -> str:
    return await db_session.scalar(
        text("SELECT current_setting('app.tenant_id', true)")
    )


@pytest.mark.asyncio
async def test_tenant_scoped_factories_switch_context_before_each_flush(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_module,
    make_lesson,
    make_quiz,
    make_document,
):
    tenant_a = await make_tenant(name="Factory context A")
    tenant_b = await make_tenant(name="Factory context B")

    user_a = await make_user(tenant_a, role="methodologist")
    assert await _current_tenant_id(db_session) == str(tenant_a.id)

    user_b = await make_user(tenant_b, role="methodologist")
    assert await _current_tenant_id(db_session) == str(tenant_b.id)

    course_a = await make_course(tenant_a, user_a)
    assert await _current_tenant_id(db_session) == str(tenant_a.id)
    course_b = await make_course(tenant_b, user_b)
    assert await _current_tenant_id(db_session) == str(tenant_b.id)

    module_a = await make_module(course_a)
    assert await _current_tenant_id(db_session) == str(tenant_a.id)
    module_b = await make_module(course_b)
    assert await _current_tenant_id(db_session) == str(tenant_b.id)

    lesson_a = await make_lesson(module_a)
    assert await _current_tenant_id(db_session) == str(tenant_a.id)
    lesson_b = await make_lesson(module_b)
    assert await _current_tenant_id(db_session) == str(tenant_b.id)

    await make_quiz(lesson_a)
    assert await _current_tenant_id(db_session) == str(tenant_a.id)
    await make_quiz(lesson_b)
    assert await _current_tenant_id(db_session) == str(tenant_b.id)

    await make_document(tenant_a, user_a)
    assert await _current_tenant_id(db_session) == str(tenant_a.id)
    await make_document(tenant_b, user_b)
    assert await _current_tenant_id(db_session) == str(tenant_b.id)
