"""Shared SQL contract for the head of an enrollment occurrence chain."""

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.enrollment import Enrollment


def is_current_occurrence() -> ColumnElement[bool]:
    """Return a tenant-safe predicate that excludes retained predecessors.

    Completed predecessors remain immutable, so their status cannot be changed
    merely to hide them from operational views.  A row is historical once a
    later occurrence points to it through ``previous_enrollment_id``.
    """

    successor = aliased(Enrollment)
    return ~exists(
        select(1).where(
            successor.previous_enrollment_id == Enrollment.id,
            successor.tenant_id == Enrollment.tenant_id,
            successor.user_id == Enrollment.user_id,
            successor.course_id == Enrollment.course_id,
        )
    )
