"""Methodologist routes for the document's only editorial review."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.source_editorial_review.domain import ReviewCommand, ReviewConflictError
from app.modules.source_editorial_review.service import (
    apply_command,
    history,
    owned_document,
    read_approval,
    read_state,
    review_enabled,
    review_view,
    statuses,
)

router = APIRouter()
Actor = Annotated[User, Depends(require_role("methodologist"))]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/editorial-review/status")
async def source_review_status(db: Database, user: Actor, document_ids: Annotated[list[UUID], Query(max_length=5)]) -> dict[str, Any]:
    enabled = review_enabled()
    return {"required": enabled, "documents": await statuses(db, UUID(str(user.tenant_id)), document_ids) if enabled else {}}


def _require_enabled() -> None:
    if not review_enabled():
        raise HTTPException(status_code=404, detail="Source review is disabled")


def _conflict(error: ReviewConflictError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": str(error)})


@router.get("/{doc_id}/editorial-review")
async def get_review(doc_id: UUID, db: Database, user: Actor) -> dict[str, Any]:
    _require_enabled()
    tenant = UUID(str(user.tenant_id))
    doc = await owned_document(db, tenant, doc_id)
    rows = await history(db, tenant, doc_id)
    try:
        return review_view(doc, rows, read_state(rows, doc.content_sha256))
    except ReviewConflictError as error:
        raise _conflict(error) from error


@router.get("/{doc_id}/editorial-review/assets/{asset_id}")
async def get_review_asset(doc_id: UUID, asset_id: str, preparation_sha256: str,
                           db: Database, user: Actor) -> Response:
    from app.modules.source_preparation.assets import preview_asset

    return await preview_asset(db, UUID(str(user.tenant_id)), doc_id, asset_id, preparation_sha256)


@router.post("/{doc_id}/editorial-review")
async def change_review(doc_id: UUID, command: ReviewCommand, db: Database, user: Actor) -> dict[str, Any]:
    _require_enabled()
    tenant = UUID(str(user.tenant_id))
    doc = await owned_document(db, tenant, doc_id, lock=True)
    try:
        rows, state, event, dispatch = await apply_command(db, doc, UUID(str(user.id)), command)
        response = review_view(doc, rows, state, event)
    except ReviewConflictError as error:
        raise _conflict(error) from error
    if dispatch:
        # Persist the command before dispatch. A lost acknowledgement can replay
        # the exact key; only one delivery can claim the queued event.
        await db.commit()
        from app.core.celery_app import celery_app

        try:
            celery_app.send_task("documents.editorial_review", args=[str(tenant), str(doc_id), str(event.id)],
                                 queue="documents", retry=False)
        except Exception as error:
            raise HTTPException(status_code=503, detail={"code": "source_review_dispatch_unknown"}) from error
    return response


@router.get("/{doc_id}/editorial-review/{approval_id}")
async def get_review_snapshot(doc_id: UUID, approval_id: UUID, db: Database, user: Actor) -> dict[str, Any]:
    # Already-pinned course citations remain readable if new reviews are disabled.
    tenant = UUID(str(user.tenant_id))
    doc = await owned_document(db, tenant, doc_id)
    try:
        event, state = await read_approval(db, tenant, doc, approval_id)
        return review_view(doc, await history(db, tenant, doc_id, event.sequence), state)
    except ReviewConflictError as error:
        raise _conflict(error) from error
