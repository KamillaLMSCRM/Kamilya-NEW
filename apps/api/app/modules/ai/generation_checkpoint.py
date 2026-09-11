"""Tenant-scoped repository for resumable AI generation before course creation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

_MAX_KEY_LENGTH = 160


class AIGenerationCheckpointError(RuntimeError):
    """Stable, sanitized failure for generation checkpoint persistence."""


class AIGenerationIncompleteError(AIGenerationCheckpointError):
    """Raised when a caller tries to finalize an incomplete generation."""


@dataclass(frozen=True)
class PlannedLesson:
    module_key: str
    lesson_key: str
    module_order: int
    lesson_order: int


@dataclass(frozen=True)
class GenerationPlan:
    generation_key: str
    plan_revision: str
    source_job_id: str
    plan_payload: Mapping[str, Any]
    lessons: tuple[PlannedLesson, ...]


@dataclass(frozen=True)
class MissingGenerationItem:
    module_key: str
    lesson_key: str
    module_order: int
    lesson_order: int
    stage: str


@dataclass(frozen=True)
class ClaimedGenerationItem(MissingGenerationItem):
    lease_owner: str
    attempt_count: int


@dataclass(frozen=True)
class GenerationCheckpointSnapshot:
    module_key: str
    lesson_key: str
    module_order: int
    lesson_order: int
    content_payload: Mapping[str, Any] | None
    review_payload: Mapping[str, Any] | None
    assessment_payload: Mapping[str, Any] | None


def _row_value(row: Any, name: str, index: int) -> Any:
    mapping = getattr(row, "_mapping", None)
    return mapping[name] if mapping is not None else row[index]


def _first(result: Any) -> Any:
    return result.first()


def _json_payload(payload: Mapping[str, Any], *, error: str) -> str:
    if not isinstance(payload, Mapping):
        raise AIGenerationCheckpointError(error)
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise AIGenerationCheckpointError(error) from exc


def _key(value: str, *, error: str) -> str:
    if not isinstance(value, str) or not 0 < len(value.strip()) <= _MAX_KEY_LENGTH:
        raise AIGenerationCheckpointError(error)
    return value


def _lease_duration(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 900:
        raise AIGenerationCheckpointError("invalid_lease_duration")
    return value


def _stage(value: str) -> str:
    if value not in {"content", "review", "assessment"}:
        raise AIGenerationCheckpointError("invalid_checkpoint_stage")
    return value


def _persisted_payload(value: Any, *, error: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIGenerationCheckpointError(error) from exc
    if not isinstance(value, Mapping):
        raise AIGenerationCheckpointError(error)
    return value


class AIGenerationCheckpointRepository:
    """Use inside a caller-owned transaction with explicit tenant context."""

    async def _set_tenant(self, session: Any, tenant_id: str) -> None:
        await session.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})

    async def create_plan(
        self,
        session: Any,
        *,
        tenant_id: str,
        generation_key: str,
        plan_revision: str,
        source_job_id: str,
        plan_payload: Mapping[str, Any],
        lessons: Sequence[PlannedLesson],
    ) -> GenerationPlan:
        generation_key = _key(generation_key, error="invalid_generation_key")
        plan_revision = _key(plan_revision, error="invalid_plan_revision")
        source_job_id = _key(source_job_id, error="invalid_source_job_id")
        serialized_plan = _json_payload(plan_payload, error="invalid_plan_payload")
        normalized_lessons = tuple(lessons)
        if not normalized_lessons:
            raise AIGenerationCheckpointError("empty_generation_plan")
        identities: set[tuple[str, str]] = set()
        for lesson in normalized_lessons:
            if not isinstance(lesson, PlannedLesson):
                raise AIGenerationCheckpointError("invalid_planned_lesson")
            _key(lesson.module_key, error="invalid_module_key")
            _key(lesson.lesson_key, error="invalid_lesson_key")
            if lesson.module_order < 0 or lesson.lesson_order < 0:
                raise AIGenerationCheckpointError("invalid_lesson_order")
            identity = (lesson.module_key, lesson.lesson_key)
            if identity in identities:
                raise AIGenerationCheckpointError("duplicate_planned_lesson")
            identities.add(identity)

        await self._set_tenant(session, tenant_id)
        lineage = await session.execute(
            text("SELECT id FROM ai_jobs WHERE id = :source_job_id AND tenant_id = CAST(:tenant_id AS uuid)"),
            {"tenant_id": str(tenant_id), "source_job_id": source_job_id},
        )
        if _first(lineage) is None:
            raise AIGenerationCheckpointError("source_job_not_found")
        inserted = await session.execute(
            text("""
                INSERT INTO ai_generation_runs (
                    tenant_id, generation_key, plan_revision, source_job_id, plan_payload
                ) VALUES (
                    CAST(:tenant_id AS uuid), :generation_key, :plan_revision, :source_job_id,
                    CAST(:plan_payload AS jsonb)
                )
                ON CONFLICT (tenant_id, generation_key) DO NOTHING
                RETURNING id
            """),
            {
                "tenant_id": str(tenant_id), "generation_key": generation_key,
                "plan_revision": plan_revision, "source_job_id": source_job_id,
                "plan_payload": serialized_plan,
            },
        )
        run = _first(inserted)
        if run is not None:
            run_id = _row_value(run, "id", 0)
            for lesson in normalized_lessons:
                await session.execute(
                    text("""
                        INSERT INTO ai_generation_lesson_checkpoints (
                            tenant_id, generation_run_id, module_key, lesson_key, module_order, lesson_order
                        ) VALUES (
                            CAST(:tenant_id AS uuid), CAST(:generation_run_id AS uuid), :module_key,
                            :lesson_key, :module_order, :lesson_order
                        )
                    """),
                    {
                        "tenant_id": str(tenant_id), "generation_run_id": str(run_id),
                        "module_key": lesson.module_key, "lesson_key": lesson.lesson_key,
                        "module_order": lesson.module_order, "lesson_order": lesson.lesson_order,
                    },
                )
        loaded = await self.load_plan(session, tenant_id=tenant_id, generation_key=generation_key)
        if (
            loaded.plan_revision != plan_revision
            or loaded.source_job_id != source_job_id
            or _json_payload(loaded.plan_payload, error="invalid_persisted_plan_payload") != serialized_plan
            or loaded.lessons != normalized_lessons
        ):
            raise AIGenerationCheckpointError("generation_plan_conflict")
        return loaded

    async def load_plan(self, session: Any, *, tenant_id: str, generation_key: str) -> GenerationPlan:
        generation_key = _key(generation_key, error="invalid_generation_key")
        await self._set_tenant(session, tenant_id)
        run_result = await session.execute(
            text("""
                SELECT id, plan_revision, source_job_id, plan_payload
                FROM ai_generation_runs
                WHERE tenant_id = CAST(:tenant_id AS uuid) AND generation_key = :generation_key
            """),
            {"tenant_id": str(tenant_id), "generation_key": generation_key},
        )
        run = _first(run_result)
        if run is None:
            raise AIGenerationCheckpointError("generation_plan_not_found")
        payload = _row_value(run, "plan_payload", 3)
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, Mapping):
            raise AIGenerationCheckpointError("invalid_persisted_plan_payload")
        lessons_result = await session.execute(
            text("""
                SELECT module_key, lesson_key, module_order, lesson_order
                FROM ai_generation_lesson_checkpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid) AND generation_run_id = CAST(:generation_run_id AS uuid)
                ORDER BY module_order ASC, lesson_order ASC, module_key ASC, lesson_key ASC
            """),
            {"tenant_id": str(tenant_id), "generation_run_id": str(_row_value(run, "id", 0))},
        )
        return GenerationPlan(
            generation_key=generation_key,
            plan_revision=_row_value(run, "plan_revision", 1),
            source_job_id=_row_value(run, "source_job_id", 2),
            plan_payload=payload,
            lessons=tuple(
                PlannedLesson(
                    module_key=_row_value(row, "module_key", 0), lesson_key=_row_value(row, "lesson_key", 1),
                    module_order=_row_value(row, "module_order", 2), lesson_order=_row_value(row, "lesson_order", 3),
                )
                for row in lessons_result.fetchall()
            ),
        )

    async def checkpoint_content(self, session: Any, *, tenant_id: str, generation_key: str, module_key: str, lesson_key: str, content_payload: Mapping[str, Any], lease_owner: str | None = None) -> None:
        await self._checkpoint(
            session, tenant_id=tenant_id, generation_key=generation_key, module_key=module_key,
            lesson_key=lesson_key, payload=content_payload, column="content", lease_owner=lease_owner,
        )

    async def checkpoint_review(self, session: Any, *, tenant_id: str, generation_key: str, module_key: str, lesson_key: str, review_payload: Mapping[str, Any], lease_owner: str | None = None) -> None:
        await self._checkpoint(
            session, tenant_id=tenant_id, generation_key=generation_key, module_key=module_key,
            lesson_key=lesson_key, payload=review_payload, column="review", lease_owner=lease_owner,
        )

    async def load_checkpoints(
        self, session: Any, *, tenant_id: str, generation_key: str
    ) -> tuple[GenerationCheckpointSnapshot, ...]:
        generation_key = _key(generation_key, error="invalid_generation_key")
        await self._set_tenant(session, tenant_id)
        result = await session.execute(
            text("""
                SELECT checkpoint.module_key, checkpoint.lesson_key, checkpoint.module_order,
                       checkpoint.lesson_order, checkpoint.content_status, checkpoint.review_status,
                       checkpoint.assessment_status, checkpoint.content_payload, checkpoint.review_payload,
                       checkpoint.assessment_payload
                FROM ai_generation_lesson_checkpoints AS checkpoint
                JOIN ai_generation_runs AS run ON run.id = checkpoint.generation_run_id
                WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                  AND run.tenant_id = checkpoint.tenant_id
                  AND run.generation_key = :generation_key
                ORDER BY checkpoint.module_order ASC, checkpoint.lesson_order ASC,
                         checkpoint.module_key ASC, checkpoint.lesson_key ASC
            """),
            {"tenant_id": str(tenant_id), "generation_key": generation_key},
        )
        snapshots: list[GenerationCheckpointSnapshot] = []
        for row in result.fetchall():
            content_status = _row_value(row, "content_status", 4)
            review_status = _row_value(row, "review_status", 5)
            assessment_status = _row_value(row, "assessment_status", 6)
            content_payload = _persisted_payload(
                _row_value(row, "content_payload", 7), error="invalid_persisted_content_payload"
            )
            review_payload = _persisted_payload(
                _row_value(row, "review_payload", 8), error="invalid_persisted_review_payload"
            )
            assessment_payload = _persisted_payload(
                _row_value(row, "assessment_payload", 9), error="invalid_persisted_assessment_payload"
            )
            if content_status == "completed" and content_payload is None:
                raise AIGenerationCheckpointError("invalid_persisted_content_payload")
            if review_status == "completed" and review_payload is None:
                raise AIGenerationCheckpointError("invalid_persisted_review_payload")
            if assessment_status == "completed" and assessment_payload is None:
                raise AIGenerationCheckpointError("invalid_persisted_assessment_payload")
            snapshots.append(
                GenerationCheckpointSnapshot(
                    module_key=_row_value(row, "module_key", 0),
                    lesson_key=_row_value(row, "lesson_key", 1),
                    module_order=_row_value(row, "module_order", 2),
                    lesson_order=_row_value(row, "lesson_order", 3),
                    content_payload=content_payload,
                    review_payload=review_payload,
                    assessment_payload=assessment_payload,
                )
            )
        return tuple(snapshots)

    async def checkpoint_assessment(self, session: Any, *, tenant_id: str, generation_key: str, module_key: str, lesson_key: str, assessment_payload: Mapping[str, Any], lease_owner: str | None = None) -> None:
        await self._checkpoint(
            session, tenant_id=tenant_id, generation_key=generation_key, module_key=module_key,
            lesson_key=lesson_key, payload=assessment_payload, column="assessment", lease_owner=lease_owner,
        )

    async def _checkpoint(self, session: Any, *, tenant_id: str, generation_key: str, module_key: str, lesson_key: str, payload: Mapping[str, Any], column: str, lease_owner: str | None) -> None:
        column = _stage(column)
        generation_key = _key(generation_key, error="invalid_generation_key")
        module_key = _key(module_key, error="invalid_module_key")
        lesson_key = _key(lesson_key, error="invalid_lesson_key")
        normalized_lease_owner = (
            _key(lease_owner, error="invalid_lease_owner") if lease_owner is not None else None
        )
        serialized_payload = _json_payload(payload, error=f"invalid_{column}_payload")
        await self._set_tenant(session, tenant_id)
        result = await session.execute(
            text(f"""
                UPDATE ai_generation_lesson_checkpoints AS checkpoint
                SET {column}_payload = CAST(:payload AS jsonb),
                    {column}_status = 'completed',
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = now()
                FROM ai_generation_runs AS run
                WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                  AND checkpoint.generation_run_id = run.id
                  AND run.tenant_id = checkpoint.tenant_id
                  AND run.generation_key = :generation_key
                  AND checkpoint.module_key = :module_key
                  AND checkpoint.lesson_key = :lesson_key
                  AND (
                      CAST(:lease_owner AS varchar) IS NULL
                      OR checkpoint.lease_owner = CAST(:lease_owner AS varchar)
                  )
                  AND (
                      checkpoint.{column}_status <> 'completed'
                      OR checkpoint.{column}_payload = CAST(:payload AS jsonb)
                  )
                RETURNING checkpoint.id
            """),
            {
                "tenant_id": str(tenant_id), "generation_key": generation_key,
                "module_key": module_key, "lesson_key": lesson_key, "payload": serialized_payload,
                "lease_owner": normalized_lease_owner,
            },
        )
        if _first(result) is not None:
            return
        existing = await session.execute(
            text(f"""
                SELECT checkpoint.{column}_status, checkpoint.{column}_payload
                FROM ai_generation_lesson_checkpoints AS checkpoint
                JOIN ai_generation_runs AS run ON run.id = checkpoint.generation_run_id
                WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                  AND run.tenant_id = checkpoint.tenant_id
                  AND run.generation_key = :generation_key
                  AND checkpoint.module_key = :module_key
                  AND checkpoint.lesson_key = :lesson_key
            """),
            {
                "tenant_id": str(tenant_id), "generation_key": generation_key,
                "module_key": module_key, "lesson_key": lesson_key,
            },
        )
        row = _first(existing)
        if row is None:
            raise AIGenerationCheckpointError("generation_lesson_not_found")
        if _row_value(row, f"{column}_status", 0) == "completed":
            raise AIGenerationCheckpointError(f"{column}_checkpoint_conflict")
        raise AIGenerationCheckpointError("generation_checkpoint_not_updated")

    async def claim_item(
        self,
        session: Any,
        *,
        tenant_id: str,
        generation_key: str,
        module_key: str,
        lesson_key: str,
        stage: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
    ) -> ClaimedGenerationItem | None:
        """Atomically claim one exact planned item before invoking a provider."""
        generation_key = _key(generation_key, error="invalid_generation_key")
        module_key = _key(module_key, error="invalid_module_key")
        lesson_key = _key(lesson_key, error="invalid_lesson_key")
        stage = _stage(stage)
        lease_owner = _key(lease_owner, error="invalid_lease_owner")
        duration = _lease_duration(lease_duration_seconds)
        prerequisite = {
            "content": "TRUE",
            "review": "checkpoint.content_status = 'completed'",
            "assessment": "checkpoint.review_status = 'completed'",
        }[stage]
        await self._set_tenant(session, tenant_id)
        result = await session.execute(
            text(f"""
                UPDATE ai_generation_lesson_checkpoints AS checkpoint
                SET lease_owner = :lease_owner,
                    lease_expires_at = now() + make_interval(secs => :lease_duration_seconds),
                    lease_duration_seconds = :lease_duration_seconds,
                    attempt_count = checkpoint.attempt_count + 1,
                    updated_at = now()
                FROM ai_generation_runs AS run
                WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                  AND checkpoint.generation_run_id = run.id
                  AND run.tenant_id = checkpoint.tenant_id
                  AND run.generation_key = :generation_key
                  AND checkpoint.module_key = :module_key
                  AND checkpoint.lesson_key = :lesson_key
                  AND checkpoint.{stage}_status <> 'completed'
                  AND {prerequisite}
                  AND (checkpoint.lease_expires_at IS NULL OR checkpoint.lease_expires_at <= now())
                RETURNING checkpoint.module_key, checkpoint.lesson_key, checkpoint.module_order,
                          checkpoint.lesson_order, checkpoint.attempt_count
            """),
            {
                "tenant_id": str(tenant_id), "generation_key": generation_key,
                "module_key": module_key, "lesson_key": lesson_key,
                "lease_owner": lease_owner, "lease_duration_seconds": duration,
            },
        )
        row = _first(result)
        if row is None:
            return None
        return ClaimedGenerationItem(
            module_key=_row_value(row, "module_key", 0), lesson_key=_row_value(row, "lesson_key", 1),
            module_order=_row_value(row, "module_order", 2), lesson_order=_row_value(row, "lesson_order", 3),
            attempt_count=_row_value(row, "attempt_count", 4), stage=stage, lease_owner=lease_owner,
        )

    async def release_leases(
        self,
        session: Any,
        *,
        tenant_id: str,
        generation_key: str,
        lease_owner: str,
    ) -> None:
        generation_key = _key(generation_key, error="invalid_generation_key")
        lease_owner = _key(lease_owner, error="invalid_lease_owner")
        await self._set_tenant(session, tenant_id)
        await session.execute(
            text("""
                UPDATE ai_generation_lesson_checkpoints AS checkpoint
                SET lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
                FROM ai_generation_runs AS run
                WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                  AND checkpoint.generation_run_id = run.id
                  AND run.tenant_id = checkpoint.tenant_id
                  AND run.generation_key = :generation_key
                  AND checkpoint.lease_owner = :lease_owner
            """),
            {
                "tenant_id": str(tenant_id), "generation_key": generation_key,
                "lease_owner": lease_owner,
            },
        )

    async def claim_missing_item(
        self,
        session: Any,
        *,
        tenant_id: str,
        generation_key: str,
        stage: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
    ) -> ClaimedGenerationItem | None:
        generation_key = _key(generation_key, error="invalid_generation_key")
        stage = _stage(stage)
        lease_owner = _key(lease_owner, error="invalid_lease_owner")
        duration = _lease_duration(lease_duration_seconds)
        await self._set_tenant(session, tenant_id)
        result = await session.execute(
            text(f"""
                WITH candidate AS (
                    SELECT checkpoint.id
                    FROM ai_generation_lesson_checkpoints AS checkpoint
                    JOIN ai_generation_runs AS run ON run.id = checkpoint.generation_run_id
                    WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                      AND run.tenant_id = checkpoint.tenant_id
                      AND run.generation_key = :generation_key
                      AND checkpoint.{stage}_status <> 'completed'
                      AND (checkpoint.lease_expires_at IS NULL OR checkpoint.lease_expires_at <= now())
                    ORDER BY checkpoint.module_order ASC, checkpoint.lesson_order ASC,
                             checkpoint.module_key ASC, checkpoint.lesson_key ASC
                    FOR UPDATE OF checkpoint SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ai_generation_lesson_checkpoints AS checkpoint
                SET lease_owner = :lease_owner,
                    lease_expires_at = now() + make_interval(secs => :lease_duration_seconds),
                    lease_duration_seconds = :lease_duration_seconds,
                    attempt_count = checkpoint.attempt_count + 1,
                    updated_at = now()
                FROM candidate
                WHERE checkpoint.id = candidate.id
                RETURNING checkpoint.module_key, checkpoint.lesson_key, checkpoint.module_order,
                          checkpoint.lesson_order, checkpoint.attempt_count
            """),
            {
                "tenant_id": str(tenant_id), "generation_key": generation_key,
                "lease_owner": lease_owner, "lease_duration_seconds": duration,
            },
        )
        row = _first(result)
        if row is None:
            return None
        return ClaimedGenerationItem(
            module_key=_row_value(row, "module_key", 0), lesson_key=_row_value(row, "lesson_key", 1),
            module_order=_row_value(row, "module_order", 2), lesson_order=_row_value(row, "lesson_order", 3),
            attempt_count=_row_value(row, "attempt_count", 4), stage=stage, lease_owner=lease_owner,
        )

    async def enumerate_missing_items(self, session: Any, *, tenant_id: str, generation_key: str) -> tuple[MissingGenerationItem, ...]:
        generation_key = _key(generation_key, error="invalid_generation_key")
        await self._set_tenant(session, tenant_id)
        result = await session.execute(
            text("""
                SELECT checkpoint.module_key, checkpoint.lesson_key, checkpoint.module_order,
                       checkpoint.lesson_order, checkpoint.content_status, checkpoint.review_status,
                       checkpoint.assessment_status
                FROM ai_generation_lesson_checkpoints AS checkpoint
                JOIN ai_generation_runs AS run ON run.id = checkpoint.generation_run_id
                WHERE checkpoint.tenant_id = CAST(:tenant_id AS uuid)
                  AND run.tenant_id = checkpoint.tenant_id
                  AND run.generation_key = :generation_key
                  AND (checkpoint.content_status <> 'completed' OR checkpoint.review_status <> 'completed'
                       OR checkpoint.assessment_status <> 'completed')
                ORDER BY checkpoint.module_order ASC, checkpoint.lesson_order ASC,
                         checkpoint.module_key ASC, checkpoint.lesson_key ASC
            """),
            {"tenant_id": str(tenant_id), "generation_key": generation_key},
        )
        missing: list[MissingGenerationItem] = []
        for row in result.fetchall():
            values = {name: _row_value(row, name, index) for index, name in enumerate((
                "module_key", "lesson_key", "module_order", "lesson_order", "content_status", "review_status",
                "assessment_status",
            ))}
            if values["content_status"] != "completed":
                missing.append(MissingGenerationItem(stage="content", **{key: values[key] for key in values if not key.endswith("_status")}))
            if values["review_status"] != "completed":
                missing.append(MissingGenerationItem(stage="review", **{key: values[key] for key in values if not key.endswith("_status")}))
            if values["assessment_status"] != "completed":
                missing.append(MissingGenerationItem(stage="assessment", **{key: values[key] for key in values if not key.endswith("_status")}))
        return tuple(missing)

    async def assert_complete(self, session: Any, *, tenant_id: str, generation_key: str) -> None:
        missing = await self.enumerate_missing_items(session, tenant_id=tenant_id, generation_key=generation_key)
        if missing:
            raise AIGenerationIncompleteError("generation_incomplete")


__all__ = [
    "AIGenerationCheckpointError", "AIGenerationCheckpointRepository", "AIGenerationIncompleteError",
    "ClaimedGenerationItem", "GenerationCheckpointSnapshot", "GenerationPlan",
    "MissingGenerationItem", "PlannedLesson",
]
