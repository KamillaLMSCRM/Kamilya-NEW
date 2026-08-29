"""Bootstrap the real Lombard Sandyk tenant in an approved KZ database.

The command imports only organization structure, learner profiles, two approved
course definitions and their immutable releases. It never copies old
enrollments, attempts, certificates, evidence, invitations, credentials or
audit rows. A repeat is supported only while the bootstrap tenant has not been
changed afterwards; exact postconditions fail closed otherwise. Dry-run is the
default.
"""

# ruff: noqa: E402 -- the standalone script must add apps/api before app imports.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.registry import load_all_models

# Standalone bootstrap scripts do not pass through ``app.main``. Load the
# canonical registry explicitly so SQLAlchemy can resolve every foreign key
# while flushing related rows (notably Enrollment.recurring_assignment_id).
load_all_models()

from app.core.storage import get_storage
from app.models.department import Department
from app.models.document import Document
from app.models.enrollment import Enrollment
from app.models.tenants import Tenant, TenantUsage
from app.models.users import User
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import create_course_release
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.positions.batch_service import apply_rules_for_users
from app.modules.positions.models import Position, PositionCourse
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.users.staff_import_service import build_preview, commit_import, parse_upload

TENANT_NAME = "ТОО «Ломбард Сандық»"
TENANT_SLUG = "too-lombard-sandyk"
CONFIRMATION = "IMPORT-LOMBARD-SANDYK"
EXPECTED_COUNTS = {
    "users": 13,  # 12 learners plus one inactive, non-login import actor.
    "students": 12,
    "departments": 2,
    "positions": 4,
    "documents": 2,
    "courses": 2,
    "content_releases": 2,
    "modules": 7,
    "lessons": 18,
    "content_blocks": 0,
    "quizzes": 18,
    "questions": 78,
    "quiz_choices": 312,
    "position_course_rules": 6,
    "enrollments": 22,
}


def _async_url(value: str) -> str:
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def _package_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_snapshot_sha256(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_package(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported course package schema")
    courses = payload.get("courses")
    if not isinstance(courses, list) or len(courses) != 2:
        raise ValueError("The Lombard Sandyk package must contain exactly two courses")
    totals = {"modules": 0, "lessons": 0, "quizzes": 0, "questions": 0}
    kinds: set[str] = set()
    for item in courses:
        snapshot = item.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("Course package contains an invalid release snapshot")
        if _canonical_snapshot_sha256(snapshot) != item.get("source_snapshot_sha256"):
            raise ValueError("Course package release checksum mismatch")
        course_payload = snapshot.get("course") or {}
        if str(item.get("source_course_id")) != str(course_payload.get("id")):
            raise ValueError("Source course ID does not match the release snapshot")
        if str(course_payload.get("tenant_id")) != str(payload.get("source_tenant_id")):
            raise ValueError("Source tenant ID does not match the release snapshot")
        document_ids = {
            str(document["id"])
            for document in snapshot.get("source_documents") or []
        }
        referenced_ids = {str(value) for value in course_payload.get("source_document_ids") or []}
        if course_payload.get("source_instruction_id"):
            referenced_ids.add(str(course_payload["source_instruction_id"]))
        kinds.add(_course_kind(str(snapshot["course"]["title"])))
        modules = snapshot.get("modules") or []
        lessons = [lesson for module in modules for lesson in module.get("lessons") or []]
        for lesson in lessons:
            referenced_ids.update(str(value) for value in lesson.get("source_document_ids") or [])
        if referenced_ids != document_ids:
            raise ValueError("Source document manifest does not match course references")
        quizzes = [quiz for lesson in lessons for quiz in lesson.get("quizzes") or []]
        questions = [question for quiz in quizzes for question in quiz.get("questions") or []]
        totals["modules"] += len(modules)
        totals["lessons"] += len(lessons)
        totals["quizzes"] += len(quizzes)
        totals["questions"] += len(questions)
    if kinds != {"microcredit_rules", "expert_appraiser_instruction"}:
        raise ValueError("Course package does not contain both approved Sandyk course kinds")
    if totals != {"modules": 7, "lessons": 18, "quizzes": 18, "questions": 78}:
        raise ValueError(f"Unexpected Sandyk course graph: {totals}")
    return payload


def _course_kind(title: str) -> str:
    normalized = title.casefold()
    if "микрокредит" in normalized or "правил" in normalized:
        return "microcredit_rules"
    if "эксперт" in normalized or "оценщик" in normalized:
        return "expert_appraiser_instruction"
    raise ValueError(f"Unexpected course in package: {title}")


def _remap_json_ids(value: Any, document_ids: dict[str, UUID]) -> Any:
    if isinstance(value, dict):
        return {key: _remap_json_ids(item, document_ids) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_json_ids(item, document_ids) for item in value]
    if isinstance(value, str) and value in document_ids:
        return str(document_ids[value])
    return value


async def _set_tenant_context(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})


async def _ensure_tenant(db: AsyncSession) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.slug == TENANT_SLUG).with_for_update())
    if tenant is not None:
        if tenant.name != TENANT_NAME:
            raise ValueError("Target slug is already used by another tenant name")
        if tenant.is_demo:
            raise ValueError("Refusing to reuse a demo tenant as the real customer tenant")
        return tenant
    tenant = Tenant(
        id=uuid4(),
        name=TENANT_NAME,
        slug=TENANT_SLUG,
        status="active",
        plan="custom",
        max_users=50,
        max_courses_per_month=10,
        settings={"onboarding_source": "lombard_sandyk_2026_08"},
        is_demo=False,
    )
    db.add(tenant)
    db.add(TenantUsage(tenant_id=tenant.id))
    await db.flush()
    return tenant


