"""Seed a dedicated Kamilya LMS tenant for load testing.

This script is intentionally deterministic and idempotent for one tenant slug.
Use it only for staging or for a dedicated production load-test tenant.

Examples:
  python scripts/seed_load_tenant.py --dry-run
  python scripts/seed_load_tenant.py --learners 500 --courses 20 --reset
  python scripts/seed_load_tenant.py --database-url postgresql+asyncpg://...
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import argon2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - only for minimal environments.
    dotenv_values = None


ph = argon2.PasswordHasher()


@dataclass(frozen=True)
class SeedConfig:
    slug: str
    name: str
    learners: int
    admins: int
    methodologists: int
    courses: int
    modules_per_course: int
    lessons_per_module: int
    questions_per_quiz: int
    password: str
    token_ttl_minutes: int
    reset: bool
    dry_run: bool
    output_csv: Path
    database_url: str


async def main() -> None:
    args = parse_args()
    database_url = resolve_database_url(args.database_url)
    config = SeedConfig(
        slug=args.slug,
        name=args.name,
        learners=args.learners,
        admins=args.admins,
        methodologists=args.methodologists,
        courses=args.courses,
        modules_per_course=args.modules,
        lessons_per_module=args.lessons,
        questions_per_quiz=args.questions,
        password=args.password,
        token_ttl_minutes=args.token_ttl_minutes,
        reset=args.reset,
        dry_run=args.dry_run,
        output_csv=Path(args.output_csv),
        database_url=database_url,
    )

    print_summary(config)
    if config.dry_run:
        return

    engine = create_async_engine(config.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        tenant_id = await ensure_tenant(session, config)
        await session.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})
        if config.reset:
            await reset_tenant_data(session, tenant_id)
            await session.flush()

        users = await ensure_users(session, tenant_id, config)
        course_data = await ensure_courses(session, tenant_id, users["methodologists"][0], config)
        await ensure_enrollments(session, tenant_id, users["learners"], course_data["course_ids"])
        await session.commit()

    await engine.dispose()

    write_users_csv(config.output_csv, users, config)
    print("")
    print("Load tenant seeded.")
    print(f"tenant_id={tenant_id}")
    print(f"slug={config.slug}")
    print(f"users_csv={config.output_csv}")
    print(f"course_ids={','.join(str(item) for item in course_data['course_ids'][:5])}")
    print(f"lesson_ids={','.join(str(item) for item in course_data['lesson_ids'][:10])}")
    print(f"quiz_ids={','.join(str(item) for item in course_data['quiz_ids'][:10])}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a Kamilya LMS tenant for load testing.")
    parser.add_argument(
        "--slug",
        default="load-test.kml",
        help="Tenant slug to create/use. For password login it must match the users' email domain.",
    )
    parser.add_argument("--name", default="Kamilya Load Test Tenant", help="Tenant display name.")
    parser.add_argument("--learners", type=int, default=500)
    parser.add_argument("--admins", type=int, default=2)
    parser.add_argument("--methodologists", type=int, default=5)
    parser.add_argument("--courses", type=int, default=20)
    parser.add_argument("--modules", type=int, default=3, help="Modules per course.")
    parser.add_argument("--lessons", type=int, default=4, help="Lessons per module.")
    parser.add_argument("--questions", type=int, default=3, help="Questions per lesson quiz.")
    parser.add_argument("--password", default=os.getenv("LOAD_TEST_PASSWORD", "LoadTest123!"))
    parser.add_argument(
        "--token-ttl-minutes",
        type=int,
        default=240,
        help="Access token TTL written to the generated k6 CSV. Use 0 to omit tokens.",
    )
    parser.add_argument("--output-csv", default=str(REPO_ROOT / "tests" / "load" / "load-users.csv"))
    parser.add_argument("--database-url", default="")
    parser.add_argument("--reset", action="store_true", help="Delete existing data for this tenant before seeding.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_database_url(explicit: str) -> str:
    if explicit:
        return explicit
    env_path = REPO_ROOT / ".env"
    values = dotenv_values(env_path) if dotenv_values and env_path.exists() else {}
    url = (
        values.get("MIGRATION_DATABASE_URL")
        or values.get("DATABASE_URL")
        or os.getenv("MIGRATION_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )
    if not url:
        raise SystemExit("DATABASE_URL or MIGRATION_DATABASE_URL is required.")
    normalized = str(url)
    if normalized.startswith("postgres://"):
        normalized = "postgresql+asyncpg://" + normalized.removeprefix("postgres://")
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+asyncpg://" + normalized.removeprefix("postgresql://")
    return normalized


def print_summary(config: SeedConfig) -> None:
    print("Kamilya LMS load-test seed")
    print(f"tenant={config.name} ({config.slug})")
    print(f"learners={config.learners}, admins={config.admins}, methodologists={config.methodologists}")
    print(
        "content="
        f"{config.courses} courses x {config.modules_per_course} modules x "
        f"{config.lessons_per_module} lessons x {config.questions_per_quiz} quiz questions"
    )
    print(f"reset={config.reset}, dry_run={config.dry_run}")


async def ensure_tenant(session: AsyncSession, config: SeedConfig) -> UUID:
    existing = (
        await session.execute(text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": config.slug})
    ).scalar_one_or_none()
    if existing:
        tenant_id = UUID(str(existing))
        await session.execute(
            text(
                """
                UPDATE tenants
                SET name = :name,
                    status = 'active',
                    plan = 'load_test',
                    max_users = NULL,
                    max_courses_per_month = NULL,
                    trial_ends_at = NULL,
                    updated_at = now()
                WHERE id = :tenant_id
                """
            ),
            {"tenant_id": str(tenant_id), "name": config.name},
        )
        return tenant_id

    tenant_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tenants (
                id, name, slug, status, plan, settings, is_demo,
                max_users, max_courses_per_month
            )
            VALUES (
                :tenant_id, :name, :slug, 'active', 'load_test', '{}'::jsonb, false,
                NULL, NULL
            )
            """
        ),
        {"tenant_id": str(tenant_id), "name": config.name, "slug": config.slug},
    )
    return tenant_id


