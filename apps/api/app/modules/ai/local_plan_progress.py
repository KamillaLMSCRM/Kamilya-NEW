"""Explicit process-local planner progress scope tied to native POST reservations."""
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.modules.ai.llm_client import _native_post_reservation
from app.modules.ai.local_post_reservation_experiment import LocalPostReservations

_active: ContextVar[object | None] = ContextVar("local_plan_progress", default=None)


@contextmanager
def local_plan_progress_scope(budget: LocalPostReservations) -> Iterator[None]:
    scope = _native_post_reservation.get()
    if (type(budget) is not LocalPostReservations or scope is None or scope.closed
            or getattr(scope.reserve, "__self__", None) is not budget or _active.get() is not None):
        raise ValueError("local_plan_progress_requires_reservation")
    token = _active.set(scope)
    try:
        yield
    finally:
        _active.reset(token)


def local_plan_progress_enabled() -> bool:
    scope = _active.get()
    current = _native_post_reservation.get()
    return scope is not None and current is not None and current is scope and not current.closed


def target_state(source_identity: str, target_id: str, plan: dict[str, Any], audit: dict[str, Any]) -> str:
    """Digest owned target, source identity, linked obligations/facets and target audit."""
    import hashlib
    import json
    targets = [row for row in plan.get("targets", []) if row.get("id") == target_id]
    if len(targets) != 1:
        raise ValueError("local_plan_target_identity_invalid")
    obligations = [row for row in plan.get("material_obligations", []) if target_id in row.get("target_ids", [])]
    facets = [row for row in plan.get("qualification_facets", [])
              if target_id in row.get("target_ids", []) or target_id in row.get("branch_target_ids", [])]
    facet_ids = {row.get("id") for row in facets}
    verdicts = [row for row in audit.get("target_verdicts", []) if row.get("target_id") == target_id]
    facet_verdicts = [row for row in audit.get("facet_verdicts", []) if row.get("facet_id") in facet_ids]
    payload = [source_identity, targets, obligations, facets, verdicts, facet_verdicts]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class TargetTombstones:
    """A no-op remains tombstoned even after a later ABA return to the same state."""
    def __init__(self) -> None:
        self._states: set[tuple[str, str]] = set()
        self._observed: set[tuple[str, str]] = set()

    def record(self, target_id: str, before: str, after: str) -> None:
        self._observed.add((target_id, before))
        if (target_id, after) in self._observed:
            self._states.add((target_id, after))
        self._observed.add((target_id, after))

    def blocked(self, target_id: str, state: str) -> bool:
        return (target_id, state) in self._states


def validate_tombstoned_patch(payload: dict[str, Any], blocked_ids: set[str], plan: dict[str, Any]) -> None:
    """Reject target edits and shared-obligation edits touching tombstoned owners."""
    rows = payload.get("targets", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get("id") in blocked_ids for row in rows):
        raise ValueError("local_plan_tombstone_scope_violation")
    old = {row["id"]: row for row in plan.get("material_obligations", [])}
    proposals = payload.get("material_obligations", [])
    if not isinstance(proposals, list):
        raise ValueError("local_plan_tombstone_scope_violation")
    for row in proposals:
        if not isinstance(row, dict):
            raise ValueError("local_plan_tombstone_scope_violation")
        previous = old.get(row.get("id"), {})
        owners = set(row.get("target_ids", [])) | set(previous.get("target_ids", []))
        if owners & blocked_ids and previous != row:
            raise ValueError("local_plan_tombstone_scope_violation")

    # Facet payloads are partial patches: omission is retained by the native
    # merge. Any explicit change to either old or new ownership is forbidden.
    old_facets = {row["id"]: row for row in plan.get("qualification_facets", [])}
    facets = payload.get("qualification_facets", [])
    if not isinstance(facets, list):
        raise ValueError("local_plan_tombstone_scope_violation")
    for row in facets:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("local_plan_tombstone_scope_violation")
        previous = old_facets.get(row["id"], {})
        owners = (set(row.get("target_ids", [])) | set(row.get("branch_target_ids", [])) |
                  set(previous.get("target_ids", [])) | set(previous.get("branch_target_ids", [])))
        if owners & blocked_ids and previous != row:
            raise ValueError("local_plan_tombstone_scope_violation")
