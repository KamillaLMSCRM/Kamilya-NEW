"""Named, active-role permission checks for domain capabilities."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_active_user

# FastAPI dependency factories intentionally call Depends in signatures.
# Ruff's B008 rule does not understand this framework contract.
# ruff: noqa: B008


@dataclass(frozen=True)
class _CourseApprovalPermissions:
    CONFIGURE: str = "course_approval.configure"
    REQUEST: str = "course_approval.request"
    REVIEW: str = "course_approval.review"
    PUBLISH: str = "course_approval.publish"
    AUDIT_READ: str = "course_approval.audit_read"


COURSE_APPROVAL_PERMISSIONS = _CourseApprovalPermissions()

# Keep this table intentionally explicit.  It evaluates the active role, never
# the union of roles assigned to an account.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({COURSE_APPROVAL_PERMISSIONS.CONFIGURE, COURSE_APPROVAL_PERMISSIONS.AUDIT_READ}),
    "methodologist": frozenset(
        {
            COURSE_APPROVAL_PERMISSIONS.CONFIGURE,
            COURSE_APPROVAL_PERMISSIONS.REQUEST,
            COURSE_APPROVAL_PERMISSIONS.REVIEW,
            COURSE_APPROVAL_PERMISSIONS.PUBLISH,
            COURSE_APPROVAL_PERMISSIONS.AUDIT_READ,
        }
    ),
    "student": frozenset(),
    "superadmin": frozenset(),
}


def role_has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require_permission(permission: str) -> Callable[..., Awaitable[Any]]:
    async def checker(user: Any = Depends(get_current_active_user)) -> Any:
        if not role_has_permission(user.role, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required")
        return user

    return checker