async def reset_tenant_data(session: AsyncSession, tenant_id: UUID) -> None:
    statements = [
        "DELETE FROM quiz_attempts WHERE tenant_id = :tenant_id",
        """
        DELETE FROM quiz_choices
        WHERE question_id IN (
            SELECT qn.id
            FROM questions qn
            JOIN quizzes qz ON qz.id = qn.quiz_id
            WHERE qz.tenant_id = :tenant_id
        )
        """,
        """
        DELETE FROM questions
        WHERE quiz_id IN (SELECT id FROM quizzes WHERE tenant_id = :tenant_id)
        """,
        "DELETE FROM quizzes WHERE tenant_id = :tenant_id",
        "DELETE FROM progress WHERE tenant_id = :tenant_id",
        "DELETE FROM enrollments WHERE tenant_id = :tenant_id",
        "DELETE FROM content_blocks WHERE lesson_id IN (SELECT id FROM lessons WHERE tenant_id = :tenant_id)",
        "DELETE FROM lessons WHERE tenant_id = :tenant_id",
        "DELETE FROM modules WHERE tenant_id = :tenant_id",
        "DELETE FROM courses WHERE tenant_id = :tenant_id",
        "DELETE FROM position_courses WHERE tenant_id = :tenant_id",
        "DELETE FROM positions WHERE tenant_id = :tenant_id",
        "DELETE FROM user_roles WHERE tenant_id = :tenant_id",
        "DELETE FROM users WHERE tenant_id = :tenant_id",
        "DELETE FROM tenant_usage WHERE tenant_id = :tenant_id",
    ]
    for statement in statements:
        await session.execute(text(statement), {"tenant_id": str(tenant_id)})


async def ensure_users(session: AsyncSession, tenant_id: UUID, config: SeedConfig) -> dict[str, list[dict]]:
    users: dict[str, list[dict]] = {"admins": [], "methodologists": [], "learners": []}
    password_hash = ph.hash(config.password)

    for index in range(config.admins):
        users["admins"].append(
            await ensure_user(
                session,
                tenant_id,
                email=f"load-admin-{index + 1}@{config.slug}",
                first_name="Load",
                last_name=f"Admin {index + 1}",
                role="admin",
                password_hash=password_hash,
                personnel_number=f"load-admin-{index + 1:04d}",
            )
        )

    for index in range(config.methodologists):
        users["methodologists"].append(
            await ensure_user(
                session,
                tenant_id,
                email=f"load-methodologist-{index + 1}@{config.slug}",
                first_name="Load",
                last_name=f"Methodologist {index + 1}",
                role="teacher",
                password_hash=password_hash,
                personnel_number=f"load-methodologist-{index + 1:04d}",
            )
        )

    for index in range(config.learners):
        users["learners"].append(
            await ensure_user(
                session,
                tenant_id,
                email=f"load-learner-{index + 1:04d}@{config.slug}",
                first_name="Load",
                last_name=f"Learner {index + 1:04d}",
                role="student",
                password_hash=password_hash,
                personnel_number=f"load-learner-{index + 1:04d}",
            )
        )

    return users


