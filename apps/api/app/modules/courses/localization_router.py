"""Authoring and learner routes for native course language editions."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, get_current_user, require_role
from app.core.db import get_db
from app.models.courses import Course
from app.models.users import User
from app.modules.courses.access import require_course_access
from app.modules.courses.localizations import (
    POLICY_KEY,
    Language,
    LanguagePolicy,
    SaveEdition,
    author_snapshot,
    editions,
    finish_edition_generation,
    learner_snapshot,
    read_policy,
    save_edition,
    source_fields,
    translate_fields,
    validate_edition,
    visible_edition,
)

router = APIRouter(prefix="/courses/{course_id}/languages", tags=["course languages"])
Database = Annotated[AsyncSession, Depends(get_db)]
Author = Annotated[User, Depends(require_role("superadmin", "methodologist"))]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("")
async def course_languages(
    course_id: UUID, db: Database, user: CurrentUser, language: Language | None = None,
) -> dict[str, Any]:
    course = await require_course_access(db, course_id, user)
    if not read_policy(course) or course.delivery_type != "native":
        return {"primary": None, "available": [], "content": {}}
    snapshot = await learner_snapshot(db, course, user) if user.role == "student" else await author_snapshot(db, course)
    policy = read_policy(course, snapshot)
    assert policy is not None
    sha, _ = source_fields(snapshot)
    translations = await editions(db, course, sha, published=True)
    result: dict[str, str] = next((row["content"] for row in translations if row["language"] == language), {})
    return {"primary": policy.primary, "available": [policy.primary, *(row["language"] for row in translations)],
            "content": visible_edition(result)}


async def _author_course(db: AsyncSession, course_id: UUID, user: User, *, locked: bool = False) -> Course:
    query = select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id,
                                 Course.delivery_type == "native")
    course = await db.scalar(query.with_for_update() if locked else query)
    if course is None:
        raise HTTPException(404, detail="native_course_not_found")
    return course


@router.get("/editor")
async def language_editor(course_id: UUID, db: Database, user: Author) -> dict[str, Any]:
    course = await _author_course(db, course_id, user)
    snapshot = await author_snapshot(db, course)
    sha, fields = source_fields(snapshot)
    rows = await editions(db, course, sha, published=False)
    return {"policy": read_policy(course), "source_sha256": sha, "source": fields,
            "editions": {row["language"]: {"content": row["content"], "approved": bool(row["approved_at"]),
                                           "pending": row["generation_pending"]} for row in rows}}


@router.put("/editor")
async def set_language_policy(course_id: UUID, payload: LanguagePolicy, db: Database, user: Author) -> LanguagePolicy:
    course = await _author_course(db, course_id, user, locked=True)
    prior = read_policy(course)
    if prior and prior.primary != payload.primary:
        raise HTTPException(409, detail="course_primary_language_already_set")
    cast(Any, course).source_analysis = {**(course.source_analysis or {}), POLICY_KEY: payload.model_dump()}
    return payload


def _target(course: Course, language: Language) -> LanguagePolicy:
    policy = read_policy(course)
    if not policy or language == policy.primary or language not in policy.requested:
        raise HTTPException(422, detail="translation_language_not_requested")
    return policy


@router.put("/editor/{language}")
async def save_language(
    course_id: UUID, language: Language, payload: SaveEdition, db: Database, user: Author,
) -> dict[str, bool]:
    course = await _author_course(db, course_id, user, locked=True)
    policy = _target(course, language)
    sha, fields = source_fields(await author_snapshot(db, course))
    if sha != payload.source_sha256:
        raise HTTPException(409, detail="translation_source_changed")
    validate_edition(fields, payload.content)
    if not await save_edition(db, course, policy, sha, language, payload.content, approve=payload.approve):
        raise HTTPException(409, detail="translation_already_approved")
    return {"approved": payload.approve}


@router.post("/editor/{language}/generate")
async def generate_language(course_id: UUID, language: Language, db: Database, user: Author) -> dict[str, Any]:
    course = await _author_course(db, course_id, user, locked=True)
    policy = _target(course, language)
    sha, fields = source_fields(await author_snapshot(db, course))
    if not fields or sum(map(len, fields.values())) > 36_000:
        raise HTTPException(422, detail="translation_requires_manual_editor")
    existing = next((row for row in await editions(db, course, sha, published=False)
                     if row["language"] == language), None)
    if existing and (existing["generation_pending"] or existing["content"]):
        return {"content": existing["content"], "pending": existing["generation_pending"]}
    claimed = await save_edition(db, course, policy, sha, language, {}, approve=False, pending=True)
    if not claimed:
        raise HTTPException(409, detail="translation_already_claimed")
    await db.commit()
    try:
        content = await translate_fields(fields, language, cast(UUID, user.tenant_id))
        validate_edition(fields, content)
    except (ValueError, HTTPException):
        await _set_tenant_security_context(db, str(user.tenant_id))
        await finish_edition_generation(db, course, sha, language, {})
        return {"content": {}, "pending": False, "error": "translation_model_output_invalid"}
    except Exception:
        return {"content": {}, "pending": True, "error": "translation_outcome_unknown"}
    await _set_tenant_security_context(db, str(user.tenant_id))
    if not await finish_edition_generation(db, course, sha, language, content):
        raise HTTPException(409, detail="translation_edited_concurrently")
    return {"content": content, "pending": False}
