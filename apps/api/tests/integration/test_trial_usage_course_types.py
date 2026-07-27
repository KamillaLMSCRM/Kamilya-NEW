from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_trial_usage_keeps_regular_and_instruction_courses_separate(
    db_session,
    make_tenant,
    make_user,
    make_course,
    make_document,
):
    from app.core.trial_limits import count_ai_courses
    from app.models.tenants import TenantUsage
    from app.modules.admin.service import get_trial_usage

    tenant = await make_tenant(
        name="Trial usage",
        slug="trial-usage-course-types",
        status="trial",
        plan="trial",
        settings={
            "trial_limits": {
                "ai_course_generations_limit": 1,
                "jd_course_generations_limit": 1,
                "max_students": 10,
                "system_users_limit": 3,
            }
        },
    )
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@trial-usage.example",
    )
    await make_course(
        tenant,
        methodologist,
        title="Regular AI course",
        ai_generated=True,
    )
    instruction = await make_document(
        tenant,
        methodologist,
        name="instruction.txt",
        category="job_instruction",
    )
    instruction_course = await make_course(
        tenant,
        methodologist,
        title="Instruction course",
        ai_generated=True,
    )
    instruction_course.source_instruction_id = instruction.id
    db_session.add(
        TenantUsage(
            tenant_id=tenant.id,
            ai_course_generations_used=1,
            jd_course_generations_used=1,
            system_users_count_snapshot=1,
        )
    )
    await db_session.flush()

    assert await count_ai_courses(db_session, tenant.id) == 1
    usage = await get_trial_usage(db_session, tenant.id)
    assert usage["ai_courses"] == {"used": 1, "limit": 1, "remaining": 0}
    assert usage["jd_courses"] == {"used": 1, "limit": 1, "remaining": 0}