async def ensure_user(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    email: str,
    first_name: str,
    last_name: str,
    role: str,
    password_hash: str,
    personnel_number: str,
) -> dict:
    row = (
        await session.execute(
            text(
                """
                SELECT id FROM users
                WHERE tenant_id = :tenant_id AND lower(email) = lower(:email)
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "email": email},
        )
    ).mappings().first()

    if row:
        user_id = UUID(str(row["id"]))
        await session.execute(
            text(
                """
                UPDATE users
                SET first_name = :first_name,
                    last_name = :last_name,
                    role = :role,
                    password_hash = :password_hash,
                    personnel_number = :personnel_number,
                    is_active = true,
                    status = 'active',
                    updated_at = now()
                WHERE id = :user_id
                """
            ),
            {
                "user_id": str(user_id),
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "password_hash": password_hash,
                "personnel_number": personnel_number,
            },
        )
    else:
        user_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO users (
                    id, tenant_id, email, personnel_number, password_hash,
                    first_name, last_name, role, is_active, status
                )
                VALUES (
                    :user_id, :tenant_id, :email, :personnel_number, :password_hash,
                    :first_name, :last_name, :role, true, 'active'
                )
                """
            ),
            {
                "user_id": str(user_id),
                "tenant_id": str(tenant_id),
                "email": email,
                "personnel_number": personnel_number,
                "password_hash": password_hash,
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
            },
        )

    await session.execute(
        text(
            """
            INSERT INTO user_roles (id, user_id, tenant_id, role)
            VALUES (:id, :user_id, :tenant_id, :role)
            ON CONFLICT (user_id, tenant_id, role) DO NOTHING
            """
        ),
        {"id": str(uuid4()), "user_id": str(user_id), "tenant_id": str(tenant_id), "role": role},
    )
    return {"id": user_id, "tenant_id": tenant_id, "email": email, "role": role}


async def ensure_courses(
    session: AsyncSession,
    tenant_id: UUID,
    creator: dict,
    config: SeedConfig,
) -> dict[str, list[UUID]]:
    course_ids: list[UUID] = []
    lesson_ids: list[UUID] = []
    quiz_ids: list[UUID] = []

    for course_index in range(config.courses):
        course_id = await ensure_course(session, tenant_id, creator["id"], course_index)
        course_ids.append(course_id)

        for module_index in range(config.modules_per_course):
            module_id = await ensure_module(session, tenant_id, course_id, course_index, module_index)
            for lesson_index in range(config.lessons_per_module):
                lesson_id = await ensure_lesson(session, tenant_id, module_id, course_index, module_index, lesson_index)
                lesson_ids.append(lesson_id)
                quiz_id = await ensure_quiz(
                    session,
                    tenant_id,
                    lesson_id,
                    course_index,
                    module_index,
                    lesson_index,
                    config.questions_per_quiz,
                )
                quiz_ids.append(quiz_id)

    return {"course_ids": course_ids, "lesson_ids": lesson_ids, "quiz_ids": quiz_ids}


async def ensure_course(session: AsyncSession, tenant_id: UUID, creator_id: UUID, course_index: int) -> UUID:
    title = f"Load Test Course {course_index + 1:02d}"
    row = (
        await session.execute(
            text(
                """
                SELECT id FROM courses
                WHERE tenant_id = :tenant_id AND title = :title
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "title": title},
        )
    ).mappings().first()
    if row:
        course_id = UUID(str(row["id"]))
        await session.execute(
            text(
                """
                UPDATE courses
                SET description = :description,
                    status = 'published',
                    ai_generated = false,
                    review_status = 'approved',
                    reviewed_by = :creator_id,
                    reviewed_at = now(),
                    published_at = COALESCE(published_at, now()),
                    updated_at = now()
                WHERE id = :course_id
                """
            ),
            {
                "course_id": str(course_id),
                "creator_id": str(creator_id),
                "description": f"Published course for load testing #{course_index + 1}.",
            },
        )
        return course_id

    course_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO courses (
                id, tenant_id, title, description, status, created_by,
                published_at, ai_generated, review_status, reviewed_by, reviewed_at
            )
            VALUES (
                :course_id, :tenant_id, :title, :description, 'published', :creator_id,
                now(), false, 'approved', :creator_id, now()
            )
            """
        ),
        {
            "course_id": str(course_id),
            "tenant_id": str(tenant_id),
            "title": title,
            "description": f"Published course for load testing #{course_index + 1}.",
            "creator_id": str(creator_id),
        },
    )
    return course_id


async def ensure_module(
    session: AsyncSession,
    tenant_id: UUID,
    course_id: UUID,
    course_index: int,
    module_index: int,
) -> UUID:
    title = f"Module {module_index + 1}: Load scenario {course_index + 1}.{module_index + 1}"
    row = (
        await session.execute(
            text(
                """
                SELECT id FROM modules
                WHERE tenant_id = :tenant_id AND course_id = :course_id AND order_index = :order_index
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "course_id": str(course_id), "order_index": module_index},
        )
    ).mappings().first()
    if row:
        module_id = UUID(str(row["id"]))
        await session.execute(
            text("UPDATE modules SET title = :title, description = :description WHERE id = :module_id"),
            {"module_id": str(module_id), "title": title, "description": "Synthetic module for load testing."},
        )
        return module_id

    module_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO modules (id, tenant_id, course_id, title, description, order_index, ai_generated)
            VALUES (:module_id, :tenant_id, :course_id, :title, :description, :order_index, false)
            """
        ),
        {
            "module_id": str(module_id),
            "tenant_id": str(tenant_id),
            "course_id": str(course_id),
            "title": title,
            "description": "Synthetic module for load testing.",
            "order_index": module_index,
        },
    )
    return module_id


async def ensure_lesson(
    session: AsyncSession,
    tenant_id: UUID,
    module_id: UUID,
    course_index: int,
    module_index: int,
    lesson_index: int,
) -> UUID:
    title = f"Lesson {lesson_index + 1}: Load path {course_index + 1}.{module_index + 1}.{lesson_index + 1}"
    row = (
        await session.execute(
            text(
                """
                SELECT id FROM lessons
                WHERE tenant_id = :tenant_id AND module_id = :module_id AND order_index = :order_index
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "module_id": str(module_id), "order_index": lesson_index},
        )
    ).mappings().first()
    content = (
        f"{title}\n\n"
        "This is deterministic synthetic training content for load tests. "
        "It is long enough to exercise course rendering and quiz grounding, "
        "but intentionally contains no customer data or secrets.\n\n"
        "Key points:\n"
        "1. Read the procedure before acting.\n"
        "2. Confirm the responsible role.\n"
        "3. Record completion in the LMS.\n"
    )
    if row:
        lesson_id = UUID(str(row["id"]))
        await session.execute(
            text(
                """
                UPDATE lessons
                SET title = :title,
                    content = :content,
                    duration_seconds = 600,
                    content_type = 'text',
                    published_at = COALESCE(published_at, now()),
                    updated_at = now()
                WHERE id = :lesson_id
                """
            ),
            {"lesson_id": str(lesson_id), "title": title, "content": content},
        )
        return lesson_id

    lesson_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO lessons (
                id, tenant_id, module_id, title, content_type, content,
                duration_seconds, order_index, ai_generated, published_at
            )
            VALUES (
                :lesson_id, :tenant_id, :module_id, :title, 'text', :content,
                600, :order_index, false, now()
            )
            """
        ),
        {
            "lesson_id": str(lesson_id),
            "tenant_id": str(tenant_id),
            "module_id": str(module_id),
            "title": title,
            "content": content,
            "order_index": lesson_index,
        },
    )
    return lesson_id


async def ensure_quiz(
    session: AsyncSession,
    tenant_id: UUID,
    lesson_id: UUID,
    course_index: int,
    module_index: int,
    lesson_index: int,
    questions_per_quiz: int,
) -> UUID:
    row = (
        await session.execute(
            text("SELECT id FROM quizzes WHERE tenant_id = :tenant_id AND lesson_id = :lesson_id LIMIT 1"),
            {"tenant_id": str(tenant_id), "lesson_id": str(lesson_id)},
        )
    ).mappings().first()
    if row:
        quiz_id = UUID(str(row["id"]))
        await session.execute(
            text("DELETE FROM quiz_choices WHERE question_id IN (SELECT id FROM questions WHERE quiz_id = :quiz_id)"),
            {"quiz_id": str(quiz_id)},
        )
        await session.execute(text("DELETE FROM questions WHERE quiz_id = :quiz_id"), {"quiz_id": str(quiz_id)})
    else:
        quiz_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO quizzes (id, lesson_id, tenant_id, title, pass_score, attempt_limit, deferral_days)
                VALUES (:quiz_id, :lesson_id, :tenant_id, :title, 80, 3, 7)
                """
            ),
            {
                "quiz_id": str(quiz_id),
                "lesson_id": str(lesson_id),
                "tenant_id": str(tenant_id),
                "title": f"Quiz {course_index + 1}.{module_index + 1}.{lesson_index + 1}",
            },
        )

    for question_index in range(questions_per_quiz):
        question_id = uuid4()
        await session.execute(
            text(
                """
                INSERT INTO questions (id, quiz_id, text, type, points, explanation, order_index)
                VALUES (:question_id, :quiz_id, :text, 'multiple_choice', 1, :explanation, :order_index)
                """
            ),
            {
                "question_id": str(question_id),
                "quiz_id": str(quiz_id),
                "text": f"What is the expected action in load-test lesson question {question_index + 1}?",
                "explanation": "The expected action is to follow the documented process and record progress.",
                "order_index": question_index,
            },
        )
        choices = [
            ("Follow the documented process and record progress", True),
            ("Skip the LMS record", False),
            ("Delete the course", False),
            ("Ignore the responsible role", False),
        ]
        for choice_index, (choice_text, is_correct) in enumerate(choices):
            await session.execute(
                text(
                    """
                    INSERT INTO quiz_choices (id, question_id, text, is_correct, order_index)
                    VALUES (:choice_id, :question_id, :text, :is_correct, :order_index)
                    """
                ),
                {
                    "choice_id": str(uuid4()),
                    "question_id": str(question_id),
                    "text": choice_text,
                    "is_correct": is_correct,
                    "order_index": choice_index,
                },
            )

    return quiz_id


async def ensure_enrollments(
    session: AsyncSession,
    tenant_id: UUID,
    learners: list[dict],
    course_ids: list[UUID],
) -> None:
    for learner_index, learner in enumerate(learners):
        # Enroll every learner in a small rotating subset. This gives broad
        # course coverage without creating learners*courses rows by default.
        assigned_courses = [
            course_ids[learner_index % len(course_ids)],
            course_ids[(learner_index + 1) % len(course_ids)],
        ]
        for course_id in assigned_courses:
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT id FROM enrollments
                        WHERE tenant_id = :tenant_id AND user_id = :user_id AND course_id = :course_id
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "user_id": str(learner["id"]),
                        "course_id": str(course_id),
                    },
                )
            ).scalar_one_or_none()
            if existing:
                continue
            await session.execute(
                text(
                    """
                    INSERT INTO enrollments (id, tenant_id, user_id, course_id, status, source)
                    VALUES (:id, :tenant_id, :user_id, :course_id, 'enrolled', 'manual')
                    """
                ),
                {
                    "id": str(uuid4()),
                    "tenant_id": str(tenant_id),
                    "user_id": str(learner["id"]),
                    "course_id": str(course_id),
                },
            )


def write_users_csv(path: Path, users: dict[str, list[dict]], config: SeedConfig) -> None:
    from app.core.auth import create_access_token

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for group in ("learners", "admins", "methodologists"):
            for user in users[group]:
                token = ""
                if config.token_ttl_minutes > 0:
                    token = create_access_token(
                        {
                            "sub": str(user["id"]),
                            "tenant_id": str(user["tenant_id"]),
                            "roles": [user["role"]],
                        },
                        expires_delta=timedelta(minutes=config.token_ttl_minutes),
                    )
                writer.writerow([user["email"], config.password, token])


if __name__ == "__main__":
    asyncio.run(main())
