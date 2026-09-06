"""Real RLS/API checks; invoked by the isolated DEV gate, never public fixtures."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


async def exercise_document_regression(owner, checks):
    """Run the exact required document-worker journey assertion on synthetic DEV data.

    Storage/ingestion are intentionally stubbed by the existing test; this is not
    provider document-to-course smoke evidence.
    """
    import importlib.util
    from pathlib import Path

    from pytest import MonkeyPatch

    test_root = Path(__file__).resolve().parents[1]

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    fixtures = load("insights_regression_fixtures", test_root / "conftest.py")
    tests = load("insights_document_regression", test_root / "integration/test_document_operations.py")
    async with AsyncSession(owner, expire_on_commit=False) as db:
        with MonkeyPatch.context() as monkeypatch:
            set_tenant = fixtures.set_current_tenant.__wrapped__(db)
            await tests.test_document_reindex_worker_completes_and_is_idempotent(
                db,
                monkeypatch,
                fixtures.make_tenant.__wrapped__(db),
                fixtures.make_user.__wrapped__(db, set_tenant),
                fixtures.make_document.__wrapped__(db, set_tenant),
            )
    checks.append("ai_course_01_document_reindex_worker_exact_regression")


async def exercise(owner, runtime, schema, checks):
    from app.core.auth import get_current_user
    from app.core.db import get_db
    from app.models.enrollment import Enrollment
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from app.modules.courses.release_service import canonical_json_sha256
    from app.modules.learning_insights.router import router
    from app.modules.lessons.models import Lesson, Module
    from app.modules.quizzes.models import Quiz, QuizAttempt

    ids = {
        key: uuid4()
        for key in (
            "tenant",
            "foreign_tenant",
            "methodologist",
            "foreign_user",
            "user1",
            "user2",
            "course",
            "foreign_course",
            "module",
            "lesson",
            "quiz",
            "release",
            "question",
            "correct",
            "wrong",
            "enrollment1",
            "enrollment2",
            "foreign_enrollment",
        )
    }
    now = datetime(2026, 9, 1, 10, tzinfo=UTC)
    question = {
        "id": str(ids["question"]),
        "text": "Synthetic safety question",
        "type": "mcq",
        "points": 1,
        "explanation": "Synthetic explanation",
        "order_index": 0,
        "choices": [
            {"id": str(ids["correct"]), "text": "Check first", "is_correct": True, "order_index": 0},
            {"id": str(ids["wrong"]), "text": "Skip check", "is_correct": False, "order_index": 1},
        ],
    }
    release_snapshot = {
        "modules": [
            {
                "id": str(ids["module"]),
                "lessons": [
                    {
                        "id": str(ids["lesson"]),
                        "quizzes": [{"id": str(ids["quiz"]), "title": "Synthetic quiz", "questions": [question]}],
                    }
                ],
            }
        ]
    }
    release_hash = canonical_json_sha256(release_snapshot)
    attempt_rows = []
    for number, (learner, enrollment, correct) in enumerate(
        (
            ("user1", "enrollment1", False),
            ("user2", "enrollment2", False),
            ("user1", "enrollment1", True),
        )
    ):
        attempt_id = uuid4()
        completed = now + timedelta(hours=number)
        row = dict(
            id=attempt_id,
            tenant_id=ids["tenant"],
            user_id=ids[learner],
            enrollment_id=ids[enrollment],
            quiz_id=ids["quiz"],
            content_release_id=ids["release"],
            started_at=completed - timedelta(seconds=60),
            completed_at=completed,
            time_spent_seconds=60,
            score_percent=100 if correct else 0,
            total_points=1,
            earned_points=int(correct),
            passed=correct,
            answers=[
                {
                    "question_id": str(ids["question"]),
                    "selected_choice_ids": [str(ids["correct" if correct else "wrong"])],
                }
            ],
        )
        attempt_evidence = {
            key: (str(value) if key.endswith("id") else value.isoformat() if isinstance(value, datetime) else value)
            for key, value in row.items()
            if key != "answers"
        }
        attempt_evidence.update(course_id=str(ids["course"]), content_release_sha256=release_hash)
        snapshot = {
            "schema_version": 1,
            "attempt": attempt_evidence,
            "quiz": {
                "id": str(ids["quiz"]),
                "title": "Synthetic quiz",
                "pass_score": 80,
                "time_limit": None,
                "attempt_limit": 3,
                "deferral_days": 7,
                "questions": [question],
            },
            "graded_answers": [
                {
                    "question_id": str(ids["question"]),
                    "selected_choice_ids": [str(ids["correct" if correct else "wrong"])],
                    "correct_choice_ids": [str(ids["correct"])],
                    "is_correct": correct,
                    "points_earned": int(correct),
                    "points_possible": 1,
                }
            ],
        }
        row.update(evidence_snapshot=snapshot, evidence_sha256=canonical_json_sha256(snapshot))
        attempt_rows.append(row)

    async with owner.begin() as conn:
        assert (await conn.execute(text("SELECT current_schema()"))).scalar_one() == schema, "owner_schema_binding"
        for key in ("tenant", "foreign_tenant"):
            await conn.execute(
                insert(Tenant.__table__).values(
                    id=ids[key], name="Synthetic insights QA", slug=key + ids[key].hex, status="active"
                )
            )
        for key in ("methodologist", "foreign_user", "user1", "user2"):
            await conn.execute(
                insert(User.__table__).values(
                    id=ids[key],
                    tenant_id=ids["foreign_tenant" if key == "foreign_user" else "tenant"],
                    first_name="Synthetic",
                    last_name=key,
                    role="methodologist" if key == "methodologist" else "student",
                )
            )
        for key in ("course", "foreign_course"):
            await conn.execute(
                insert(Course.__table__).values(
                    id=ids[key],
                    tenant_id=ids["foreign_tenant" if key == "foreign_course" else "tenant"],
                    title="Synthetic course",
                )
            )
        await conn.execute(
            insert(Module.__table__).values(
                id=ids["module"], tenant_id=ids["tenant"], course_id=ids["course"], title="Synthetic module"
            )
        )
        await conn.execute(
            insert(Lesson.__table__).values(
                id=ids["lesson"], tenant_id=ids["tenant"], module_id=ids["module"], title="Synthetic lesson"
            )
        )
        await conn.execute(
            insert(Quiz.__table__).values(
                id=ids["quiz"], tenant_id=ids["tenant"], lesson_id=ids["lesson"], title="Synthetic quiz"
            )
        )
        await conn.execute(
            insert(ContentRelease.__table__).values(
                id=ids["release"],
                tenant_id=ids["tenant"],
                course_id=ids["course"],
                version=1,
                snapshot=release_snapshot,
                snapshot_sha256=release_hash,
            )
        )
        for enrollment, user in (
            ("enrollment1", "user1"),
            ("enrollment2", "user2"),
            ("foreign_enrollment", "foreign_user"),
        ):
            foreign = user == "foreign_user"
            await conn.execute(
                insert(Enrollment.__table__).values(
                    id=ids[enrollment],
                    user_id=ids[user],
                    tenant_id=ids["foreign_tenant" if foreign else "tenant"],
                    course_id=ids["foreign_course" if foreign else "course"],
                    content_release_id=None if foreign else ids["release"],
                )
            )
        for row in attempt_rows:
            await conn.execute(insert(QuizAttempt.__table__).values(**row))
    checks.append("synthetic_only_fixture_seed")

    actor = SimpleNamespace(
        id=ids["methodologist"], tenant_id=ids["tenant"], role="methodologist", is_active=True, status="active"
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def current_user():
        return actor

    async def session():
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": str(actor.tenant_id or "")}
                )
                yield db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = session
    prefix = "/api/v1/admin/learning-insights"
    enrollment_url = f"{prefix}/enrollments/{ids['enrollment1']}"
    course_url = f"{prefix}/courses/{ids['course']}"
    review_url = f"{prefix}/attempts/{attempt_rows[0]['id']}/questions/{ids['question']}/review"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.test") as client:
        detail = await client.get(enrollment_url)
        assert detail.status_code == 200, "http_enrollment_success"
        payload = detail.json()
        assert detail.headers.get("cache-control") == "no-store", "http_no_store"
        assert [a["evidence_status"] for a in payload["attempts"]] == ["verified", "verified"], "snapshot_verified"
        assert payload["attempts"][0]["lesson_id"] == str(ids["lesson"]), "release_lesson_navigation"
        assert payload["attempts"][0]["questions"][0]["choices"][1]["selected"], "exact_wrong_answer"
        assert all(key not in detail.text for key in ("email", "phone", "password")), "private_fields_absent"
        summary = (await client.get(course_url)).json()
        stats = summary["questions"][0]
        assert (stats["respondents"], stats["incorrect"], stats["latest_incorrect"], stats["improved"]) == (
            2,
            2,
            1,
            1,
        ), "unique_first_latest_statistics"
        period = await client.get(course_url, params={"date_from": (now + timedelta(minutes=30)).isoformat()})
        assert period.json()["questions"][0]["respondents"] == 1, "first_attempt_before_period_not_promoted"
        assert (
            await client.get(course_url, params={"date_from": "2026-09-01"})
        ).status_code == 422, "naive_date_rejected"
        assert (
            await client.get(f"{prefix}/enrollments/{ids['foreign_enrollment']}")
        ).status_code == 404, "foreign_enrollment_404"
        assert (await client.get(f"{prefix}/courses/{ids['foreign_course']}")).status_code == 404, "foreign_course_404"
        checks.extend(
            ("http_detail_and_exact_answers", "cohort_first_latest_and_period", "tenant_http_404_and_private_fields")
        )
        for role in ("student", "admin", "superadmin"):
            actor.role = role
            for method, url in (("get", enrollment_url), ("get", course_url), ("put", review_url)):
                response = await getattr(client, method)(
                    url, **({"json": {"status": "train_staff"}} if method == "put" else {})
                )
                assert response.status_code == 403, "unauthorized_role_403"
        actor.role, actor.tenant_id = "superadmin", None
        assert (await client.get(enrollment_url)).status_code == 403, "platform_no_tenant_403"
        actor.role, actor.tenant_id = "methodologist", ids["tenant"]
        actor.is_active = False
        assert (await client.get(enrollment_url)).status_code == 403, "inactive_user_403"
        actor.is_active = True
        actor.role = "superadmin"
        assert (await client.get(enrollment_url)).status_code == 403, "superadmin_requires_active_methodologist"
        actor.role = "methodologist"
        checks.append("roles_and_inactive_negatives")
        for status in ("train_staff", "train_staff", "resolved"):
            saved = await client.put(review_url, json={"status": status})
            assert saved.status_code == 200 and saved.json()["status"] == status, "annotation_save"
            reloaded = (await client.get(enrollment_url)).json()
            assert (
                reloaded["attempts"][0]["questions"][0]["review"]["status"] == status
            ), "annotation_fresh_session_readback"
        assert (await client.put(review_url, json={"status": "invented"})).status_code == 422, "invalid_status_422"
        actor.tenant_id = ids["foreign_tenant"]
        assert (
            await client.put(review_url, json={"status": "train_staff"})
        ).status_code == 404, "foreign_annotation_404"
        actor.tenant_id = ids["tenant"]
        checks.append("annotation_idempotence_persistence_and_tenant_boundary")
        actor.is_impersonating = True
        assert (
            await client.put(review_url, json={"status": "resolved"})
        ).status_code == 200, "impersonated_tenant_annotation"
        actor.is_impersonating = False

    async with owner.connect() as conn:
        unchanged = (
            (await conn.execute(select(QuizAttempt.evidence_sha256).order_by(QuizAttempt.completed_at))).scalars().all()
        )
        assert unchanged == [row["evidence_sha256"] for row in attempt_rows], "original_evidence_unchanged"
        count = (await conn.execute(text("SELECT count(*) FROM learning_question_reviews"))).scalar_one()
        assert count == 1, "upsert_unique_row"
        flags = (
            await conn.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:name)"),
                {"name": f"{schema}.learning_question_reviews"},
            )
        ).one()
        assert flags == (True, True), "annotation_forced_rls"
    async with runtime.begin() as conn:
        assert (await conn.execute(text("SELECT current_schema()"))).scalar_one() == schema, "runtime_schema_binding"
        assert (
            await conn.execute(text("SELECT count(*) FROM learning_question_reviews"))
        ).scalar_one() == 0, "no_context_no_rows"
        await conn.execute(
            text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": str(ids["foreign_tenant"])}
        )
        assert (
            await conn.execute(text("SELECT count(*) FROM learning_question_reviews"))
        ).scalar_one() == 0, "foreign_context_no_rows"
    for violation in ("tenant", "course", "actor", "status", "delete"):
        rejected = False
        try:
            async with runtime.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": str(ids["tenant"])}
                )
                if violation == "delete":
                    await conn.execute(text("DELETE FROM learning_question_reviews"))
                else:
                    await conn.execute(
                        text(
                            "INSERT INTO learning_question_reviews (tenant_id,course_id,question_key,status,updated_by) VALUES (:tenant,:course,:key,:status,:actor)"
                        ),
                        {
                            "tenant": ids["foreign_tenant" if violation == "tenant" else "tenant"],
                            "course": ids["foreign_course" if violation == "course" else "course"],
                            "actor": ids["foreign_user" if violation == "actor" else "methodologist"],
                            "key": uuid4().hex * 2,
                            "status": "invalid" if violation == "status" else "train_staff",
                        },
                    )
        except DBAPIError as exc:
            expected = "23514" if violation == "status" else "42501"
            assert getattr(exc.orig, "sqlstate", None) == expected, "expected_rls_or_check_sqlstate"
            rejected = True
        assert rejected, "database_boundary_rejection"
    checks.extend(
        (
            "immutable_evidence_unchanged",
            "forced_rls_and_no_context",
            "sql_cross_tenant_course_actor_status_delete_rejected",
        )
    )

    from copy import deepcopy

    from pytest import MonkeyPatch

    from app.modules.learning_insights import service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.test") as client:
        with MonkeyPatch.context() as patch:
            patch.setattr(service, "MAX_CANDIDATE_ATTEMPTS", 2)
            assert (await client.get(course_url)).status_code == 422, "aggregate_overflow_explicit"
            patch.setattr(service, "MAX_ENROLLMENT_ATTEMPTS", 1)
            assert (await client.get(enrollment_url)).status_code == 422, "history_overflow_explicit"
        unknown = deepcopy(attempt_rows[-1])
        unknown.update(id=uuid4(), completed_at=now + timedelta(hours=3), evidence_snapshot=None, evidence_sha256=None)
        async with owner.begin() as conn:
            await conn.execute(insert(QuizAttempt.__table__).values(**unknown))
        stats = (await client.get(course_url)).json()["questions"][0]
        assert (stats["respondents"], stats["latest_respondents"], stats["latest_unavailable"], stats["improved"]) == (
            2,
            1,
            1,
            0,
        ), "missing_latest_not_carried_forward"
        unknown_url = f"{prefix}/attempts/{unknown['id']}/questions/{ids['question']}/review"
        assert (
            await client.put(unknown_url, json={"status": "resolved"})
        ).status_code == 409, "missing_evidence_annotation_409"
        cutoff = await client.get(course_url, params={"date_to": (now + timedelta(hours=2, minutes=30)).isoformat()})
        assert cutoff.json()["questions"][0]["latest_respondents"] == 2, "latest_cutoff_selects_actual_in_period"
        changed = deepcopy(attempt_rows[-1])
        changed.update(id=uuid4(), completed_at=now + timedelta(hours=4))
        changed["evidence_snapshot"]["attempt"].update(
            id=str(changed["id"]), completed_at=changed["completed_at"].isoformat()
        )
        changed["evidence_snapshot"]["quiz"]["questions"][0]["text"] = "Different synthetic question definition"
        changed["evidence_sha256"] = canonical_json_sha256(changed["evidence_snapshot"])
        async with owner.begin() as conn:
            await conn.execute(insert(QuizAttempt.__table__).values(**changed))
        stats = (await client.get(course_url)).json()["questions"]
        assert len(stats) == 1 and stats[0]["latest_unavailable"] == 1, "changed_latest_definition_not_promoted"
        earlier = deepcopy(attempt_rows[1])
        earlier.update(id=uuid4(), completed_at=now - timedelta(hours=1), evidence_snapshot=None, evidence_sha256=None)
        async with owner.begin() as conn:
            await conn.execute(insert(QuizAttempt.__table__).values(**earlier))
        stats = (await client.get(course_url)).json()["questions"][0]
        assert stats["respondents"] == 1 and stats["latest_respondents"] == 0, "missing_first_not_promoted"
        assert stats["latest_incorrect_percent"] is None, "unknown_latest_is_not_zero_percent"
        checks.extend(
            (
                "bounded_query_fail_closed",
                "missing_first_latest_and_changed_definition",
                "latest_period_cutoff_and_null_percentage",
            )
        )