async def _ensure_import_actor(db: AsyncSession, tenant_id: UUID) -> User:
    actor = await db.scalar(
        select(User).where(
            User.tenant_id == tenant_id,
            User.personnel_number == "SYSTEM-IMPORT",
            User.role == "methodologist",
        )
    )
    if actor is not None:
        return actor
    actor = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=None,
        personnel_number="SYSTEM-IMPORT",
        first_name="Системный",
        last_name="Импорт",
        role="methodologist",
        is_active=False,
        status="inactive",
    )
    db.add(actor)
    await db.flush()
    return actor


def _source_document_manifests(package: dict[str, Any]) -> list[dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for item in package["courses"]:
        for document in item["snapshot"].get("source_documents") or []:
            manifests[str(document["id"])] = document
    return list(manifests.values())


def _validate_source_files(package: dict[str, Any], source_document_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for manifest in _source_document_manifests(package):
        path = source_document_dir / str(manifest["filename"])
        if not path.is_file():
            raise ValueError(f"Source document is missing: {manifest['filename']}")
        expected_hash = str(manifest.get("content_sha256") or "").lower()
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected_hash or actual_hash != expected_hash:
            raise ValueError(f"Source document checksum mismatch: {manifest['filename']}")
        paths[str(manifest["id"])] = path
    return paths


async def _ensure_source_documents(
    db: AsyncSession,
    tenant_id: UUID,
    actor_id: UUID,
    package: dict[str, Any],
    source_paths: dict[str, Path],
) -> tuple[dict[str, UUID], list[str]]:
    mapping: dict[str, UUID] = {}
    created_storage_keys: list[str] = []
    storage = get_storage()
    for manifest in _source_document_manifests(package):
        source_id = str(manifest["id"])
        path = source_paths[source_id]
        content = path.read_bytes()
        content_sha256 = hashlib.sha256(content).hexdigest()
        existing = await db.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.content_sha256 == content_sha256,
                Document.lifecycle_status == "active",
            )
        )
        if existing is not None:
            mapping[source_id] = existing.id
            continue
        # A deterministic tenant-local ID makes a retry converge on the same
        # storage object even if the process died after put_bytes but before
        # the database transaction committed.
        document_id = uuid5(tenant_id, f"document:{content_sha256}")
        storage_key = f"tenants/{tenant_id}/documents/{document_id}{path.suffix.lower()}"
        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            uploaded_by=actor_id,
            title=manifest.get("title") or path.name,
            filename=path.name,
            content_type=manifest["content_type"],
            size=len(content),
            s3_key=storage_key,
            description="Исходный документ перенесён вместе с подтверждённым курсом.",
            category=manifest.get("category") or "general",
            embedding_status="failed",
            embedding_error="Требуется повторная индексация в Казахстанском контуре",
            source_family_id=document_id,
            version=1,
            content_sha256=content_sha256,
            lifecycle_status="active",
            index_status="failed",
            index_error_code="reindex_required_after_tenant_transfer",
            index_message="Файл доступен; для AI-поиска требуется повторная индексация.",
            index_revision=1,
        )
        db.add(document)
        await db.flush()
        storage.put_bytes(storage_key, content, str(manifest["content_type"]))
        created_storage_keys.append(storage_key)
        mapping[source_id] = document_id
    return mapping, created_storage_keys


