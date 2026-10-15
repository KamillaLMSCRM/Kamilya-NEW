"""Owned-schema DEV regression for Unicode resource resolution under C collation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from workbench_assignment_dev_gate import GateBlocked, context, safe_schema


async def verify_unicode_resolution(
    owner_engine,
    runtime_engine,
    schema: str,
    actor,
    course_id,
    department_id,
    learner_id,
    now: datetime,
) -> list[str]:
    """Exercise the real preview resolver against C-collated owned fixtures.

    DDL and fixture edits are restricted to the supplied disposable schema and
    exact tenant/IDs. Each preview transaction is rolled back; no confirmation
    or external call is made.
    """
    qualified = safe_schema(schema)
    tenant = str(actor.tenant_id)
    checks: list[str] = []
    original: dict[str, object] = {}

    async with owner_engine.begin() as connection:
        await context(connection, schema, actor.tenant_id, actor.actor_id)
        icu = (
            await connection.execute(
                text(
                    "SELECT collname, collprovider FROM pg_catalog.pg_collation "
                    "WHERE collname='und-x-icu' AND collprovider='i'"
                )
            )
        ).all()
        if len(icu) != 1:
            raise GateBlocked("icu_collation_missing_or_ambiguous")
        checks.append("und_x_icu_provider_present")

        rows = (
            await connection.execute(
                text(
                    f"SELECT title FROM {qualified}.courses "
                    "WHERE tenant_id=:tenant AND id=:course"
                ),
                {"tenant": tenant, "course": str(course_id)},
            )
        ).all()
        departments = (
            await connection.execute(
                text(
                    f"SELECT name FROM {qualified}.departments "
                    "WHERE tenant_id=:tenant AND id=:department"
                ),
                {"tenant": tenant, "department": str(department_id)},
            )
        ).all()
        learner = (
            await connection.execute(
                text(
                    f"SELECT status, organization_unit_id, position_id "
                    f"FROM {qualified}.users WHERE tenant_id=:tenant AND id=:learner"
                ),
                {"tenant": tenant, "learner": str(learner_id)},
            )
        ).all()
        if len(rows) != 1 or len(departments) != 1 or len(learner) != 1:
            raise GateBlocked("unicode_fixture_missing")
        original.update(
            title=rows[0][0],
            department_name=departments[0][0],
            learner_status=learner[0][0],
            learner_department=learner[0][1],
            learner_position=learner[0][2],
        )
        if original["learner_position"] is not None:
            position = (
                await connection.execute(
                    text(
                        f"SELECT department_id FROM {qualified}.positions "
                        "WHERE tenant_id=:tenant AND id=:position"
                    ),
                    {"tenant": tenant, "position": str(original["learner_position"])},
                )
            ).all()
            if len(position) != 1:
                raise GateBlocked("unicode_fixture_position_missing")
            original["position_department"] = position[0][0]

        await connection.execute(
            text(
                f'ALTER TABLE {qualified}.courses '
                'ALTER COLUMN title TYPE text COLLATE "C"'
            )
        )
        await connection.execute(
            text(
                f'ALTER TABLE {qualified}.departments '
                'ALTER COLUMN name TYPE text COLLATE "C"'
            )
        )
        await connection.execute(
            text(
                f"UPDATE {qualified}.courses SET title=:title "
                "WHERE tenant_id=:tenant AND id=:course"
            ),
            {
                "tenant": tenant,
                "course": str(course_id),
                "title": "ПРОВЕРКА НАЗНАЧЕНИЯ",
            },
        )
        await connection.execute(
            text(
                f"UPDATE {qualified}.departments SET name=:name "
                "WHERE tenant_id=:tenant AND id=:department"
            ),
            {
                "tenant": tenant,
                "department": str(department_id),
                "name": "ӘҚҢҒҰҮҺӨІ БӨЛІМІ",
            },
        )
        await connection.execute(
            text(
                f"UPDATE {qualified}.users SET status='active', organization_unit_id=:department "
                "WHERE tenant_id=:tenant AND id=:learner"
            ),
            {
                "tenant": tenant,
                "department": str(department_id),
                "learner": str(learner_id),
            },
        )
        if original["learner_position"] is not None:
            await connection.execute(
                text(
                    f"UPDATE {qualified}.positions SET department_id=:department "
                    "WHERE tenant_id=:tenant AND id=:position"
                ),
                {
                    "tenant": tenant,
                    "department": str(department_id),
                    "position": str(original["learner_position"]),
                },
            )
        collations = (
            await connection.execute(
                text(
                    "SELECT c.relname, a.attname, col.collname "
                    "FROM pg_catalog.pg_attribute a "
                    "JOIN pg_catalog.pg_class c ON c.oid=a.attrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_catalog.pg_collation col ON col.oid=a.attcollation "
                    "WHERE n.nspname=:schema AND c.relname IN ('courses','departments') "
                    "AND a.attname IN ('title','name') AND a.attnum > 0 "
                    "AND NOT a.attisdropped ORDER BY c.relname, a.attname"
                ),
                {"schema": schema},
            )
        ).all()
        if {(row[0], row[1], row[2]) for row in collations} != {
            ("courses", "title", "C"),
            ("departments", "name", "C"),
        }:
            raise GateBlocked("owned_fixture_columns_not_c_collated")
        checks.append("owned_course_department_columns_c_collated")

        for value in ("ПРОВЕРКА НАЗНАЧЕНИЯ", "ӘҚҢҒҰҮҺӨІ БӨЛІМІ"):
            result = (
                await connection.execute(
                    text(
                        'SELECT lower(CAST(:value AS text) COLLATE "C"), '
                        'lower(CAST(:value AS text) COLLATE "und-x-icu")'
                    ),
                    {"value": value},
                )
            ).one()
            if result[0] == value.lower() or result[1] != value.lower():
                raise GateBlocked("unicode_lower_probe_mismatch")
        checks.append("c_lower_differs_and_icu_lower_matches_python")

    try:
        from app.modules.methodologist_workbench.assignment_schemas import AssignmentPreviewRequest
        from app.modules.methodologist_workbench.assignment_service import create_assignment_preview
        from app.modules.methodologist_workbench.natural_assignment_intent import AssignmentCandidate

        variants = (
            ("проверка назначения", "әқңғұүһөі бөлімі"),
            ("Проверка Назначения", "Әқңғұүһөі Бөлімі"),
            ("  ПРОВЕРКА Назначения  ", "  әҚҢҒҰҮҺӨІ БӨЛІМІ  "),
            ("«ПРОВЕРКА Назначения»", '"ӘҚҢҒҰҮҺӨІ БӨЛІМІ"'),
        )
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            enrollment_before = await db.scalar(
                text(f"SELECT count(*) FROM {qualified}.enrollments WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            plan_before = await db.scalar(
                text(f"SELECT count(*) FROM {qualified}.workbench_assignment_plans WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            for variant_index, (course_query, department_query) in enumerate(variants):
                candidate = AssignmentCandidate(
                    course_query=course_query,
                    department_query=department_query,
                    due_date=now.date().isoformat(),
                    due_time="23:59:59",
                )
                # DTO construction intentionally strips outer whitespace. The
                # service must preserve that validated DTO, not pre-validation input.
                before_candidate = candidate.model_dump()
                request = AssignmentPreviewRequest(
                    instruction="unicode C-collation preview",
                    timezone_name="UTC",
                    candidate=candidate,
                    course_id=course_id,
                    department_id=department_id,
                    notify=False,
                )
                result = await create_assignment_preview(db, actor, request, now=now)
                if (
                    result.state != "preview_ready"
                    or result.course_id != course_id
                    or result.department_id != department_id
                    or candidate.model_dump() != before_candidate
                ):
                    await db.rollback()
                    code = getattr(result, "code", "identity_or_candidate_mismatch")
                    raise GateBlocked(f"unicode_preview_{variant_index}_{result.state}_{code}")
                await db.rollback()
                await context(db, schema, actor.tenant_id, actor.actor_id)
            enrollment_after = await db.scalar(
                text(f"SELECT count(*) FROM {qualified}.enrollments WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            plan_after = await db.scalar(
                text(f"SELECT count(*) FROM {qualified}.workbench_assignment_plans WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            if enrollment_before != enrollment_after or plan_before != plan_after:
                raise GateBlocked("unicode_preview_left_rows")
        checks.append("unicode_case_space_quote_variants_resolve_exact_ids")
        checks.append("unicode_preview_rollback_preserves_enrollments_and_plans")
    finally:
        async with owner_engine.begin() as connection:
            await context(connection, schema, actor.tenant_id, actor.actor_id)
            await connection.execute(
                text(
                    f"UPDATE {qualified}.courses SET title=:title "
                    "WHERE tenant_id=:tenant AND id=:course"
                ),
                {"tenant": tenant, "course": str(course_id), "title": original["title"]},
            )
            await connection.execute(
                text(
                    f"UPDATE {qualified}.departments SET name=:name "
                    "WHERE tenant_id=:tenant AND id=:department"
                ),
                {"tenant": tenant, "department": str(department_id), "name": original["department_name"]},
            )
            await connection.execute(
                text(
                    f"UPDATE {qualified}.users SET status=:status, organization_unit_id=:department "
                    "WHERE tenant_id=:tenant AND id=:learner"
                ),
                {
                    "tenant": tenant,
                    "status": original["learner_status"],
                    "department": original["learner_department"],
                    "learner": str(learner_id),
                },
            )
            if original["learner_position"] is not None:
                await connection.execute(
                    text(
                        f"UPDATE {qualified}.positions SET department_id=:department "
                        "WHERE tenant_id=:tenant AND id=:position"
                    ),
                    {
                        "tenant": tenant,
                        "department": original["position_department"],
                        "position": str(original["learner_position"]),
                    },
                )

    return checks
