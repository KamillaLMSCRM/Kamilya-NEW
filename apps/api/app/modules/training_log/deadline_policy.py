"""Deadline policy shared by the training-log SQL and row read model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import case, func, or_
from sqlalchemy.sql.elements import ColumnElement

DeadlineStatus = Literal[
    "not_applicable",
    "active",
    "overdue",
    "completed_on_time",
    "completed_late",
]


def classify_deadline(
    *,
    due_at: datetime | None,
    completed_at: datetime | None,
    now: datetime | None = None,
    enrollment_status: str = "enrolled",
    eligible: bool = True,
) -> DeadlineStatus:
    """Classify one enrollment against its effective immutable cycle deadline."""
    if due_at is None or not eligible:
        return "not_applicable"
    if completed_at is not None:
        return "completed_late" if completed_at > due_at else "completed_on_time"
    if enrollment_status == "completed":
        # Completion is known, but its punctuality cannot be reconstructed.
        return "not_applicable"
    current_time = now or datetime.now(UTC)
    return "overdue" if due_at < current_time else "active"


def deadline_status_sql(
    *,
    due_at: ColumnElement[Any],
    completed_at: ColumnElement[Any],
    enrollment_status: ColumnElement[Any],
    eligible: ColumnElement[bool],
) -> ColumnElement[str]:
    """One DB-clock expression for row status, filters and counts."""
    return case(
        (or_(due_at.is_(None), eligible.is_not(True)), "not_applicable"),
        (completed_at > due_at, "completed_late"),
        (completed_at.is_not(None), "completed_on_time"),
        (enrollment_status == "completed", "not_applicable"),
        (due_at < func.now(), "overdue"),
        else_="active",
    )