async def _find_existing_imported_course(
    db: AsyncSession,
    tenant_id: UUID,
    source_course_id: str,
    title: str,
) -> Course | None:
    courses = (
        (
            await db.execute(
                select(Course).where(Course.tenant_id == tenant_id, Course.title == title)
            )
        )
        .scalars()
        .all()
    )
    for course in courses:
        transfer = (course.source_analysis or {}).get("tenant_transfer") or {}
        if transfer.get("source_course_id") == source_course_id:
            return course
    if courses:
        raise ValueError(f"A non-imported course with the same title already exists: {title}")
    return None


async def _import_course(
    db: AsyncSession,
    tenant_id: UUID,
    item: dict[str, Any],
    package_sha256: str,
    document_ids: dict[str, UUID],
) -> tuple[Course, bool]:
    snapshot = item["snapshot"]
    course_payload = snapshot["course"]
    source_course_id = str(item["source_course_id"])
    title = str(course_payload["title"])
    existing = await _find_existing_imported_course(db, tenant_id, source_course_id, title)
    if existing is not None:
        return existing, False

    source_document_manifest = snapshot.get("source_documents") or []
    transferred_document_manifest = [
        {
            "source_document_id": str(document["id"]),
            "source_family_id": str(document.get("source_family_id") or document["id"]),
            "target_document_id": str(document_ids[str(document["id"])]),
            "filename": document["filename"],
            "content_type": document["content_type"],
            "content_sha256": document["content_sha256"],
        }
        for document in source_document_manifest
    ]
    source_analysis = _remap_json_ids(dict(course_payload.get("source_analysis") or {}), document_ids)
    source_analysis["tenant_transfer"] = {
        "source_tenant_name": TENANT_NAME,
        "source_course_id": source_course_id,
        "source_release_version": int(item["source_release_version"]),
        "source_snapshot_sha256": item["source_snapshot_sha256"],
        "package_sha256": package_sha256,
        "source_documents": transferred_document_manifest,
        "document_links_pending": False,
    }
    mapped_course_document_ids = [
        str(document_ids[source_id])
        for source_id in course_payload.get("source_document_ids") or []
        if source_id in document_ids
    ]
    source_instruction_id = course_payload.get("source_instruction_id")
    source_instruction_version = course_payload.get("source_instruction_version_at")
    course = Course(
        id=uuid4(),
        tenant_id=tenant_id,
        title=title,
        description=course_payload.get("description") or "",
        status="published",
        delivery_type=course_payload.get("delivery_type") or "native",
        ai_generated=bool(course_payload.get("ai_generated")),
        source_instruction_id=document_ids.get(str(source_instruction_id)) if source_instruction_id else None,
        source_instruction_version_at=(
            datetime.fromisoformat(source_instruction_version)
            if source_instruction_version
            else None
        ),
        source_document_ids=mapped_course_document_ids,
        source_strategy=course_payload.get("source_strategy") or "single_topic",
        source_combination_goal=course_payload.get("source_combination_goal"),
        source_analysis=source_analysis,
        review_status="approved",
        reviewed_by=None,
        reviewed_at=None,
        review_comment="Перенесено из тестового контура; содержание и тесты сохранены без старых результатов.",
    )
    db.add(course)
    await db.flush()

    for module_payload in snapshot.get("modules") or []:
        module = Module(
            id=uuid4(),
            tenant_id=tenant_id,
            course_id=course.id,
            title=module_payload["title"],
            description=module_payload.get("description") or "",
            order_index=int(module_payload.get("order_index") or 0),
            ai_generated=bool(course.ai_generated),
        )
        db.add(module)
        await db.flush()
        for lesson_payload in module_payload.get("lessons") or []:
            lesson = Lesson(
                id=uuid4(),
                tenant_id=tenant_id,
                module_id=module.id,
                title=lesson_payload["title"],
                content_type=lesson_payload.get("content_type") or "text",
                content=lesson_payload.get("content"),
                duration_seconds=lesson_payload.get("duration_seconds"),
                order_index=int(lesson_payload.get("order_index") or 0),
                ai_generated=bool(course.ai_generated),
                source_document_ids=[
                    str(document_ids[source_id])
                    for source_id in lesson_payload.get("source_document_ids") or []
                    if source_id in document_ids
                ],
                source_references=_remap_json_ids(lesson_payload.get("source_references") or [], document_ids),
                source_validation_status=lesson_payload.get("source_validation_status") or "not_applicable",
            )
            db.add(lesson)
            await db.flush()
            for block_payload in lesson_payload.get("content_blocks") or []:
                db.add(
                    ContentBlock(
                        id=uuid4(),
                        lesson_id=lesson.id,
                        block_type=block_payload["block_type"],
                        content=block_payload.get("content"),
                        order_index=int(block_payload.get("order_index") or 0),
                        metadata_=block_payload.get("metadata"),
                    )
                )
            for quiz_payload in lesson_payload.get("quizzes") or []:
                quiz = Quiz(
                    id=uuid4(),
                    lesson_id=lesson.id,
                    tenant_id=tenant_id,
                    title=quiz_payload["title"],
                    pass_score=int(quiz_payload.get("pass_score") or 80),
                    time_limit=quiz_payload.get("time_limit"),
                    attempt_limit=int(quiz_payload.get("attempt_limit") or 3),
                    deferral_days=int(quiz_payload.get("deferral_days") or 7),
                    review_status="approved",
                    reviewed_by=None,
                    reviewed_at=None,
                )
                db.add(quiz)
                await db.flush()
                for question_payload in quiz_payload.get("questions") or []:
                    question = Question(
                        id=uuid4(),
                        quiz_id=quiz.id,
                        text=question_payload["text"],
                        type=question_payload["type"],
                        points=int(question_payload.get("points") or 1),
                        explanation=question_payload.get("explanation"),
                        order_index=int(question_payload.get("order_index") or 0),
                        pool_group=question_payload.get("pool_group"),
                    )
                    db.add(question)
                    await db.flush()
                    for choice_payload in question_payload.get("choices") or []:
                        db.add(
                            QuizChoice(
                                id=uuid4(),
                                question_id=question.id,
                                text=choice_payload["text"],
                                is_correct=bool(choice_payload.get("is_correct")),
                                order_index=int(choice_payload.get("order_index") or 0),
                            )
                        )
    await db.flush()
    await create_course_release(db, course, published_by=None)
    await db.flush()
    return course, True


