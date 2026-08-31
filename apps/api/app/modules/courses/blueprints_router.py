"""HTTP seam for versioned industry course blueprints."""

# FastAPI dependency injection intentionally uses callable defaults.
# ruff: noqa: B008

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.courses.blueprint_schemas import (
    BlueprintAdaptationRequest,
    BlueprintAdaptationSnapshot,
    BlueprintAlreadyInstantiatedDetail,
    BlueprintInstantiationRequest,
    BlueprintInstantiationResponse,
    BlueprintLocale,
    CourseBlueprintResponse,
)
from app.modules.courses.blueprint_service import (
    BlueprintAlreadyInstantiatedError,
    BlueprintContentConflictError,
    BlueprintNotFoundError,
    BlueprintSourceDocumentError,
    adaptation_snapshot,
    get_catalog,
    get_catalog_item,
    instantiate_blueprint,
    update_blueprint_adaptation,
)
from app.modules.courses.models import Course

router = APIRouter(
    dependencies=[Depends(require_tenant_user())],
    tags=["course-blueprints"],
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Course blueprint not found")


def _adaptation_conflict(error: BlueprintContentConflictError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "blueprint_adaptation_conflict", "message": error.message},
    )


async def _include_financial_blueprints(db: AsyncSession, user: User) -> bool:
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise _not_found()
    return bool(tenant.is_financial_organization)


@router.get("/course-blueprints", response_model=list[CourseBlueprintResponse])
async def list_course_blueprints(
    locale: BlueprintLocale = Query("ru"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
) -> list[CourseBlueprintResponse]:
    return get_catalog(
        locale,
        include_financial=await _include_financial_blueprints(db, user),
    )


@router.get("/course-blueprints/{blueprint_id}", response_model=CourseBlueprintResponse)
async def get_course_blueprint(
    blueprint_id: str,
    locale: BlueprintLocale = Query("ru"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
) -> CourseBlueprintResponse:
    try:
        return get_catalog_item(
            blueprint_id,
            locale,
            include_financial=await _include_financial_blueprints(db, user),
        )
    except BlueprintNotFoundError as error:
        raise _not_found() from error


@router.post(
    "/course-blueprints/{blueprint_id}/instantiate",
    response_model=BlueprintInstantiationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": BlueprintAlreadyInstantiatedDetail}},
)
async def instantiate_course_blueprint(
    blueprint_id: str,
    payload: BlueprintInstantiationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
) -> BlueprintInstantiationResponse:
    from app.core.trial_limits import assert_can_create_courses

    await assert_can_create_courses(db, user.tenant_id)
    try:
        course, response = await instantiate_blueprint(
            db,
            blueprint_id=blueprint_id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            request=payload,
        )
    except BlueprintNotFoundError as error:
        raise _not_found() from error
    except BlueprintAlreadyInstantiatedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "blueprint_already_instantiated",
                "message": "This blueprint version already has an active course",
                "existing_course_id": str(error.course_id),
            },
        ) from error
    except BlueprintSourceDocumentError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "blueprint_source_documents_not_found",
                "message": "One or more source documents are unavailable",
            },
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    await log_action(
        db,
        user.tenant_id,
        "instantiate",
        "course_blueprint",
        resource_id=str(course.id),
        user_id=user.id,
        details={
            "blueprint_id": response.blueprint_id,
            "blueprint_version": response.blueprint_version,
            "locale": response.locale,
            "readiness_percent": response.readiness_percent,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return response


async def _tenant_blueprint_course(
    db: AsyncSession,
    course_id: UUID,
    tenant_id: UUID,
) -> Course:
    course = (
        await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get(
    "/courses/{course_id}/blueprint-adaptation",
    response_model=BlueprintAdaptationSnapshot,
)
async def get_blueprint_adaptation(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
) -> BlueprintAdaptationSnapshot:
    course = await _tenant_blueprint_course(db, course_id, user.tenant_id)
    try:
        return adaptation_snapshot(course)
    except BlueprintNotFoundError as error:
        raise _not_found() from error


@router.put(
    "/courses/{course_id}/blueprint-adaptation",
    response_model=BlueprintInstantiationResponse,
)
async def replace_blueprint_adaptation(
    course_id: UUID,
    payload: BlueprintAdaptationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
) -> BlueprintInstantiationResponse:
    course = await _tenant_blueprint_course(db, course_id, user.tenant_id)
    try:
        response = await update_blueprint_adaptation(db, course=course, request=payload)
    except BlueprintNotFoundError as error:
        raise _not_found() from error
    except BlueprintSourceDocumentError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "blueprint_source_documents_not_found",
                "message": "One or more source documents are unavailable",
            },
        ) from error
    except BlueprintContentConflictError as error:
        raise _adaptation_conflict(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    await log_action(
        db,
        user.tenant_id,
        "adapt",
        "course_blueprint",
        resource_id=str(course.id),
        user_id=user.id,
        details={
            "blueprint_id": response.blueprint_id,
            "blueprint_version": response.blueprint_version,
            "readiness_percent": response.readiness_percent,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return response