async def _ensure_rules(
    db: AsyncSession,
    tenant_id: UUID,
    courses: dict[str, Course],
) -> int:
    positions = (
        (await db.execute(select(Position).where(Position.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    created = 0
    for position in positions:
        required_courses = [courses["microcredit_rules"]]
        if "эксперт" in position.name.casefold() or "оценщик" in position.name.casefold():
            required_courses.append(courses["expert_appraiser_instruction"])
        for course in required_courses:
            existing = await db.scalar(
                select(PositionCourse).where(
                    PositionCourse.tenant_id == tenant_id,
                    PositionCourse.position_id == position.id,
                    PositionCourse.course_id == course.id,
                )
            )
            if existing is None:
                db.add(
                    PositionCourse(
                        tenant_id=tenant_id,
                        position_id=position.id,
                        course_id=course.id,
                        required=True,
                    )
                )
                created += 1
    await db.flush()
    return created


async def _verify(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    result: dict[str, int] = {}
    for label, model in (
        ("users", User),
        ("departments", Department),
        ("positions", Position),
        ("documents", Document),
        ("courses", Course),
        ("content_releases", ContentRelease),
        ("modules", Module),
        ("lessons", Lesson),
        ("content_blocks", ContentBlock),
        ("quizzes", Quiz),
        ("questions", Question),
        ("quiz_choices", QuizChoice),
        ("position_course_rules", PositionCourse),
        ("enrollments", Enrollment),
    ):
        query = select(func.count()).select_from(model)
        if hasattr(model, "tenant_id"):
            query = query.where(model.tenant_id == tenant_id)
        elif model is ContentBlock:
            query = query.join(Lesson, Lesson.id == ContentBlock.lesson_id).where(
                Lesson.tenant_id == tenant_id
            )
        elif model is Question:
            query = query.join(Quiz, Quiz.id == Question.quiz_id).where(Quiz.tenant_id == tenant_id)
        elif model is QuizChoice:
            query = (
                query.join(Question, Question.id == QuizChoice.question_id)
                .join(Quiz, Quiz.id == Question.quiz_id)
                .where(Quiz.tenant_id == tenant_id)
            )
        result[label] = int(await db.scalar(query) or 0)
    result["students"] = int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == tenant_id, User.role == "student")
        )
        or 0
    )
    return result


async def run(args: argparse.Namespace) -> None:
    package_path = Path(args.course_package).resolve()
    staff_path = Path(args.staff_file).resolve()
    source_document_dir = Path(args.source_document_dir).resolve()
    package = _load_package(package_path)
    source_paths = _validate_source_files(package, source_document_dir)
    parsed = parse_upload(staff_path.name, staff_path.read_bytes())
    if parsed.invalid_rows or len(parsed.rows) != 12:
        raise ValueError(
            f"Staff file must parse as 12 valid rows and no invalid rows; got {len(parsed.rows)} valid, "
            f"{len(parsed.invalid_rows)} invalid"
        )
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "tenant": TENANT_NAME,
                    "staff_rows": len(parsed.rows),
                    "departments": sorted({row.department for row in parsed.rows}),
                    "course_titles": [item["snapshot"]["course"]["title"] for item in package["courses"]],
                    "source_documents": [path.name for path in source_paths.values()],
                    "package_sha256": _package_sha256(package_path),
                },
                ensure_ascii=False,
            )
        )
        return
    if args.confirmation != CONFIRMATION:
        raise ValueError(f"--confirmation must equal {CONFIRMATION}")
    raw_url = os.getenv(args.database_url_env)
    if not raw_url:
        raise ValueError(f"{args.database_url_env} is not configured")

    engine = create_async_engine(_async_url(raw_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    created_storage_keys: list[str] = []
    async with session_factory() as db:
        try:
            await db.execute(text("SELECT set_config('app.is_superadmin', 'true', true)"))
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
                {"lock_name": f"tenant-import:{TENANT_SLUG}"},
            )
            tenant = await _ensure_tenant(db)
            await _set_tenant_context(db, tenant.id)
            actor = await _ensure_import_actor(db, tenant.id)
            document_ids, created_storage_keys = await _ensure_source_documents(
                db,
                tenant.id,
                actor.id,
                package,
                source_paths,
            )
            preview = await build_preview(db, tenant.id, parsed)
            staff_result = await commit_import(
                db,
                tenant.id,
                parsed,
                commit_changes=False,
                apply_rules=False,
            )
            courses_by_kind: dict[str, Course] = {}
            imported_courses = 0
            package_hash = _package_sha256(package_path)
            for item in package["courses"]:
                course, created = await _import_course(
                    db,
                    tenant.id,
                    item,
                    package_hash,
                    document_ids,
                )
                courses_by_kind[_course_kind(course.title)] = course
                imported_courses += int(created)
            rules_created = await _ensure_rules(db, tenant.id, courses_by_kind)
            learner_ids = list(
                (
                    await db.execute(
                        select(User.id).where(
                            User.tenant_id == tenant.id,
                            User.role == "student",
                            User.is_active.is_(True),
                        )
                    )
                ).scalars()
            )
            rule_result = await apply_rules_for_users(db, learner_ids)
            counts = await _verify(db, tenant.id)
            if counts != EXPECTED_COUNTS:
                raise ValueError(
                    "Import postconditions failed before commit: "
                    f"expected {EXPECTED_COUNTS}, got {counts}"
                )
            await db.commit()
        except Exception:
            await db.rollback()
            storage = get_storage()
            cleanup_failures: list[str] = []
            for storage_key in created_storage_keys:
                try:
                    storage.delete_bytes(storage_key)
                except Exception:
                    cleanup_failures.append(storage_key)
            if cleanup_failures:
                print(
                    json.dumps(
                        {
                            "status": "rollback_storage_cleanup_required",
                            "storage_keys": cleanup_failures,
                        }
                    ),
                    file=sys.stderr,
                )
            raise
        await db.execute(text("SELECT set_config('app.is_superadmin', 'true', true)"))
        await _set_tenant_context(db, tenant.id)
        counts = await _verify(db, tenant.id)
        print(
            json.dumps(
                {
                    "mode": "applied",
                    "tenant_id": str(tenant.id),
                    "preview": preview.summary,
                    "staff": staff_result,
                    "courses_created": imported_courses,
                    "rules_created": rules_created,
                    "enrollments_added": rule_result.added,
                    "enrollments_removed": rule_result.removed,
                    "counts": counts,
                    "package_sha256": package_hash,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-package", required=True)
    parser.add_argument("--staff-file", required=True)
    parser.add_argument("--source-document-dir", required=True)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
