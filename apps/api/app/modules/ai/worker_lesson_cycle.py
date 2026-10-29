"""DEV-only adapter: automatic source plan -> serial reviewed durable lessons.

No model selection, publication or direct course/quiz writes. Existing generation
repository owns tenant-bound storage; the course pipeline owns draft persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from functools import wraps
from typing import Any, TypeVar, cast

from sqlalchemy import text

from app.modules.ai.assessment_counter_context import full_counter_scope
from app.modules.ai.assessment_source_context import (
    ContextProjectionError,
    select_assessment_context,
    select_semantic_assessment_context,
)
from app.modules.ai.complete_clause import COMPLETE_CLAUSE_FORM, build_complete_clause_spec
from app.modules.ai.evidence_engine.models import CourseIntent, LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import BlockAssessmentResult
from app.modules.ai.evidence_engine.semantic_blocks import SemanticBlock
from app.modules.ai.final_teaching_eligibility import FinalTeachingCatalog, catalog_matches_final_content
from app.modules.ai.generation_checkpoint import AIGenerationCheckpointRepository, PlannedLesson
from app.modules.ai.json_evidence_equivalence import equivalent as json_equivalent
from app.modules.ai.lesson_cycle import (
    MAX_CASE_CITATION_LOGICAL_CALLS,
    MAX_RAW_SOURCE_CHARS,
    MAX_RENDERED_SOURCE_CHARS,
    POLICY_VERSION,
    CaseCitationCycleBudget,
    LessonCycleResult,
    LessonPacket,
    ReviewedQuestion,
    SourceExcerpt,
    operational_question_target_ids,
    ordinary_binary_source_identity,
    ordinary_response_budget_proof,
    prepare_component_construction,
    question_inventory_key,
    run_lesson_cycles,
    source_response_budget_proof,
)
from app.modules.ai.llm_client import AllProvidersFailedError
from app.modules.ai.source_assessment_plan import (
    PLAN_POLICY,
    SourcePlanError,
    build_source_assessment_plan,
    operational_evidence_gaps,
    plan_facet_source_ids,
    plan_facet_status,
    source_only_plan_lesson,
)
from app.modules.ai.source_case_projection import (
    MATERIAL_BRANCH_EFFECTS,
    CaseContextBinding,
    CaseProjectionSource,
    bind_case_context,
)
from app.modules.ai.source_literal import source_context_fields
from app.modules.ai.source_plan_factory import APPLICATION_PLAN_POLICY, SourcePlanFactory, SourcePlanMode
from app.modules.ai.source_question_identity import assessment_inventory_binding

_PROMPT_INVENTORY_POLICY = "worker-question-prompt-inventory-v2"
SOURCE_AUTHOR_CONTRACT_POLICY = "worker-source-author-contract-v2"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _reviewed_evidence_matches(restored: Any, saved: Any) -> bool:
    """Compare reviewed evidence; historical repair feedback is not review authority."""
    if not isinstance(restored, dict) or not isinstance(saved, dict):
        return False
    return json_equivalent(
        {key: value for key, value in restored.items() if key != "repair_feedback"},
        {key: value for key, value in saved.items() if key != "repair_feedback"},
    )


def _historical_feedback_diagnostic(saved: Any) -> dict[str, Any] | None:
    """Expose only a bounded type label; keep raw feedback in its journal."""
    if not isinstance(saved, dict) or "repair_feedback" not in saved:
        return None
    value = saved["repair_feedback"]
    kind = ("null" if value is None else "boolean" if isinstance(value, bool)
            else "object" if isinstance(value, dict) else "array" if isinstance(value, list)
            else "string" if isinstance(value, str) else "number" if isinstance(value, int | float)
            else "other")
    return {"policy": "historical-repair-feedback-v1", "trust": "untrusted",
            "reviewed_in_current_run": False, "present": True, "value_type": kind}


def _target_needs_support_export(target: Any, owners: set[str]) -> bool:
    """Hold known non-owner source custody until question export can retain it."""
    source_ids = [source_id for group in target.component_source_ids for source_id in group]
    bindings = (*target.qualification_bindings, *target.original_context_bindings,
                *target.case_context_bindings)
    source_ids.extend(binding.get("source_id") for binding in bindings)
    for binding in (target.fixed_source_context, target.source_quote_proposition):
        if binding is not None:
            source_ids.append(binding.get("source_id"))
    return any(source_id not in owners for source_id in source_ids)


def _question_needs_support_export(question: ReviewedQuestion, owner_sources: set[str]) -> bool:
    """Retain no question whose reviewed source attribution cannot be exported."""
    audit = question.semantic_audit
    if audit is not None and not isinstance(audit, dict):
        return True
    audit = audit or {}
    collections = (question.option_evidence, audit.get("options", ()), audit.get("target_proofs", ()))
    if any(not isinstance(rows, tuple | list) for rows in collections):
        return True
    return any(not isinstance(row, dict) or row.get("source_id") not in owner_sources
               for rows in collections for row in rows)


def _mapped_case_context_bindings(target: Any, excerpts: dict[str, SourceExcerpt]) -> tuple[dict[str, Any], ...]:
    """Recompute existing display receipts under the mapped source identity."""
    mapped = []
    for binding in target.case_context_bindings:
        excerpt = excerpts[binding["source_id"]]
        forks = {row["quote"] for row in target.qualification_bindings
            if row["source_id"] == binding["source_id"]
            and row["branch_effect"] in MATERIAL_BRANCH_EFFECTS}
        owned = bind_case_context(CaseProjectionSource(excerpt.source_id, excerpt.text, excerpt.original_text),
            binding["quote"], within_quote=next(iter(forks)) if len(forks) == 1 else None)
        if owned != replace(CaseContextBinding(**binding), source_id=excerpt.source_id):
            raise ValueError("source_case_context_remap_changed_receipt")
        mapped.append(asdict(owned))
    return tuple(mapped)


def _incomplete_material_case_target_ids(plan: Any, *, allow_application_edges: bool = False) -> tuple[str, ...]:
    """Withhold known branch families atomically; unknown source branches earn no claim."""
    if allow_application_edges:
        # This opt-in adapter accepts only the existing complete-only graph
        # planner, revalidated by its builder/zero-call transcript restore.
        # A global facet vote cannot replace an individual admitted edge.
        def unique_ids(values: Any) -> bool:
            return (isinstance(values, list | tuple)
                and all(isinstance(value, str) and value for value in values)
                and len(values) == len(set(values)))

        target_values = [target.target_id for target in plan.targets]
        if not unique_ids(target_values) or not unique_ids(plan.admitted_target_ids):
            raise SourcePlanError("worker_application_source_plan_incomplete")
        target_ids = set(target_values)
        admitted = set(plan.admitted_target_ids)
        raw = plan.evidence.get("plan")
        resolution = raw.get("qualification_resolution") if isinstance(raw, dict) else None
        facets = resolution.get("facets") if isinstance(resolution, dict) else None
        edges = resolution.get("admitted_edges") if isinstance(resolution, dict) else None
        if not isinstance(facets, list) or not isinstance(edges, list):
            raise SourcePlanError("worker_application_source_plan_incomplete")
        expected_edges: set[tuple[str, str]] = set()
        facet_ids: set[str] = set()
        for facet in facets:
            if (not isinstance(facet, dict) or not isinstance(facet.get("facet_id"), str)
                    or not facet["facet_id"] or facet["facet_id"] in facet_ids
                    or not unique_ids(facet.get("target_ids"))
                    or not set(facet["target_ids"]) <= target_ids):
                raise SourcePlanError("worker_application_source_plan_incomplete")
            facet_ids.add(facet["facet_id"])
            expected_edges.update((facet["facet_id"], tid) for tid in facet["target_ids"])
        actual_edges: set[tuple[str, str]] = set()
        for edge in edges:
            if (not isinstance(edge, dict) or set(edge) != {"facet_id", "target_id"}
                    or any(not isinstance(edge[key], str) or not edge[key] for key in edge)):
                raise SourcePlanError("worker_application_source_plan_incomplete")
            identity = (edge["facet_id"], edge["target_id"])
            if identity in actual_edges:
                raise SourcePlanError("worker_application_source_plan_incomplete")
            actual_edges.add(identity)
        if actual_edges != expected_edges:
            raise SourcePlanError("worker_application_source_plan_incomplete")
        status = plan_facet_status(plan, admitted)
        if (plan.evidence.get("policy") != APPLICATION_PLAN_POLICY
                or "batches" in plan.evidence or plan.requires_review is not False or admitted != target_ids
                or status["source_completeness"]["complete"] is not True
                or status["assessment_coverage"]["complete"] is not True):
            raise SourcePlanError("worker_application_source_plan_incomplete")
    else:
        target_ids = {target.target_id for target in plan.targets}
        admitted = set(plan.admitted_target_ids) & target_ids
    batches = [(f"B{index + 1}:", row.get("evidence", {})) for index, row in
        enumerate(plan.evidence["batches"])] if "batches" in plan.evidence else [("", plan.evidence)]
    withheld: set[str] = set()
    for prefix, child in batches:
        resolution = child.get("plan", {}).get("qualification_resolution", {})
        if "admitted_edges" in resolution:
            if not allow_application_edges:
                raise SourcePlanError("local_semantic_view_worker_adoption_not_enabled")
            continue  # Every branch/edge above is complete; no partial family exists.
        accepted = set(resolution.get("admitted_facet_ids", []))
        for facet in resolution.get("facets", []):
            branches = facet.get("branch_target_ids") if isinstance(facet, dict) else None
            if (not isinstance(facet, dict) or facet.get("facet_id") not in accepted
                    or facet.get("branch_effect") not in MATERIAL_BRANCH_EFFECTS
                    or not isinstance(branches, list) or len(branches) < 2
                    or any(not isinstance(target_id, str) or not target_id for target_id in branches)):
                continue
            family = {prefix + target_id for target_id in branches}
            if not family <= admitted:
                withheld.update(family & admitted)
    return tuple(sorted(withheld))


def _assessment_target_batches(
    admitted: tuple[Any, ...], maximum: int = 24,
) -> tuple[tuple[tuple[Any, ...], ...], tuple[str, ...]]:
    """Pack exact case-facet components atomically; never infer a relationship."""
    if type(maximum) is not int or not 1 <= maximum <= 24:
        raise ValueError("worker_cycle_invalid_batch_maximum")
    if not isinstance(admitted, tuple):
        raise ValueError("worker_cycle_invalid_admitted_targets")

    parents = list(range(len(admitted)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    facet_owner: dict[str, int] = {}
    case_indices: set[int] = set()
    for index, target in enumerate(admitted):
        if not getattr(target, "case_context_bindings", ()):
            continue
        facet_ids: set[str] = {
            binding["facet_id"]
            for binding in getattr(target, "qualification_bindings", ())
            if isinstance(binding, dict)
            and binding.get("branch_effect") in MATERIAL_BRANCH_EFFECTS
            and isinstance(binding.get("facet_id"), str)
            and binding["facet_id"]
        }
        if not facet_ids:
            continue
        case_indices.add(index)
        for facet_id in facet_ids:
            if facet_id in facet_owner:
                union(index, facet_owner[facet_id])
            else:
                facet_owner[facet_id] = index

    components: dict[int, list[int]] = {}
    for index in case_indices:
        components.setdefault(root(index), []).append(index)
    by_index = {
        member: tuple(sorted(members))
        for members in components.values()
        for member in members
    }

    units: list[tuple[Any, ...]] = []
    consumed: set[int] = set()
    for index, _target in enumerate(admitted):
        if index in consumed:
            continue
        members = by_index.get(index, (index,))
        consumed.update(members)
        units.append(tuple(admitted[member] for member in members))

    batches: list[tuple[Any, ...]] = []
    current: list[Any] = []
    oversized: list[str] = []
    for unit in units:
        if len(unit) > maximum:
            oversized.extend(str(target.target_id) for target in unit)
            continue
        if current and len(current) + len(unit) > maximum:
            batches.append(tuple(current))
            current = []
        current.extend(unit)
    if current:
        batches.append(tuple(current))
    return tuple(batches), tuple(oversized)


def _assign_complete_clause_surface(target: Any, obligations: Any, sources: tuple[SourceExcerpt, ...],
                                    *, enabled: bool) -> Any:
    """Route one exact canonical outcome/object target; never infer truth or a key."""
    linked = [row for row in obligations if target.target_id in row.target_ids]
    if (target.case_context_bindings or enabled is not True or len(linked) != 1
            or target.assessment_level == "operational_decision" or linked[0].evidence_level != "source_recognition"
            or linked[0].dimension not in {"outcome", "object"}
            or len(target.answer_requirements) != 1 or len(target.answer_requirements[0]) != 1
            or linked[0].quote != target.answer_requirements[0][0]):
        return target
    proposed = replace(target, answer_surface=COMPLETE_CLAUSE_FORM)
    return proposed if build_complete_clause_spec(proposed, sources, enabled=True) is not None else target


def create_dev_lesson_assessor(*, settings: Any, tenant_id: str, job_id: str,
                               client: Any, session_factory: Any, checkpoint: Any) -> WorkerLessonAssessor | None:
    """Exact existing DEV identities, never APP_ENV (DEV also uses production)."""
    if (settings.DEPLOYMENT_ENVIRONMENT not in {"render-development", "render-development-worker", "vm-development-worker"}
            or not settings.AI_LESSON_CYCLE_DEV_ENABLED
            or tenant_id not in settings.AI_LESSON_CYCLE_DEV_TENANTS):
        return None
    return WorkerLessonAssessor(tenant_id=tenant_id, client=client,
        journal=WorkerCycleJournal(tenant_id, job_id, session_factory), checkpoint=checkpoint,
        learner_language_gate=True)


class _MeasuredClient:
    def __init__(self, client: Any, checkpoint: Any):
        self.client, self.checkpoint = client, checkpoint
        self.calls = self.attempts = 0

    async def ainvoke_validated(self, *args: Any, **kwargs: Any) -> Any:
        await self.checkpoint()
        self.calls += 1
        try:
            response = await self.client.ainvoke_validated(*args, **kwargs)
        except AllProvidersFailedError as exc:
            self.attempts += len(exc.reasons) or 1
            raise
        self.attempts += response.attempt_count
        return response


class WorkerCycleJournal:
    """Small transactions, no database session held during provider calls."""

    def __init__(self, tenant_id: str, job_id: str, session_factory: Any):
        self.tenant_id, self.job_id, self.sessions = tenant_id, job_id, session_factory
        self.repository = AIGenerationCheckpointRepository()

    async def _lock_delivery(self, session: Any) -> None:
        from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id, lock_owned_delivery

        if delivery_id.get() is None:
            raise DeliveryOwnershipLostError("generation_delivery_identity_missing")
        await self.repository._set_tenant(session, self.tenant_id)
        await lock_owned_delivery(session, self.job_id, self.tenant_id, require_running=True)

    async def prepare(self, key: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        key = self._owned_key(key)
        async with self.sessions() as session:
            await self._lock_delivery(session)
            await self.repository.create_plan(session, tenant_id=self.tenant_id,
                generation_key=key, plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                source_job_id=self.job_id, plan_payload=payload,
                lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
            rows = await self.repository.load_checkpoints(session, tenant_id=self.tenant_id, generation_key=key)
            await session.commit()
            return dict(rows[0].assessment_payload) if rows[0].assessment_payload is not None else None

    async def save_value(self, key: str, value: dict[str, Any]) -> None:
        key = self._owned_key(key)
        async with self.sessions() as session:
            await self._lock_delivery(session)
            args = dict(tenant_id=self.tenant_id, generation_key=key, module_key="cycle", lesson_key="lesson")
            await self.repository.checkpoint_content(session, **args, content_payload={"owned": True})
            await self.repository.checkpoint_review(session, **args, review_payload={"policy": PLAN_POLICY})
            await self.repository.checkpoint_assessment(session, **args, assessment_payload=value)
            await session.commit()

    async def inventory_versions(self, base_key: str) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            await self.repository._set_tenant(session, self.tenant_id)
            result = await session.execute(text("""
                SELECT r.generation_key, r.plan_revision, r.plan_payload,
                       c.module_key, c.lesson_key, c.assessment_status, c.assessment_payload
                FROM ai_generation_runs r
                LEFT JOIN ai_generation_lesson_checkpoints c
                  ON c.generation_run_id = r.id AND c.tenant_id = r.tenant_id
                WHERE r.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.source_job_id = :job_id
                  AND r.plan_payload->>'inventory_base_key' = :base_key
            """), {"tenant_id": self.tenant_id, "job_id": self.job_id, "base_key": base_key})
            return [dict(row._mapping) for row in result.fetchall()]

    async def append_inventory_version(self, key: str, plan: dict[str, Any], value: dict[str, Any]) -> None:
        owned_key = self._owned_key(key)
        async with self.sessions() as session:
            await self._lock_delivery(session)
            await self.repository.create_plan(session, tenant_id=self.tenant_id,
                generation_key=owned_key, plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                source_job_id=self.job_id, plan_payload=plan,
                lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
            args = dict(tenant_id=self.tenant_id, generation_key=owned_key, module_key="cycle", lesson_key="lesson")
            await self.repository.checkpoint_content(session, **args, content_payload={"owned": True})
            await self.repository.checkpoint_review(session, **args, review_payload={"policy": PLAN_POLICY})
            await self.repository.checkpoint_assessment(session, **args, assessment_payload=value)
            await session.commit()

    async def read_value(self, key: str) -> dict[str, Any] | None:
        """Read only the current job's completed checkpoint; never create a plan."""
        async with self.sessions() as session:
            rows = await self.repository.load_checkpoints(
                session, tenant_id=self.tenant_id, generation_key=self._owned_key(key))
            if len(rows) != 1:
                return None
            row = rows[0]
            if (row.module_key != "cycle" or row.lesson_key != "lesson"
                    or row.assessment_status != "completed" or row.assessment_payload is None):
                return None
            return dict(row.assessment_payload)

    async def read_owned_value(self, key: str, expected_plan: dict[str, Any]) -> dict[str, Any] | None:
        """Read only a checkpoint whose persisted plan belongs to this tenant and job."""
        generation_key = self._owned_key(key)
        async with self.sessions() as session:
            plan = await self.repository.load_plan(session, tenant_id=self.tenant_id, generation_key=generation_key)
            if (plan.source_job_id != self.job_id or plan.plan_revision != f"{PLAN_POLICY}/{POLICY_VERSION}"
                    or not json_equivalent(dict(plan.plan_payload), expected_plan)
                    or plan.lessons != (PlannedLesson("cycle", "lesson", 0, 0),)):
                return None
            rows = await self.repository.load_checkpoints(session, tenant_id=self.tenant_id, generation_key=generation_key)
            if len(rows) != 1:
                return None
            row = rows[0]
            if (row.module_key != "cycle" or row.lesson_key != "lesson"
                    or row.assessment_status != "completed" or row.assessment_payload is None):
                return None
            return dict(row.assessment_payload)

    def _owned_key(self, key: str) -> str:
        # Source job ownership is immutable in the repository. A fresh generation
        # must not collide with another job's identical source/lesson checkpoint.
        return "worker-cycle:" + _digest([self.job_id, key])


def _restored_response_budget(packet: LessonPacket, row: dict[str, Any]) -> Any:
    proof = (ordinary_response_budget_proof(packet, row["target_ids"])
             if any(len(option) > 240 for option in row["options"]) else None)
    if _digest(row.get("source_response_budget")) != _digest(asdict(proof) if proof is not None else None):
        raise ValueError("worker_cycle_invalid_response_budget")
    return proof


class _CycleStore:
    def __init__(self, journal: Any, packet: LessonPacket, saved: dict[str, Any] | None, key: str):
        self.journal, self.packet, self.saved, self.key = journal, packet, saved, key
        self._job_id = getattr(journal, "job_id", None)

    async def load(self, tenant_id: str, identity: str) -> LessonCycleResult | None:
        if tenant_id != self.packet.tenant_id or identity != self.packet.identity():
            raise ValueError("worker_cycle_store_identity")
        if self.saved is None:
            return None
        value = dict(self.saved)
        value["questions"] = tuple(ReviewedQuestion(**(row | {
            "target_ids": tuple(row["target_ids"]), "options": tuple(row["options"]),
            "option_evidence": tuple(row["option_evidence"]),
            "component_realizations": tuple(row.get("component_realizations", [])),
            "component_fulfillments": tuple(row.get("component_fulfillments") or ()),
            "source_edits": tuple(row["source_edits"]) if row.get("source_edits") is not None else None,
            "component_proposals": tuple(row["component_proposals"]) if row.get("component_proposals") is not None else None,
            "option_language": tuple(row.get("option_language", [])),
            "option_recall": tuple(row.get("option_recall", [])),
            "option_fulfillment": tuple(row.get("option_fulfillment", [])),
            "conditional_cases": tuple(row.get("conditional_cases", [])),
            "fulfillment_checks": tuple(row.get("fulfillment_checks", [])),
            "qualification_realizations": tuple(row.get("qualification_realizations", [])),
            "application_proofs": tuple(row.get("application_proofs", [])),
            "application_scope_target_ids": tuple(row.get("application_scope_target_ids", [])),
            "lesson_refs": tuple(row.get("lesson_refs", [])),
            "lesson_quotes": tuple(row.get("lesson_quotes", [])),
            "teaching_proofs": tuple(row.get("teaching_proofs", [])),
            "source_response_budget": _restored_response_budget(self.packet, row),
        })) for row in value["questions"])
        value["missing_target_ids"] = tuple(value["missing_target_ids"])
        value["issues"] = tuple(value["issues"])
        value["teaching_diagnostics"] = tuple(value.get("teaching_diagnostics", ()))
        return LessonCycleResult(**value)

    async def reload(self, tenant_id: str, identity: str) -> LessonCycleResult | None:
        """Independently read the currently owned completed journal value."""
        if tenant_id != self.packet.tenant_id or identity != self.packet.identity():
            raise ValueError("worker_cycle_store_identity")
        reader = getattr(self.journal, "read_owned_value", None)
        if not callable(reader) or not isinstance(self._job_id, str) or not self._job_id:
            raise ValueError("worker_cycle_store_reload_unavailable")
        if getattr(self.journal, "job_id", None) != self._job_id:
            raise ValueError("worker_cycle_store_identity")
        saved = await reader(self.key, {"packet": self.packet.storage_payload()})
        if getattr(self.journal, "job_id", None) != self._job_id:
            raise ValueError("worker_cycle_store_identity")
        return await _CycleStore(self.journal, self.packet, saved, self.key).load(tenant_id, identity)

    async def save(self, tenant_id: str, identity: str, result: LessonCycleResult) -> None:
        if tenant_id != self.packet.tenant_id or identity != self.packet.identity() or result.identity != identity:
            raise ValueError("worker_cycle_store_identity")
        await self.journal.save_value(self.key, asdict(result))


@dataclass(frozen=True, slots=True)
class VerifiedSemanticSelection:
    """Process-local handoff; source-review status is not semantic approval."""

    policy: str
    tenant_id: str
    lesson_id: str
    plan_key: str
    plan_input_sha256: str
    plan_audit_sha256: str
    plan_evidence_sha256: str
    block: SemanticBlock


@dataclass(frozen=True, slots=True)
class SupportedFinalTeachingCatalog(FinalTeachingCatalog):
    support_custody_sha256: str


class _NoSemanticHandoffProvider:
    async def ainvoke_validated(self, *args: Any, **kwargs: Any) -> Any:
        raise ContextProjectionError("semantic_block_handoff_provider_forbidden", {})


@dataclass
class _LessonMutationLock:
    lock: asyncio.Lock
    users: int = 0
    owner: asyncio.Task[Any] | None = None


_MutationMethod = TypeVar("_MutationMethod", bound=Callable[..., Any])


def _serialize_lesson_mutation(method: _MutationMethod) -> _MutationMethod:
    """Serialize same-lesson mutations, with same-task reentry and bounded lifetime."""
    @wraps(method)
    async def wrapped(self: Any, lesson: LessonDraft, *args: Any, **kwargs: Any) -> Any:
        lesson_id = lesson.lesson_id
        task = asyncio.current_task()
        entry = self._lesson_mutation_locks.get(lesson_id)
        if entry is not None and entry.owner is task and task is not None:
            return await method(self, lesson, *args, **kwargs)
        if entry is None:
            entry = _LessonMutationLock(asyncio.Lock())
            self._lesson_mutation_locks[lesson_id] = entry
        entry.users += 1
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            entry.owner = task
            return await method(self, lesson, *args, **kwargs)
        finally:
            if acquired:
                entry.owner = None
                entry.lock.release()
            entry.users -= 1
            if entry.users == 0:
                self._lesson_mutation_locks.pop(lesson_id, None)
    return cast(_MutationMethod, wrapped)


class WorkerLessonAssessor:
    def __init__(self, *, tenant_id: str, client: Any, journal: Any, checkpoint: Any,
                 learner_language_gate: bool = False, pre_audit_rebuild: bool = False,
                 source_plan_mode: SourcePlanMode = "ordinary", semantic_block_provider: Any = None,
                 semantic_closure_verifier: Any = None, description_review: bool = False,
                 experimental_case_citation: bool = False, case_citation_evaluation: bool = False,
                 local_joint_reviewer: Any = None):
        if type(learner_language_gate) is not bool:
            raise ValueError("worker_cycle_invalid_language_mode")
        if type(pre_audit_rebuild) is not bool:
            raise ValueError("worker_cycle_invalid_rebuild_mode")
        if type(experimental_case_citation) is not bool:
            raise ValueError("worker_cycle_invalid_case_citation_mode")
        if type(case_citation_evaluation) is not bool or (case_citation_evaluation and not experimental_case_citation):
            raise ValueError("worker_cycle_invalid_case_citation_evaluation")
        if (semantic_block_provider is None) != (semantic_closure_verifier is None):
            raise ValueError("worker_cycle_incomplete_semantic_configuration")
        if local_joint_reviewer is not None:
            from app.modules.ai.joint_review_capability import JointReviewCapability
            if type(local_joint_reviewer) is not JointReviewCapability:
                raise ValueError("worker_cycle_local_joint_reviewer_invalid")
        self._local_joint_reviewer = local_joint_reviewer
        import secrets
        self._local_joint_identity = secrets.token_hex(16) if local_joint_reviewer is not None else ""
        self._source_plan_factory = SourcePlanFactory(source_plan_mode, description_review=description_review)
        if source_plan_mode == "application_first" and pre_audit_rebuild:
            raise ValueError("worker_cycle_application_ordinary_flags")
        self.tenant_id, self.client, self.journal, self.checkpoint = tenant_id, client, journal, checkpoint
        self.learner_language_gate = learner_language_gate
        self.pre_audit_rebuild = pre_audit_rebuild
        self.experimental_case_citation = experimental_case_citation
        self.case_citation_evaluation = case_citation_evaluation
        self._restore_call_observations: dict[str, list[dict[str, Any]]] = {}
        self.source_plan_mode = source_plan_mode
        self._semantic_block_provider = semantic_block_provider
        self._semantic_closure_verifier = semantic_closure_verifier
        self._prepared_semantic_keys: dict[str, str] = {}
        self._source_intents: dict[str, dict[str, Any]] = {}
        self._prepared_costs: dict[str, tuple[int, int]] = {}
        self._prepared_source_keys: dict[str, str] = {}
        self._prepared_source_statuses: dict[str, dict[str, str]] = {}
        self._prepared_semantic_source_lessons: dict[str, LessonDraft] = {}
        self._supported_teaching_custody: dict[str, dict[str, Any]] = {}
        self._verified_semantic_selections: dict[str, VerifiedSemanticSelection] = {}
        self._verified_semantic_selection_digests: dict[str, str] = {}
        self._audit_first_lessons: set[str] = set()
        self._lesson_mutation_locks: dict[str, _LessonMutationLock] = {}
        # Process-owned results only; never hydrated from checkpoint assertions.
        self._reviewed_source_plans: dict[str, tuple[str, str, str, str, Any]] = {}

    @property
    def source_plan_policy(self) -> str:
        return self._source_plan_factory.policy

    def restore_call_observations(self, lesson_id: str) -> tuple[dict[str, Any], ...]:
        """Read separate restore counts, including interrupted assessments."""
        return tuple(dict(row) for row in self._restore_call_observations.get(lesson_id, ()))

    async def _build_source_plan(self, lesson: LessonDraft, primary: list[SourceFact],
                                 context: list[SourceFact], *, client: Any,
                                 saved_evidence: Any, audit_first: bool = False) -> Any:
        flags = ({"audit_first": audit_first, "pre_audit_rebuild": self.pre_audit_rebuild}
                 if self.source_plan_mode == "ordinary" else {})
        return await self._source_plan_factory.build(
            lesson, primary, context, client=client, saved_evidence=saved_evidence,
            ordinary_builder=build_source_assessment_plan, **flags)

    def _source_plan_identity(self, lesson: LessonDraft, context: list[SourceFact],
                              facts_by_id: dict[str, SourceFact], *, counter_sharded: bool, selection: Any = None) -> dict[str, Any]:
        identity = {"tenant": self.tenant_id, "lesson": asdict(source_only_plan_lesson(lesson)),
                    "facts": [asdict(fact) for fact in context],
                    "policy": f"{self.source_plan_policy}/{POLICY_VERSION}",
                    "intent": self._source_intents.get(lesson.lesson_id, {}),
                    "audit_first": lesson.lesson_id in self._audit_first_lessons}
        identity.update(self._source_plan_factory.identity())
        if self.pre_audit_rebuild:
            identity["pre_audit_policy"] = "unapproved-full-source-rebuild-v1"
        if counter_sharded:
            identity["counter_context_facts"] = [asdict(fact) for fact in facts_by_id.values()]
        if selection is not None and isinstance(selection.semantic_block, SemanticBlock):
            identity["semantic_block_sha256"] = selection.ledger.get("semantic_block_sha256") or _digest(asdict(selection.semantic_block))
            identity["semantic_source_inventory_sha256"] = selection.semantic_block.source_inventory_sha256
            identity["semantic_counter_coverage_sha256"] = _digest([[asdict(fact) for fact in shard] for shard in selection.counter_shards])
        return identity

    async def _local_joint_review_question(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact],
                                           question: dict[str, Any]) -> bool:
        """Opt-in diagnostic over available facts; no source-completeness authority."""
        if self._local_joint_reviewer is None:
            return True
        def sources() -> list[dict[str, str]]:
            from app.modules.ai.joint_review_capability import MAX_SOURCE_CHARS, MAX_SOURCES
            if len(facts_by_id) > MAX_SOURCES:
                raise ValueError("local_joint_inventory_too_large")
            total = 0
            for key, fact in facts_by_id.items():
                values = (key, fact.fact_id, fact.subject, fact.attribute, fact.value,
                          fact.source_locator, fact.uncertainty)
                if any(not isinstance(value, str) for value in values):
                    raise ValueError("local_joint_inventory_invalid")
                total += sum(len(value) for value in values)
                if total > MAX_SOURCE_CHARS:
                    raise ValueError("local_joint_inventory_too_large")
            return [{"id": key, "text": json.dumps(asdict(fact), sort_keys=True,
                    ensure_ascii=False, separators=(",", ":"))} for key, fact in facts_by_id.items()]
        try:
            rows = sources()
            revision = _digest(rows)
            identity = {"job": self._local_joint_identity, "attempt": self._local_joint_identity,
                        "source_revision": revision}
            receipt = await asyncio.wait_for(self._local_joint_reviewer.review(
                self.tenant_id, lesson.lesson_id, "local-joint-available-facts-v1", question, rows, **identity),
                timeout=30)
            current = sources()
            return (current == rows and self._local_joint_reviewer.admits(
                receipt, self.tenant_id, lesson.lesson_id, "local-joint-available-facts-v1",
                question, current, **identity))
        except Exception:
            return False

    async def _local_joint_review_batch(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact],
                                        candidates: list[dict[str, Any]]) -> dict[str, bool]:
        if self._local_joint_reviewer is None:
            return {row["id"]: True for row in candidates}
        if not candidates:
            return {}
        def source_snapshot() -> list[dict[str, str]]:
            from app.modules.ai.joint_review_capability import MAX_SOURCE_CHARS, MAX_SOURCES
            if len(facts_by_id) > MAX_SOURCES:
                raise ValueError("local_joint_inventory_too_large")
            total = 0
            for key, fact in facts_by_id.items():
                values = (key, fact.fact_id, fact.subject, fact.attribute, fact.value,
                          fact.source_locator, fact.uncertainty)
                if any(not isinstance(value, str) for value in values):
                    raise ValueError("local_joint_inventory_invalid")
                total += sum(len(value) for value in values)
                if total > MAX_SOURCE_CHARS:
                    raise ValueError("local_joint_inventory_too_large")
            return [{"id": key, "text": json.dumps(asdict(fact), sort_keys=True,
                    ensure_ascii=False, separators=(",", ":"))} for key, fact in facts_by_id.items()]
        try:
            rows = source_snapshot()
            frozen = json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            identity = {"job": self._local_joint_identity, "attempt": self._local_joint_identity,
                        "source_revision": _digest(rows)}
            verdicts = await asyncio.wait_for(self._local_joint_reviewer.review_batch(
                self.tenant_id, lesson.lesson_id, "local-joint-available-facts-v1", candidates, rows, **identity),
                timeout=30)
            if source_snapshot() != rows or json.dumps(candidates, ensure_ascii=False, sort_keys=True,
                                                        separators=(",", ":")) != frozen:
                raise ValueError("local_joint_input_changed")
            return cast(dict[str, bool], verdicts)
        except Exception:
            return {row["id"]: False for row in candidates}

    def _select_source_context(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> Any:
        if (self._semantic_block_provider is None) != (self._semantic_closure_verifier is None):
            raise ContextProjectionError("worker_cycle_incomplete_semantic_configuration", {})
        if self._semantic_block_provider is None or self._semantic_closure_verifier is None:
            selection = select_assessment_context(lesson, facts_by_id, raw_limit=MAX_RAW_SOURCE_CHARS,
                                                  rendered_limit=MAX_RENDERED_SOURCE_CHARS)
            from app.modules.ai.assessment_source_context import require_owned_internal_references_resolved

            require_owned_internal_references_resolved(lesson, facts_by_id)
            return selection
        try:
            block = self._semantic_block_provider(self.tenant_id, lesson, tuple(facts_by_id.values()))
            def verify(candidate: Any, facts: Any) -> bool:
                return self._semantic_closure_verifier(self.tenant_id, lesson, candidate, facts) is True
            return select_semantic_assessment_context(lesson, facts_by_id, block=block, closure_verifier=verify,
                raw_limit=MAX_RAW_SOURCE_CHARS, rendered_limit=MAX_RENDERED_SOURCE_CHARS)
        except ContextProjectionError:
            raise
        except Exception as exc:
            raise ContextProjectionError("semantic_block_provider_error", {}) from exc

    @_serialize_lesson_mutation
    async def verified_semantic_selection(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> VerifiedSemanticSelection | None:
        """Revalidate this process's prepared selection before handing it onward."""
        prior = self._verified_semantic_selections.get(lesson.lesson_id)
        if prior is None:
            return None
        selection = self._select_source_context(source_only_plan_lesson(lesson), facts_by_id)
        identity = self._source_plan_identity(source_only_plan_lesson(lesson), list(selection.local_facts), facts_by_id,
            counter_sharded=len(selection.counter_shards) > 1 or selection.semantic_block is not None,
            selection=selection)
        if (self._verified_semantic_selection_digests.get(lesson.lesson_id) != _digest(asdict(prior))
                or prior.tenant_id != self.tenant_id or prior.lesson_id != lesson.lesson_id
                or selection.semantic_block != prior.block
                or _digest(identity) != prior.plan_input_sha256
                or "source-plan:" + _digest(identity) != prior.plan_key):
            raise ContextProjectionError("semantic_block_handoff_identity", {})
        saved = await self.journal.read_value(prior.plan_key)
        if not isinstance(saved, dict) or _digest(saved) != prior.plan_evidence_sha256:
            raise ContextProjectionError("semantic_block_handoff_evidence", {})
        if self._source_plan_factory.description_review:
            cached = self._reviewed_source_plans.get(lesson.lesson_id)
            if (cached is None or cached[0] != prior.plan_key or cached[1] != _digest(identity)
                    or cached[2] != _digest(saved) or cached[3] != getattr(self.journal, "job_id", None)
                    or cached[4].requires_review):
                raise ContextProjectionError("semantic_block_handoff_restore", {})
            # Recheck after the journal await, including source and selected block.
            selected_now = self._select_source_context(source_only_plan_lesson(lesson), facts_by_id)
            current = self._source_plan_identity(source_only_plan_lesson(lesson), list(selected_now.local_facts), facts_by_id,
                counter_sharded=len(selected_now.counter_shards) > 1 or selected_now.semantic_block is not None,
                selection=selected_now)
            if _digest(current) != prior.plan_input_sha256 or selected_now.semantic_block != prior.block:
                raise ContextProjectionError("semantic_block_handoff_identity", {})
            return prior
        try:
            restored = await self._build_source_plan(source_only_plan_lesson(lesson),
                [facts_by_id[fid] for fid in lesson.fact_ids], list(selection.local_facts),
                client=_NoSemanticHandoffProvider(), saved_evidence=deepcopy(saved), audit_first=True)
        except Exception as exc:
            raise ContextProjectionError("semantic_block_handoff_restore", {}) from exc
        if (restored.requires_review or getattr(restored, "model_calls", None) != 0
                or getattr(restored, "attempt_count", None) != 0
                or _digest(restored.evidence) != prior.plan_evidence_sha256
                or (restored.evidence.get("plan_audit_sha256") or _digest(restored.evidence)) != prior.plan_audit_sha256):
            raise ContextProjectionError("semantic_block_handoff_restore", {})
        return prior

    @_serialize_lesson_mutation
    async def semantic_author_context(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> dict[str, Any] | None:
        """Project verified source context; this is not an author or coverage approval."""
        selection = await self.verified_semantic_selection(lesson, facts_by_id)
        if selection is None:
            return None
        block = selection.block
        payload: dict[str, Any] = {
            "policy": "semantic-author-context-v1",
            "tenant_id": selection.tenant_id,
            "lesson_id": selection.lesson_id,
            "plan_key": selection.plan_key,
            "plan_input_sha256": selection.plan_input_sha256,
            "plan_audit_sha256": selection.plan_audit_sha256,
            "plan_evidence_sha256": selection.plan_evidence_sha256,
            "source_inventory_sha256": block.source_inventory_sha256,
            "owned_fact_ids": [fact.fact_id for fact in block.owned_facts],
            "supporting_facts": [asdict(fact) for fact in block.context_facts],
            "dependencies": [asdict(edge) for edge in block.dependencies],
            "ancestor_ids_by_fact": [[fact_id, list(ancestors)] for fact_id, ancestors in block.ancestor_ids_by_fact],
            "source_documents": [asdict(identity) for identity in block.corpus_identities],
        }
        payload["context_sha256"] = _digest(payload)
        return payload

    async def semantic_support_required(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> bool:
        """Determine the verified support hold before source-plan provider work."""
        if (self._semantic_block_provider is None) != (self._semantic_closure_verifier is None):
            raise ContextProjectionError("worker_cycle_incomplete_semantic_configuration", {})
        if self._semantic_block_provider is None or self._semantic_closure_verifier is None:
            return False
        await self.checkpoint()
        selection = self._select_source_context(source_only_plan_lesson(lesson), facts_by_id)
        return (isinstance(selection.semantic_block, SemanticBlock)
                and bool(selection.semantic_block.context_facts))

    async def _derive_supported_teaching(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact], *,
                                         blocks: list[dict[str, Any]], prepared: Any, response: Any,
                                         language: Any, rendered: Any) -> FinalTeachingCatalog:
        from app.modules.ai.evidence_engine.provider_engine import lesson_surface_render_scope, render_supported_surface
        from app.modules.ai.final_teaching_eligibility import SupportedTeachingBlockRef, derive_final_teaching_catalog
        from app.modules.ai.final_teaching_eligibility import _digest as teaching_digest
        from app.modules.ai.lesson_surface_support_language import (
            prepare_support_language,
            support_language_response_valid,
        )

        selection = await self.verified_semantic_selection(lesson, facts_by_id)
        if selection is None or not selection.block.context_facts:
            raise ContextProjectionError("semantic_block_handoff_identity", {})
        language_prepared = prepare_support_language(prepared, response, blocks)
        if not support_language_response_valid(language_prepared, prepared, response, blocks, language):
            raise ContextProjectionError("semantic_block_handoff_identity", {})
        checked = await render_supported_surface(assessor=self, base_lesson=lesson, facts_by_id=facts_by_id,
            blocks=blocks, prepared=prepared, response=response, checkpoint=self.checkpoint)
        if checked != rendered or not checked.requires_review or checked.publishable:
            raise ContextProjectionError("semantic_block_handoff_identity", {})
        base_blocks = [{key: row[key] for key in ("heading", "text", "fact_ids")} for row in blocks]
        scope = lesson_surface_render_scope(prepared=prepared.base, result=response._result, base_lesson=lesson,
            plan_fact_ids=set(lesson.fact_ids), facts_by_id=facts_by_id, blocks=base_blocks)
        catalog = derive_final_teaching_catalog(lesson=checked.lesson, prepared=prepared.base,
                                                surface_scope=scope, final_blocks=checked.blocks)
        if (not catalog.entries or catalog.gaps or any(not set(entry.fact_ids) <= set(lesson.fact_ids)
                                                       for entry in catalog.entries)):
            raise ContextProjectionError("semantic_block_teaching_unproved", {})
        neighbors: dict[str, set[str]] = {fact.fact_id: set() for fact in (*selection.block.owned_facts, *selection.block.context_facts)}
        for edge in selection.block.dependencies:
            neighbors[edge.from_fact_id].add(edge.to_fact_id)
        for fact_id, ancestors in selection.block.ancestor_ids_by_fact:
            if fact_id in neighbors:
                neighbors[fact_id].update(ancestors)
        entries = []
        for entry in catalog.entries:
            matches = [block for block in checked.blocks if block.heading == entry.heading and block.text == entry.body
                       and set(block.fact_ids) == set(entry.fact_ids)]
            if len(matches) != 1:
                raise ContextProjectionError("semantic_block_teaching_unproved", {})
            supporting_ids = matches[0].supporting_fact_ids
            if supporting_ids:
                links: list[tuple[str, str]] = []
                for owner in entry.fact_ids:
                    pending, reached = [owner], {owner}
                    while pending:
                        for fid in neighbors.get(pending.pop(), ()):
                            if fid not in reached:
                                reached.add(fid)
                                pending.append(fid)
                    links.extend((owner, fid) for fid in supporting_ids if fid in reached)
                if {support for _, support in links} != set(supporting_ids):
                    raise ContextProjectionError("semantic_block_teaching_unproved", {})
                binding = teaching_digest({"policy": "supported-teaching-ref-v1", "ref_id": entry.ref_id,
                    "body_sha256": entry.body_sha256, "owned_fact_ids": list(entry.fact_ids),
                    "supporting_fact_ids": list(supporting_ids), "owner_support_links": links,
                    "support_request_sha256": prepared.request_sha256,
                    "support_context_sha256": prepared.context_sha256, "semantic_response": asdict(response),
                    "language_response": asdict(language)})
                entry = SupportedTeachingBlockRef(entry.ref_id, entry.lesson_id, entry.block_id, entry.block_index,
                    entry.fact_ids, entry.heading, entry.body, entry.body_start, entry.body_end, entry.body_sha256,
                    entry.dependency_refs, supporting_ids, tuple(links), binding)
            entries.append(entry)
        custody = teaching_digest({"policy": "supported-teaching-custody-v1", "base": catalog.custody_sha256,
            "support_request": prepared.request_payload, "semantic_response": asdict(response),
            "language_response": asdict(language), "render": asdict(checked)})
        body = {"policy": catalog.policy, "lesson_id": catalog.lesson_id, "lesson_sha256": catalog.lesson_sha256,
                "content_sha256": catalog.content_sha256, "custody_sha256": custody,
                "entries": [asdict(row) for row in entries], "gaps": [asdict(row) for row in catalog.gaps]}
        return SupportedFinalTeachingCatalog(catalog.policy, catalog.lesson_id, catalog.lesson_sha256,
            catalog.content_sha256, custody, teaching_digest(body), tuple(entries), catalog.gaps, custody)

    @_serialize_lesson_mutation
    async def bind_semantic_render_source(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact], *,
                                          blocks: list[dict[str, Any]], prepared: Any, response: Any,
                                          language: Any, rendered: Any, durable: bool = True) -> FinalTeachingCatalog:
        """Bind original source and exact supported teaching evidence for this worker."""
        if type(durable) is not bool:
            raise ContextProjectionError("semantic_teaching_persist_invalid", {})
        if not durable and isinstance(getattr(self.journal, "job_id", None), str):
            # Do not leave an older durable positive available after a repair
            # unless the complete prior-negative chain can also be restored.
            raise ContextProjectionError("semantic_teaching_repair_chain_not_persisted", {})
        catalog = await self._derive_supported_teaching(lesson, facts_by_id, blocks=blocks, prepared=prepared,
                                                         response=response, language=language, rendered=rendered)
        self._prepared_semantic_source_lessons[lesson.lesson_id] = source_only_plan_lesson(lesson)
        self._supported_teaching_custody[lesson.lesson_id] = {"source_lesson": lesson, "blocks": deepcopy(blocks),
            "prepared": prepared, "response": response, "language": language, "rendered": rendered, "catalog": catalog}
        if durable and isinstance(getattr(self.journal, "job_id", None), str):
            persisted = False
            try:
                await self._persist_supported_teaching(lesson, facts_by_id)
                persisted = True
            finally:
                if not persisted:
                    self._prepared_semantic_source_lessons.pop(lesson.lesson_id, None)
                    self._supported_teaching_custody.pop(lesson.lesson_id, None)
        return catalog

    def _supported_teaching_key(self, lesson_id: str) -> str:
        return "supported-teaching-v1:" + _digest([self.tenant_id, lesson_id])

    async def _persist_supported_teaching(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> None:
        from app.modules.ai.lesson_prose_language import LESSON_PROSE_LANGUAGE_PROMPT
        from app.modules.ai.lesson_surface_support import SUPPORT_REVIEW_PROMPT

        selection = await self.verified_semantic_selection(lesson, facts_by_id)
        custody = self._supported_teaching_custody.get(lesson.lesson_id)
        job_id = getattr(self.journal, "job_id", None)
        if selection is None or custody is None or not isinstance(job_id, str) or not job_id:
            raise ContextProjectionError("semantic_teaching_persist_invalid", {})
        value = {"policy": "supported-teaching-journal-v1", "tenant_id": self.tenant_id, "job_id": job_id,
            "lesson_id": lesson.lesson_id, "source_lesson": asdict(source_only_plan_lesson(lesson)),
            "intent": deepcopy(self._source_intents.get(lesson.lesson_id)), "plan_key": selection.plan_key,
            "plan_input_sha256": selection.plan_input_sha256, "plan_audit_sha256": selection.plan_audit_sha256,
            "plan_evidence_sha256": selection.plan_evidence_sha256, "block_sha256": _digest(asdict(selection.block)),
            "blocks": deepcopy(custody["blocks"]), "support_request_sha256": custody["prepared"].request_sha256,
            "support_context_sha256": custody["prepared"].context_sha256,
            "semantic_raw": custody["response"]._provider_wire_json,
            "language_raw": list(custody["language"]._raw_batch_json),
            "semantic_prompt_sha256": _digest(SUPPORT_REVIEW_PROMPT),
            "language_prompt_sha256": _digest(LESSON_PROSE_LANGUAGE_PROMPT),
            "render_sha256": _digest(asdict(custody["rendered"])), "catalog_sha256": _digest(asdict(custody["catalog"]))}
        value["receipt_sha256"] = _digest(value)
        key = self._supported_teaching_key(lesson.lesson_id)
        existing = await self.journal.prepare(key, {"policy": value["policy"], "tenant_id": self.tenant_id,
                                                     "job_id": job_id, "lesson_id": lesson.lesson_id})
        if existing is None:
            await self.journal.save_value(key, value)
        elif existing != value:
            raise ContextProjectionError("semantic_teaching_persist_conflict", {})

    async def _restore_supported_teaching(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact]) -> bool:
        """Restore a job-owned receipt without allowing source or review calls."""
        from app.modules.ai.evidence_engine.provider_engine import render_supported_surface
        from app.modules.ai.lesson_prose_language import LESSON_PROSE_LANGUAGE_PROMPT
        from app.modules.ai.lesson_surface_support import (
            SUPPORT_REVIEW_PROMPT,
            _strict_json,
            parse_support_surface,
            prepare_support_surface,
            support_response_valid,
        )
        from app.modules.ai.lesson_surface_support_language import (
            parse_support_language,
            prepare_support_language,
            support_language_response_valid,
        )

        job_id = getattr(self.journal, "job_id", None)
        reader = getattr(self.journal, "read_value", None)
        if not isinstance(job_id, str) or not job_id or not callable(reader):
            return False
        key = self._supported_teaching_key(lesson.lesson_id)
        saved = await reader(key)
        if not isinstance(saved, dict):
            return False
        value = deepcopy(saved)
        digest = value.pop("receipt_sha256", None)
        if (digest != _digest(value) or value.get("policy") != "supported-teaching-journal-v1"
                or value.get("tenant_id") != self.tenant_id or value.get("job_id") != job_id
                or value.get("lesson_id") != lesson.lesson_id or not isinstance(value.get("source_lesson"), dict)
                or value.get("semantic_prompt_sha256") != _digest(SUPPORT_REVIEW_PROMPT)
                or value.get("language_prompt_sha256") != _digest(LESSON_PROSE_LANGUAGE_PROMPT)
                or not isinstance(value.get("intent"), dict) or not isinstance(value.get("blocks"), list)
                or not isinstance(value.get("language_raw"), list)):
            return False
        source_data = dict(value["source_lesson"])
        source_data["fact_ids"] = tuple(source_data["fact_ids"])
        source_data["supporting_fact_ids"] = tuple(source_data["supporting_fact_ids"])
        source_lesson = LessonDraft(**source_data)
        if source_lesson.lesson_id != lesson.lesson_id or source_lesson.content:
            return False
        self._source_intents[lesson.lesson_id] = deepcopy(value["intent"])
        self._audit_first_lessons.add(lesson.lesson_id)
        selected = self._select_source_context(source_lesson, facts_by_id)
        if not isinstance(selected.semantic_block, SemanticBlock) or selected.semantic_block.requires_review:
            return False
        identity = self._source_plan_identity(source_lesson, list(selected.local_facts), facts_by_id,
            counter_sharded=len(selected.counter_shards) > 1 or selected.semantic_block is not None, selection=selected)
        plan_key = "source-plan:" + _digest(identity)
        if (plan_key != value.get("plan_key") or _digest(identity) != value.get("plan_input_sha256")
                or _digest(asdict(selected.semantic_block)) != value.get("block_sha256")):
            return False
        saved_plan = await reader(plan_key)
        saved_plan = deepcopy(saved_plan)
        if not isinstance(saved_plan, dict) or _digest(saved_plan) != value.get("plan_evidence_sha256"):
            return False
        if self._source_plan_factory.description_review:
            client = _MeasuredClient(self.client, self.checkpoint)
            try:
                plan = await self._build_source_plan(source_lesson, [facts_by_id[fid] for fid in source_lesson.fact_ids],
                    list(selected.local_facts), client=client, saved_evidence=deepcopy(saved_plan), audit_first=True)
            finally:
                previous = self._prepared_costs.get(plan_key, (0, 0))
                self._prepared_costs[plan_key] = (previous[0] + client.calls, previous[1] + client.attempts)
            current_selection = self._select_source_context(source_lesson, facts_by_id)
            current_identity = self._source_plan_identity(source_lesson, list(current_selection.local_facts), facts_by_id,
                counter_sharded=len(current_selection.counter_shards) > 1 or current_selection.semantic_block is not None,
                selection=current_selection)
            if (_digest(current_identity) != _digest(identity) or not _reviewed_evidence_matches(plan.evidence, saved_plan)
                    or not json_equivalent(await reader(plan_key), saved_plan)
                    or not json_equivalent(await reader(key), saved)):
                return False
            current_selection = self._select_source_context(source_lesson, facts_by_id)
            current_identity = self._source_plan_identity(source_lesson, list(current_selection.local_facts), facts_by_id,
                counter_sharded=len(current_selection.counter_shards) > 1 or current_selection.semantic_block is not None,
                selection=current_selection)
            if _digest(current_identity) != _digest(identity) or getattr(self.journal, "job_id", None) != job_id:
                return False
            self._reviewed_source_plans[lesson.lesson_id] = (plan_key, _digest(identity), _digest(saved_plan), job_id, deepcopy(plan))
        else:
            plan = await self._build_source_plan(source_lesson, [facts_by_id[fid] for fid in source_lesson.fact_ids],
                list(selected.local_facts), client=_NoSemanticHandoffProvider(), saved_evidence=deepcopy(saved_plan), audit_first=True)
        if (plan.requires_review or (not self._source_plan_factory.description_review and (plan.model_calls != 0 or plan.attempt_count != 0))
                or (not self._source_plan_factory.description_review and _digest(plan.evidence) != value.get("plan_evidence_sha256"))
                or (plan.evidence.get("plan_audit_sha256") or _digest(plan.evidence)) != value.get("plan_audit_sha256")):
            return False
        handoff = VerifiedSemanticSelection("verified-semantic-selection-v1", self.tenant_id, lesson.lesson_id,
            plan_key, _digest(identity), value["plan_audit_sha256"], value["plan_evidence_sha256"], selected.semantic_block)
        self._verified_semantic_selections[lesson.lesson_id] = handoff
        self._verified_semantic_selection_digests[lesson.lesson_id] = _digest(asdict(handoff))
        self._prepared_source_keys[lesson.lesson_id] = plan_key
        self._prepared_semantic_keys[lesson.lesson_id] = plan_key
        self._prepared_source_statuses[lesson.lesson_id] = {"state": "accepted"}
        context = await self.semantic_author_context(source_lesson, facts_by_id)
        if context is None:
            return False
        blocks = value["blocks"]
        prepared = prepare_support_surface(lesson_id=lesson.lesson_id, owned_fact_ids=source_lesson.fact_ids,
            facts_by_id=facts_by_id, blocks=blocks, verified_context=context)
        if (prepared.request_sha256 != value.get("support_request_sha256")
                or prepared.context_sha256 != value.get("support_context_sha256")):
            return False
        response = parse_support_surface(prepared, _strict_json(value["semantic_raw"]), wire_raw=value["semantic_raw"])
        if not support_response_valid(prepared, response, positive=True):
            return False
        language_prepared = prepare_support_language(prepared, response, blocks)
        language = parse_support_language(language_prepared, prepared, response, tuple(value["language_raw"]))
        if not support_language_response_valid(language_prepared, prepared, response, blocks, language):
            return False
        rendered = await render_supported_surface(assessor=self, base_lesson=source_lesson, facts_by_id=facts_by_id,
            blocks=blocks, prepared=prepared, response=response, checkpoint=self.checkpoint)
        if rendered.lesson != lesson or _digest(asdict(rendered)) != value.get("render_sha256"):
            return False
        catalog = await self._derive_supported_teaching(source_lesson, facts_by_id, blocks=blocks,
            prepared=prepared, response=response, language=language, rendered=rendered)
        if (_digest(asdict(catalog)) != value.get("catalog_sha256") or not json_equivalent(await reader(key), saved)
                or not json_equivalent(await reader(plan_key), saved_plan)):
            return False
        self._prepared_semantic_source_lessons[lesson.lesson_id] = source_lesson
        self._supported_teaching_custody[lesson.lesson_id] = {"source_lesson": source_lesson,
            "blocks": deepcopy(blocks), "prepared": prepared, "response": response, "language": language,
            "rendered": rendered, "catalog": catalog}
        return True

    def _clear_supported_restoration(self, lesson_id: str) -> None:
        self._verified_semantic_selections.pop(lesson_id, None)
        self._verified_semantic_selection_digests.pop(lesson_id, None)
        self._reviewed_source_plans.pop(lesson_id, None)
        self._prepared_semantic_source_lessons.pop(lesson_id, None)
        self._supported_teaching_custody.pop(lesson_id, None)
        self._prepared_source_keys.pop(lesson_id, None)
        self._prepared_semantic_keys.pop(lesson_id, None)
        self._prepared_source_statuses.pop(lesson_id, None)
        self._source_intents.pop(lesson_id, None)
        self._audit_first_lessons.discard(lesson_id)

    @_serialize_lesson_mutation
    async def restore_supported_teaching_catalog(self, lesson: LessonDraft,
                                                  facts_by_id: dict[str, SourceFact]) -> SupportedFinalTeachingCatalog | None:
        """Explicitly rebuild job-owned supported custody after a process restart."""
        restored = False
        try:
            if not await self.semantic_support_required(lesson, facts_by_id):
                return None
            if not await self._restore_supported_teaching(lesson, facts_by_id):
                return None
            catalog = self._supported_teaching_custody[lesson.lesson_id]["catalog"]
            if isinstance(catalog, SupportedFinalTeachingCatalog):
                restored = True
                return catalog
        except Exception:
            pass
        finally:
            if not restored:
                self._clear_supported_restoration(lesson.lesson_id)
        return None

    async def validate_semantic_author_citations(
        self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact], blocks: list[dict[str, Any]],
    ) -> None:
        """Check citation custody only; independent source/prose review remains required."""
        selection = await self.verified_semantic_selection(lesson, facts_by_id)
        if selection is None or not isinstance(blocks, list) or not blocks:
            raise ContextProjectionError("semantic_author_citations", {})
        block = selection.block
        owned = {fact.fact_id for fact in block.owned_facts}
        support = {fact.fact_id for fact in block.context_facts}
        neighbors: dict[str, set[str]] = {fact.fact_id: set() for fact in (*block.owned_facts, *block.context_facts)}
        for edge in block.dependencies:
            neighbors[edge.from_fact_id].add(edge.to_fact_id)
        for fact_id, ancestors in block.ancestor_ids_by_fact:
            if fact_id in neighbors:
                neighbors[fact_id].update(ancestors)
        covered_owned: set[str] = set()
        for row in blocks:
            if not isinstance(row, dict):
                raise ContextProjectionError("semantic_author_citations", {})
            primary, cited = row.get("fact_ids"), row.get("supporting_fact_ids")
            if (not isinstance(primary, list) or not primary or not isinstance(cited, list)
                    or any(not isinstance(fid, str) for fid in (*primary, *cited))
                    or len(set(primary)) != len(primary) or len(set(cited)) != len(cited)
                    or not set(primary) <= owned or not set(cited) <= support):
                raise ContextProjectionError("semantic_author_citations", {})
            pending, reached = list(primary), set(primary)
            while pending:
                for fid in neighbors.get(pending.pop(), ()):
                    if fid not in reached:
                        reached.add(fid)
                        pending.append(fid)
            if set(cited) != reached & support:
                raise ContextProjectionError("semantic_author_citations", {})
            covered_owned.update(primary)
        if covered_owned != owned:
            raise ContextProjectionError("semantic_author_citations", {})

    @_serialize_lesson_mutation
    async def prepare_source_plan(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact],
                                  *, intent: CourseIntent) -> dict[str, Any]:
        """Prepare the existing source audit once, before learner prose exists.

        The author receives a projection, not mutable canonical ownership. The
        assessor later restores/revalidates the same journal plan without calls.
        Rebuild this projection on every restore; its version does not change
        the canonical source-plan cache identity or audit digest.
        """
        await self.checkpoint()
        self._verified_semantic_selections.pop(lesson.lesson_id, None)
        self._verified_semantic_selection_digests.pop(lesson.lesson_id, None)
        self._reviewed_source_plans.pop(lesson.lesson_id, None)
        self._prepared_semantic_source_lessons.pop(lesson.lesson_id, None)
        self._supported_teaching_custody.pop(lesson.lesson_id, None)
        self._source_intents[lesson.lesson_id] = asdict(intent)
        self._audit_first_lessons.add(lesson.lesson_id)
        source_lesson = source_only_plan_lesson(lesson)
        try:
            selection = self._select_source_context(source_lesson, facts_by_id)
        except ContextProjectionError as exc:
            self._prepared_source_statuses[lesson.lesson_id] = {"state": "context_rejected", "error_code": exc.code}
            return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                    "requires_review": True,
                    "source_context_error": exc.code, "critical_targets": []}
        context = list(selection.local_facts)
        semantic = selection.semantic_block is not None
        identity = self._source_plan_identity(source_lesson, context, facts_by_id,
            counter_sharded=len(selection.counter_shards) > 1 or semantic, selection=selection)
        key = "source-plan:" + _digest(identity)
        review_job_id = getattr(self.journal, "job_id", None)
        if self._source_plan_factory.description_review and (not isinstance(review_job_id, str) or not review_job_id):
            return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                    "input_sha256": _digest(identity), "requires_review": True,
                    "source_plan_rejected": True, "critical_targets": []}
        if self._semantic_block_provider is not None and self._semantic_closure_verifier is not None:
            self._prepared_semantic_keys[lesson.lesson_id] = key
        else:
            self._prepared_semantic_keys.pop(lesson.lesson_id, None)
        self._prepared_source_keys[lesson.lesson_id] = key
        saved = await self.journal.prepare(key, {"input_sha256": _digest(identity), "input": identity})
        saved = deepcopy(saved)
        client = _MeasuredClient(self.client, self.checkpoint)
        try:
            if saved is not None and saved.get("rejected") is True:
                self._prepared_source_statuses[lesson.lesson_id] = {
                    "state": "rejected", "error_code": self._safe_source_error_code(saved.get("error_code"))}
                return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                        "input_sha256": _digest(identity),
                        "requires_review": True, "source_plan_rejected": True, "critical_targets": []}
            plan = await self._build_source_plan(source_lesson,
                [facts_by_id[fid] for fid in lesson.fact_ids], context, client=client,
                saved_evidence=saved, audit_first=True)
        except SourcePlanError as exc:
            error_code = self._safe_source_error_code(str(exc))
            self._prepared_source_statuses[lesson.lesson_id] = {"state": "rejected", "error_code": error_code}
            if not self._source_plan_factory.description_review:
                await self.journal.save_value(key, {"rejected": True, "policy": self.source_plan_policy,
                                                   "error_code": error_code, "evidence": exc.evidence})
            return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                    "input_sha256": _digest(identity),
                    "requires_review": True, "source_plan_rejected": True, "critical_targets": []}
        finally:
            previous = self._prepared_costs.get(key, (0, 0))
            self._prepared_costs[key] = (previous[0] + client.calls, previous[1] + client.attempts)
        if self._source_plan_factory.description_review:
            # Cold re-review may not rewrite or silently diverge from the journal.
            selected_now = self._select_source_context(source_lesson, facts_by_id)
            current = self._source_plan_identity(source_lesson, list(selected_now.local_facts), facts_by_id,
                counter_sharded=len(selected_now.counter_shards) > 1 or selected_now.semantic_block is not None,
                selection=selected_now)
            if (_digest(current) != _digest(identity) or getattr(self.journal, "job_id", None) != review_job_id
                    or (saved is not None and not _reviewed_evidence_matches(plan.evidence, saved))
                    or (saved is not None and not json_equivalent(await self.journal.read_value(key), saved))):
                self._prepared_source_statuses[lesson.lesson_id] = {"state": "rejected", "error_code": "source_plan_rejected"}
                return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                        "input_sha256": _digest(identity), "requires_review": True,
                        "source_plan_rejected": True, "critical_targets": []}
        if saved is None:
            await self.journal.save_value(key, plan.evidence)
        journal_snapshot = deepcopy(saved if saved is not None else plan.evidence)
        if self._source_plan_factory.description_review:
            if not json_equivalent(await self.journal.read_value(key), journal_snapshot):
                self._prepared_source_statuses[lesson.lesson_id] = {"state": "rejected", "error_code": "source_plan_rejected"}
                return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                        "input_sha256": _digest(identity), "requires_review": True,
                        "source_plan_rejected": True, "critical_targets": []}
            selected_now = self._select_source_context(source_lesson, facts_by_id)
            current = self._source_plan_identity(source_lesson, list(selected_now.local_facts), facts_by_id,
                counter_sharded=len(selected_now.counter_shards) > 1 or selected_now.semantic_block is not None,
                selection=selected_now)
            if _digest(current) != _digest(identity) or getattr(self.journal, "job_id", None) != review_job_id:
                return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
                        "input_sha256": _digest(identity), "requires_review": True,
                        "source_plan_rejected": True, "critical_targets": []}
            self._reviewed_source_plans[lesson.lesson_id] = (key, _digest(identity), _digest(journal_snapshot), cast(str, review_job_id), deepcopy(plan))
        admitted = set(plan.admitted_target_ids)
        self._prepared_source_statuses[lesson.lesson_id] = {
            "state": "review_required" if plan.requires_review else "accepted"}
        if semantic and not plan.requires_review and isinstance(selection.semantic_block, SemanticBlock):
            self._verified_semantic_selections[lesson.lesson_id] = VerifiedSemanticSelection(
                "verified-semantic-selection-v1", self.tenant_id, lesson.lesson_id, key, _digest(identity),
                plan.evidence.get("plan_audit_sha256") or _digest(plan.evidence), _digest(journal_snapshot),
                selection.semantic_block)
            self._verified_semantic_selection_digests[lesson.lesson_id] = _digest(
                asdict(self._verified_semantic_selections[lesson.lesson_id]))
        return {"policy": self.source_plan_policy, "author_projection_policy": SOURCE_AUTHOR_CONTRACT_POLICY,
            "input_sha256": _digest(identity),
            "plan_audit_sha256": plan.evidence.get("plan_audit_sha256") or _digest(plan.evidence),
            "requires_review": plan.requires_review,
            "critical_targets": [{"id": target.target_id,
                "context": target.context,
                "display_context": {
                    "fixed_source_context": deepcopy(target.fixed_source_context),
                    "case_context_bindings": deepcopy(list(target.case_context_bindings)),
                },
                "components": [{"source_fact_ids": list(owners), "source_alternatives": list(terms)}
                    for terms, owners in zip(target.answer_requirements, target.component_source_ids, strict=True)],
                "governing_bindings": deepcopy([
                    *target.original_context_bindings, *target.qualification_bindings])}
                for target in plan.targets if target.target_id in admitted],
            "unresolved_source_refs": list(plan.unresolved_source_refs),
            "unresolved_obligation_ids": list(plan.unresolved_obligation_ids)}

    @staticmethod
    def _safe_source_error_code(value: Any) -> str:
        # Failure messages may come from legacy checkpoints. Never put free
        # text, source excerpts, credentials or an exception payload in status.
        known = {"source_plan_rejected", "source_applications_incomplete", "source_applications_model_call_failed",
                 "source_applications_checkpoint_integrity", "source_applications_restore_rederivation",
                 "source_applications_unused_evidence", "source_applications_field_outside_scope",
                 "frame_answer_length_exceeded", "source_frame_quote_wire_resources"}
        return value if isinstance(value, str) and value in known else "source_plan_rejected"

    async def _load_prompt_inventory(self) -> tuple[str, dict[str, Any]]:
        payload = {
            "tenant_id": self.tenant_id,
            "policy": _PROMPT_INVENTORY_POLICY,
            "plan_policy": self.source_plan_policy,
            "cycle_policy": POLICY_VERSION,
            "learner_language_gate": self.learner_language_gate,
        }
        key = "question-prompt-inventory:" + _digest(payload)
        saved = await self.journal.prepare(key, payload)
        if saved is None:
            saved = {**payload, "packets": []}
        if (saved.get("tenant_id") != self.tenant_id
                or saved.get("policy") != _PROMPT_INVENTORY_POLICY
                or saved.get("plan_policy") != self.source_plan_policy
                or saved.get("cycle_policy") != POLICY_VERSION
                or not isinstance(saved.get("packets"), list)):
            raise ValueError("worker_prompt_inventory_identity")
        for row in saved["packets"]:
            if (not isinstance(row, dict) or not isinstance(row.get("owner"), str)
                    or not isinstance(row.get("previous_question_prompts"), list)
                    or not isinstance(row.get("accepted_question_prompts"), list)
                    or any(not isinstance(value, str) or not value.strip()
                           for key_name in ("previous_question_prompts", "accepted_question_prompts")
                           for value in row[key_name])):
                raise ValueError("worker_prompt_inventory_invalid")
        owners = [row["owner"] for row in saved["packets"]]
        if len(owners) != len(set(owners)):
            raise ValueError("worker_prompt_inventory_duplicate_owner")
        # Each version is immutable. A single sequence slot is shared by all
        # writers, so a stale concurrent result conflicts rather than bypassing
        # the prompt history it should have reviewed.
        versions = await self.journal.inventory_versions(key)
        if len(versions) > 10000:
            raise ValueError("worker_prompt_inventory_version_limit")
        try:
            versions.sort(key=lambda version: version["plan_payload"]["index"])
        except (KeyError, TypeError):
            raise ValueError("worker_prompt_inventory_version_invalid") from None
        for index, record in enumerate(versions):
            version_key = f"{key}:version:{index}"
            plan = record["plan_payload"]
            version = record["assessment_payload"]
            if (record["generation_key"] != self.journal._owned_key(version_key)
                    or record["plan_revision"] != f"{PLAN_POLICY}/{POLICY_VERSION}"
                    or record["module_key"] != "cycle" or record["lesson_key"] != "lesson"
                    or record["assessment_status"] != "completed"
                    or not isinstance(plan, dict) or plan.get("index") != index
                    or plan.get("policy") != _PROMPT_INVENTORY_POLICY
                    or plan.get("inventory_base_key") != key
                    or plan.get("previous_sha256") != _digest(saved)
                    or not isinstance(version, dict)
                    or version.get("previous_sha256") != plan["previous_sha256"]
                    or not isinstance(version.get("row"), dict)):
                raise ValueError("worker_prompt_inventory_version_invalid")
            row = version["row"]
            if (plan.get("owner") != row.get("owner") or plan.get("row_sha256") != _digest(row)
                    or not isinstance(row.get("owner"), str) or not row["owner"]
                    or row["owner"] in {item["owner"] for item in saved["packets"]}
                    or not isinstance(row.get("previous_question_prompts"), list)
                    or not isinstance(row.get("accepted_question_prompts"), list)
                    or any(not isinstance(value, str) or not value.strip()
                           for name in ("previous_question_prompts", "accepted_question_prompts")
                           for value in row[name])
                    or tuple(row["previous_question_prompts"]) != self._prior_prompts(saved, row["owner"])):
                raise ValueError("worker_prompt_inventory_version_invalid")
            saved = {**saved, "packets": [*saved["packets"], row]}
        return f"{key}:version:{len(versions)}", saved

    @staticmethod
    def _prior_prompts(inventory: dict[str, Any], owner: str) -> tuple[str, ...]:
        existing = next((row for row in inventory["packets"] if row["owner"] == owner), None)
        if existing is not None:
            return tuple(existing["previous_question_prompts"])
        return tuple(dict.fromkeys(
            prompt
            for row in inventory["packets"]
            for prompt in row["accepted_question_prompts"]
        ))

    async def _record_prompts(self, *, key: str, inventory: dict[str, Any], owner: str,
                              previous: tuple[str, ...], result: LessonCycleResult, packet: LessonPacket) -> None:
        accepted = tuple(question_inventory_key(packet, question) for question in result.questions)
        existing = next((row for row in inventory["packets"] if row["owner"] == owner), None)
        if existing is not None:
            if (tuple(existing["previous_question_prompts"]) != previous
                    or tuple(existing["accepted_question_prompts"]) != accepted):
                raise ValueError("worker_prompt_inventory_result_conflict")
            return
        row = {
            "owner": owner,
            "previous_question_prompts": list(previous),
            "accepted_question_prompts": list(accepted),
        }
        if previous != self._prior_prompts(inventory, owner):
            raise ValueError("worker_prompt_inventory_stale")
        # Find the slot by replaying the current durable prefix. Do not infer
        # the version from the number of legacy rows in the baseline.
        current_key, current = await self._load_prompt_inventory()
        if current_key != key or current != inventory:
            raise ValueError("worker_prompt_inventory_stale")
        base_key, index_text = key.rsplit(":version:", 1)
        index = int(index_text)
        plan = {"policy": _PROMPT_INVENTORY_POLICY, "inventory_base_key": base_key,
                "index": index, "previous_sha256": _digest(inventory),
                "owner": owner, "row_sha256": _digest(row)}
        value = {"previous_sha256": plan["previous_sha256"], "row": row}
        await self.journal.append_inventory_version(key, plan, value)
        inventory["packets"].append(row)

    async def assess_with_teaching(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact],
                                   *, catalogs: tuple[FinalTeachingCatalog, ...]) -> BlockAssessmentResult:
        return await self(lesson, facts_by_id, teaching_catalogs=catalogs)

    @_serialize_lesson_mutation
    async def __call__(self, lesson: LessonDraft, facts_by_id: dict[str, SourceFact], *,
                       teaching_catalogs: tuple[FinalTeachingCatalog, ...] | None = None) -> BlockAssessmentResult:
        self._restore_call_observations[lesson.lesson_id] = []
        await self.checkpoint()
        try:
            verified_support = await self.semantic_support_required(lesson, facts_by_id)
        except Exception:
            return BlockAssessmentResult((), {"engine": "lesson_cycle", "terminal_status": "review_required",
                "lesson_id": lesson.lesson_id, "coverage": {"requires_review": True, "final_teaching_unproved": True},
                "source_context": {"error": "semantic_teaching_custody_unproved"},
                "logical_model_calls": 0, "provider_attempt_count": 0}, 0)
        if (verified_support and lesson.lesson_id not in self._supported_teaching_custody
                and teaching_catalogs and isinstance(teaching_catalogs[-1], SupportedFinalTeachingCatalog)):
            restored = False
            try:
                restored = await self._restore_supported_teaching(lesson, facts_by_id)
            except Exception:
                pass
            finally:
                if not restored:
                    self._clear_supported_restoration(lesson.lesson_id)
        if verified_support and lesson.lesson_id in self._prepared_semantic_keys:
            try:
                selected = self._select_source_context(source_only_plan_lesson(lesson), facts_by_id)
                original = self._prepared_semantic_source_lessons.get(lesson.lesson_id)
                identity_lesson = original if original is not None and tuple(lesson.fact_ids) == tuple(original.fact_ids) else lesson
                identity = self._source_plan_identity(identity_lesson, list(selected.local_facts), facts_by_id,
                    counter_sharded=len(selected.counter_shards) > 1 or selected.semantic_block is not None,
                    selection=selected)
                if "source-plan:" + _digest(identity) != self._prepared_semantic_keys[lesson.lesson_id]:
                    raise ValueError("semantic_block_changed_after_preparation")
            except Exception:
                return BlockAssessmentResult((), {"engine": "lesson_cycle", "terminal_status": "review_required",
                    "lesson_id": lesson.lesson_id, "coverage": {"requires_review": True, "source_context_rejected": True},
                    "source_context": {"error": "semantic_block_changed_after_preparation"},
                    "logical_model_calls": 0, "provider_attempt_count": 0}, 0)
        supported = self._supported_teaching_custody.get(lesson.lesson_id)
        requires_supported_custody = (verified_support or supported is not None or lesson.lesson_id in self._prepared_semantic_source_lessons
            or any(isinstance(catalog, SupportedFinalTeachingCatalog) for catalog in teaching_catalogs or ()))
        if requires_supported_custody:
            try:
                current_is_supported = (verified_support or supported is not None or lesson.lesson_id in self._prepared_semantic_source_lessons
                    or bool(teaching_catalogs and isinstance(teaching_catalogs[-1], SupportedFinalTeachingCatalog)))
                if current_is_supported and (supported is None or not teaching_catalogs
                        or teaching_catalogs[-1] != supported["catalog"] or lesson != supported["rendered"].lesson):
                    raise ValueError("semantic_teaching_custody_unproved")
                for candidate in teaching_catalogs or ():
                    item = self._supported_teaching_custody.get(candidate.lesson_id)
                    if isinstance(candidate, SupportedFinalTeachingCatalog) or item is not None:
                        if item is None or candidate != item["catalog"]:
                            raise ValueError("semantic_teaching_custody_unproved")
                        current_supported_catalog = await self._derive_supported_teaching(item["source_lesson"], facts_by_id,
                            blocks=item["blocks"], prepared=item["prepared"], response=item["response"],
                            language=item["language"], rendered=item["rendered"])
                        if current_supported_catalog != candidate:
                            raise ValueError("semantic_teaching_custody_unproved")
            except Exception:
                return BlockAssessmentResult((), {"engine": "lesson_cycle", "terminal_status": "review_required",
                    "lesson_id": lesson.lesson_id, "coverage": {"requires_review": True, "final_teaching_unproved": True},
                    "source_context": {"error": "semantic_teaching_custody_unproved"},
                    "logical_model_calls": 0, "provider_attempt_count": 0}, 0)
        if teaching_catalogs is not None and (
            not teaching_catalogs or teaching_catalogs[-1].lesson_id != lesson.lesson_id
            or not teaching_catalogs[-1].entries
            or not catalog_matches_final_content(teaching_catalogs[-1],
                lesson_id=lesson.lesson_id, content=lesson.content)
        ):
            source_key = self._prepared_source_keys.get(lesson.lesson_id, "")
            prepared_calls, prepared_attempts = self._prepared_costs.pop(source_key, (0, 0))
            source_status = self._prepared_source_statuses.get(lesson.lesson_id, {"state": "not_prepared"})
            current = next((row for row in teaching_catalogs if row.lesson_id == lesson.lesson_id), None)
            current_status = ("missing" if current is None else "not_last" if teaching_catalogs[-1] is not current
                              else "empty" if not current.entries else "content_mismatch")
            return BlockAssessmentResult((), {
                "engine": "lesson_cycle", "terminal_status": "review_required", "lesson_id": lesson.lesson_id,
                "coverage": {"requires_review": True, "final_teaching_unproved": True,
                    **({"source_plan_rejected": source_status["state"] == "rejected"}
                       if source_status["state"] in {"accepted", "rejected", "review_required"} else {}),
                    **({"source_plan_requires_review": True} if source_status["state"] == "review_required" else {}),
                    **({"source_context_rejected": True} if source_status["state"] == "context_rejected" else {})},
                "source_prerequisite": deepcopy(source_status),
                "final_teaching": {"catalogs": [asdict(row) for row in teaching_catalogs],
                    "current_catalog_status": current_status, "current_catalog": asdict(current) if current else None,
                    "prior_catalogs": [asdict(row) for row in teaching_catalogs if row.lesson_id != lesson.lesson_id]},
                "logical_model_calls": prepared_calls, "provider_attempt_count": prepared_attempts,
            }, prepared_attempts)
        # An unproved earlier lesson contributes no eligible body. Keep its gap
        # in diagnostics, but do not let an empty, intentionally unbound catalog
        # invalidate the independently reviewed current lesson's entire registry.
        # The current catalog above remains mandatory; nonempty prior catalogs
        # still undergo the usual native custody checks.
        excluded_prior_catalogs = tuple(row for row in teaching_catalogs[:-1] if not row.entries) \
            if teaching_catalogs else ()
        if excluded_prior_catalogs and teaching_catalogs is not None:
            teaching_catalogs = (*tuple(row for row in teaching_catalogs[:-1] if row.entries), teaching_catalogs[-1])
        prior_diagnostics = ({"excluded_prior_teaching_catalogs": [asdict(row) for row in excluded_prior_catalogs]}
                             if excluded_prior_catalogs else {})
        client = _MeasuredClient(self.client, self.checkpoint)
        primary = [facts_by_id[fid] for fid in lesson.fact_ids]
        try:
            selection = self._select_source_context(source_only_plan_lesson(lesson), facts_by_id)
        except ContextProjectionError as exc:
            return BlockAssessmentResult((), {
                "engine": "lesson_cycle", "terminal_status": "review_required", "lesson_id": lesson.lesson_id,
                "coverage": {"requires_review": True, "source_context_rejected": True},
                **prior_diagnostics,
                "source_context": {"error": exc.code, "evidence": dict(exc.evidence)},
                "logical_model_calls": 0, "provider_attempt_count": 0,
            }, 0)
        context = list(selection.local_facts)
        excerpts = {fid: SourceExcerpt(_digest(asdict(f)), "\n".join(source_context_fields(f)), f.value)
                    for fid, f in facts_by_id.items()}
        sources = tuple(excerpts[f.fact_id] for f in context)
        semantic = selection.ledger.get("mode") == "semantic_block"
        counter_shards = (tuple(tuple(excerpts[f.fact_id] for f in shard) for shard in selection.counter_shards)
                          if len(selection.counter_shards) > 1 or semantic else ())
        full_counter = semantic and selection.ledger.get("semantic_full_counter") is True
        counter_coverage = (tuple(source.source_id for source in counter_shards[0]) if full_counter
                            else tuple(excerpts[fid].source_id for fid in facts_by_id) if counter_shards else ())
        scope = (full_counter_scope(self.tenant_id, lesson.lesson_id, selection.ledger["semantic_source_inventory_sha256"],
                                    selection.ledger["semantic_block_sha256"], counter_shards[0]) if full_counter else None)
        raw_chars = sum(len(f.value) for f in context)
        rendered_chars = sum(len(source.text) for source in sources)
        if raw_chars > MAX_RAW_SOURCE_CHARS or rendered_chars > MAX_RENDERED_SOURCE_CHARS or len(sources) > 256:
            return BlockAssessmentResult((), {
                "engine": "lesson_cycle", "terminal_status": "review_required", "lesson_id": lesson.lesson_id,
                "coverage": {"requires_review": True, "source_context_rejected": True},
                **prior_diagnostics,
                "source_context": {"raw_chars": raw_chars, "rendered_chars": rendered_chars,
                                   "max_raw_chars": MAX_RAW_SOURCE_CHARS,
                                   "max_rendered_chars": MAX_RENDERED_SOURCE_CHARS},
                "logical_model_calls": 0, "provider_attempt_count": 0,
            }, 0)
        plan_lesson = lesson
        prepared_lesson = self._prepared_semantic_source_lessons.get(lesson.lesson_id)
        if prepared_lesson is not None and isinstance(selection.semantic_block, SemanticBlock):
            allowed_support = {fact.fact_id for fact in selection.semantic_block.context_facts}
            if (tuple(lesson.fact_ids) != tuple(prepared_lesson.fact_ids)
                    or not set(prepared_lesson.supporting_fact_ids) <= set(lesson.supporting_fact_ids)
                    or set(lesson.supporting_fact_ids) != allowed_support
                    or len(set(lesson.supporting_fact_ids)) != len(lesson.supporting_fact_ids)):
                return BlockAssessmentResult((), {"engine": "lesson_cycle", "terminal_status": "review_required",
                    "lesson_id": lesson.lesson_id, "coverage": {"requires_review": True, "source_context_rejected": True},
                    "source_context": {"error": "semantic_block_changed_after_preparation"},
                    "logical_model_calls": 0, "provider_attempt_count": 0}, 0)
            # Source plan evidence binds the original plan lesson, never the
            # derived presentation or newly attached source-only citations.
            plan_lesson = prepared_lesson
        identity = self._source_plan_identity(plan_lesson, context, facts_by_id,
            counter_sharded=bool(counter_shards) or selection.semantic_block is not None, selection=selection)
        plan_key = "source-plan:" + _digest(identity)
        review_job_id = getattr(self.journal, "job_id", None)
        if lesson.lesson_id in self._prepared_semantic_keys and self._prepared_semantic_keys[lesson.lesson_id] != plan_key:
            return BlockAssessmentResult((), {"engine": "lesson_cycle", "terminal_status": "review_required",
                "lesson_id": lesson.lesson_id, "coverage": {"requires_review": True, "source_context_rejected": True},
                "source_context": {"error": "semantic_block_changed_after_preparation"},
                "logical_model_calls": 0, "provider_attempt_count": 0}, 0)
        prepared_calls, prepared_attempts = self._prepared_costs.pop(plan_key, (0, 0))
        client.calls += prepared_calls
        client.attempts += prepared_attempts
        saved = await self.journal.prepare(plan_key, {"input_sha256": _digest(identity), "input": identity})
        saved = deepcopy(saved)
        def rejected(evidence: Any) -> BlockAssessmentResult:
            return BlockAssessmentResult((), {
                "engine": "lesson_cycle", "terminal_status": "review_required",
                "coverage": {"requires_review": True, "source_plan_rejected": True},
                **prior_diagnostics,
                "lesson_id": lesson.lesson_id, "source_plan_rejection": evidence,
                "logical_model_calls": client.calls, "provider_attempt_count": client.attempts,
            }, client.attempts)

        if saved is not None and saved.get("rejected") is True:
            return rejected(saved.get("evidence"))
        try:
            cached = self._reviewed_source_plans.get(lesson.lesson_id) if self._source_plan_factory.description_review else None
            if (cached is not None and saved is not None and cached[0] == plan_key and cached[1] == _digest(identity)
                    and cached[2] == _digest(saved) and cached[3] == getattr(self.journal, "job_id", None)):
                plan = deepcopy(cached[4])
            else:
                plan = await self._build_source_plan(plan_lesson, primary, context, client=client, saved_evidence=saved,
                    audit_first=lesson.lesson_id in self._audit_first_lessons)
        except SourcePlanError as exc:
            if not self._source_plan_factory.description_review:
                await self.journal.save_value(plan_key, {"rejected": True, "policy": self.source_plan_policy, "evidence": exc.evidence})
            return rejected(exc.evidence)
        if self._source_plan_factory.description_review:
            current_selection = self._select_source_context(plan_lesson, facts_by_id)
            current_identity = self._source_plan_identity(plan_lesson, list(current_selection.local_facts), facts_by_id,
                counter_sharded=len(current_selection.counter_shards) > 1 or current_selection.semantic_block is not None,
                selection=current_selection)
            if (_digest(current_identity) != _digest(identity) or not isinstance(review_job_id, str) or not review_job_id
                    or getattr(self.journal, "job_id", None) != review_job_id
                    or (saved is not None and not _reviewed_evidence_matches(plan.evidence, saved))
                    or (saved is not None and not json_equivalent(await self.journal.read_value(plan_key), saved))):
                return rejected({"error": "source_plan_identity_changed"})
        if saved is None:
            await self.journal.save_value(plan_key, plan.evidence)
        journal_snapshot = deepcopy(saved if saved is not None else plan.evidence)
        if self._source_plan_factory.description_review:
            if not json_equivalent(await self.journal.read_value(plan_key), journal_snapshot):
                return rejected({"error": "source_plan_identity_changed"})
            current_selection = self._select_source_context(plan_lesson, facts_by_id)
            current_identity = self._source_plan_identity(plan_lesson, list(current_selection.local_facts), facts_by_id,
                counter_sharded=len(current_selection.counter_shards) > 1 or current_selection.semantic_block is not None,
                selection=current_selection)
            if _digest(current_identity) != _digest(identity) or getattr(self.journal, "job_id", None) != review_job_id:
                return rejected({"error": "source_plan_identity_changed"})
        await self.checkpoint()
        if self._source_plan_factory.description_review:
            if not json_equivalent(await self.journal.read_value(plan_key), journal_snapshot):
                return rejected({"error": "source_plan_identity_changed"})
            current_selection = self._select_source_context(plan_lesson, facts_by_id)
            current_identity = self._source_plan_identity(plan_lesson, list(current_selection.local_facts), facts_by_id,
                counter_sharded=len(current_selection.counter_shards) > 1 or current_selection.semantic_block is not None,
                selection=current_selection)
            if _digest(current_identity) != _digest(identity) or getattr(self.journal, "job_id", None) != review_job_id:
                return rejected({"error": "source_plan_identity_changed"})
        # Keep full contextual rules, but preserve the owning fact boundary so
        # sibling exceptions can be checked without borrowing another rule's
        # schedule merely because it appeared in the same concatenated source.
        questions = []
        results = []
        operational_retained_ids: set[str] = set()
        # Bounds are per model response, not a license to omit targets.
        facet_owners = plan_facet_source_ids(plan)

        def mapped_target(target: Any) -> Any:
            mapped = replace(target, source_ids=tuple(dict.fromkeys(
                [_digest(asdict(facts_by_id[fid])) for fid, tids in plan.source_target_ids.items()
                 if target.target_id in tids]
                + [_digest(asdict(facts_by_id[fid])) for fid in facet_owners.get(target.target_id, ())]
                + [_digest(asdict(facts_by_id[fid])) for owners in target.component_source_ids for fid in owners]
                + [_digest(asdict(facts_by_id[binding["source_id"]]))
                   for binding in target.original_context_bindings])),
                component_source_ids=tuple(tuple(_digest(asdict(facts_by_id[fid])) for fid in owners)
                                           for owners in target.component_source_ids),
                qualification_bindings=tuple({**binding,
                    "source_id": _digest(asdict(facts_by_id[binding["source_id"]]))}
                    for binding in target.qualification_bindings),
                fixed_source_context=({**target.fixed_source_context,
                    "source_id": _digest(asdict(facts_by_id[target.fixed_source_context["source_id"]]))}
                    if target.fixed_source_context is not None else None),
                source_quote_proposition=({**target.source_quote_proposition,
                    "source_id": _digest(asdict(facts_by_id[target.source_quote_proposition["source_id"]]))}
                    if target.source_quote_proposition is not None else None),
                original_context_bindings=tuple({**binding,
                    "source_id": _digest(asdict(facts_by_id[binding["source_id"]]))}
                    for binding in target.original_context_bindings),
                case_context_bindings=_mapped_case_context_bindings(target, excerpts))
            return _assign_complete_clause_surface(
                mapped, plan.material_obligations, sources, enabled=self.learner_language_gate,
            )

        incomplete_case_target_ids = _incomplete_material_case_target_ids(
            plan, allow_application_edges=self.source_plan_mode == "application_first")
        admitted = tuple(mapped_target(target) for target in plan.targets
            if target.target_id in plan.admitted_target_ids
            and target.target_id not in incomplete_case_target_ids)
        inventory_key = ""
        inventory: dict[str, Any] = {"packets": []}
        if admitted:
            inventory_key, inventory = await self._load_prompt_inventory()
        assessment_batches, oversized_case_target_ids = _assessment_target_batches(admitted)
        case_batch_unassessed_target_ids = tuple(dict.fromkeys(
            (*incomplete_case_target_ids, *oversized_case_target_ids)))
        support_export_blocked: set[str] = set()
        local_joint_blocked: set[str] = set()
        pending_questions: list[tuple[LessonPacket, ReviewedQuestion]] = []
        batch_start = 0
        shared_case_budget = CaseCitationCycleBudget(12 if self.case_citation_evaluation else MAX_CASE_CITATION_LOGICAL_CALLS) if self.experimental_case_citation else None
        for batch in assessment_batches:
            await self.checkpoint()
            owner = _digest({
                "tenant_id": self.tenant_id,
                "lesson_id": lesson.lesson_id,
                "source_plan_key": plan_key,
                "batch_start": batch_start,
                "target_ids": [target.target_id for target in batch],
            })
            previous = self._prior_prompts(inventory, owner)
            packet = prepare_component_construction(LessonPacket(self.tenant_id, lesson.lesson_id, lesson.title, lesson.content,
                                  sources, batch, self.source_plan_policy, previous_question_prompts=previous,
                                  learner_language_gate=self.learner_language_gate,
                                  experimental_case_citation=self.experimental_case_citation,
                                  case_citation_evaluation=self.case_citation_evaluation,
                                  counter_source_shards=counter_shards, counter_source_coverage=counter_coverage,
                                  semantic_full_counter=scope,
                                  teaching_catalogs=teaching_catalogs,
                                  teaching_source_fact_ids=tuple((row.source_id, fid) for fid, row in excerpts.items())
                                      if teaching_catalogs is not None else (),
                                  teaching_source_facts=tuple(context)
                                      if teaching_catalogs is not None else ()))
            key = "lesson-cycle:" + packet.identity()
            value = await self.journal.prepare(key, {"packet": packet.storage_payload()})
            store = _CycleStore(self.journal, packet, value, key)
            def observe_restore(observation: dict[str, Any], lesson_id: str = lesson.lesson_id) -> None:
                self._restore_call_observations[lesson_id].append(dict(observation))

            flags: dict[str, Any] = {"restore_observer": observe_restore, "_shared_case_budget": shared_case_budget} if self.experimental_case_citation else {}
            result = (await run_lesson_cycles([packet], client=client, store=store, **flags))[0]
            await self._record_prompts(key=inventory_key, inventory=inventory, owner=owner,
                                       previous=previous, result=result, packet=packet)
            inventory_key, inventory = await self._load_prompt_inventory()
            results.append(result)
            pending_questions.extend((packet, q) for q in result.questions)
            batch_start += len(batch)
        joint_candidates = []
        for packet, q in pending_questions:
            options = q.options if self.learner_language_gate else tuple(sorted(
                q.options, key=lambda option: _digest([packet.identity(), q.question_id, option])))
            joint_candidates.append({"id": _digest([packet.identity(), q.question_id]),
                "question": {"text": q.text, "options": list(options), "answer": q.options[q.correct_index]}})
        candidate_counts = {row["id"]: sum(other["id"] == row["id"] for other in joint_candidates)
                            for row in joint_candidates}
        unique_candidates = ([row for row in joint_candidates if candidate_counts[row["id"]] == 1]
                             if self._local_joint_reviewer is not None else joint_candidates)
        joint_verdicts = await self._local_joint_review_batch(lesson, facts_by_id, unique_candidates)
        current_candidates = []
        for packet, q in pending_questions:
            options = q.options if self.learner_language_gate else tuple(sorted(
                q.options, key=lambda option: _digest([packet.identity(), q.question_id, option])))
            current_candidates.append({"id": _digest([packet.identity(), q.question_id]),
                "question": {"text": q.text, "options": list(options), "answer": q.options[q.correct_index]}})
        if current_candidates != joint_candidates:
            joint_verdicts = {}
        for packet, q in pending_questions:
            # The lesson may contain facts beyond this question's exported
            # target owners. Validate custody against the exact exported set,
            # not the broader lesson context.
            fids = tuple(fid for fid, tids in plan.source_target_ids.items() if set(tids) & set(q.target_ids))
            if not fids:
                raise ValueError("worker_cycle_unowned_question")
            owners = set(fids)
            blocked = {target.target_id for target in plan.targets if target.target_id in q.target_ids
                and _target_needs_support_export(target, owners)}
            if _question_needs_support_export(q, {excerpts[fid].source_id for fid in owners}):
                blocked.update(q.target_ids)
            if blocked:
                # The native MCQ output has only one unqualified quote;
                # it cannot retain a separate supporting locator/quote.
                support_export_blocked.update(blocked)
                continue
            # The language receipt binds the exact ordered visible options.
            # Do not add an unreviewed permutation after this gate.
            options = q.options if self.learner_language_gate else tuple(sorted(
                q.options, key=lambda option: _digest([packet.identity(), q.question_id, option])))
            joint_id = _digest([packet.identity(), q.question_id])
            if not joint_verdicts.get(joint_id, False):
                local_joint_blocked.update(q.target_ids)
                continue
            operational_retained_ids.update(operational_question_target_ids(packet, q))
            key_evidence = [e for e in q.option_evidence if e["index"] == q.correct_index]
            key_owners = {e["source_id"] for e in key_evidence}
            # Admission validated these exact source spans. Export every
            # clause needed for the multi-component key, not only the one
            # passage chosen by the blind reviewer.
            proof_evidence = [proof for proof in (q.semantic_audit or {}).get("target_proofs", [])
                              if proof.get("target_id") in q.target_ids and proof.get("source_id") in key_owners]
            quotes = tuple(dict.fromkeys(str(e["quote"]) for e in [*key_evidence, *proof_evidence]))
            binary_identity, binary_focus, _ = ordinary_binary_source_identity(packet, q, q.correct_index)
            exported = QuestionDraft(
                question_id=f"{packet.identity()[:16]}:{q.question_id}", lesson_id=lesson.lesson_id,
                kind="single_choice", prompt=q.text, options=options,
                correct_answer=q.options[q.correct_index], explanation=q.explanation,
                fact_id=fids[0], evidence_fact_ids=fids,
                source_quote="\n".join(quotes),
                semantic_reviewed=True,
                source_response_budget=(source_response_budget_proof(packet, q.target_ids, q.options[q.correct_index])
                    if len(q.options[q.correct_index]) > 240 else None),
                source_rule_identity=binary_identity or (question_inventory_key(packet, q)
                    if q.source_edits is not None or q.intent == "source_recall" or (q.component_proposals is not None
                        and len(next(t.answer_requirements for t in packet.targets if t.target_id == q.target_ids[0])) == 1) else ""),
                source_rule_focus=binary_focus or (q.component_proposals[0]["action_focus"] if q.component_proposals is not None
                    and len(next(t.answer_requirements for t in packet.targets if t.target_id == q.target_ids[0])) == 1 else
                    next(t.assessed_focus for t in packet.targets if t.target_id == q.target_ids[0])
                    if q.source_edits is not None or q.intent == "source_recall" else ""),
            )
            inventory_identity = question_inventory_key(packet, q)
            if (q.question_form in {"source_proposition", "natural_scenario", COMPLETE_CLAUSE_FORM}
                    or inventory_identity.startswith("ordinary-competency:")):
                exported = replace(exported, assessment_inventory_identity=inventory_identity,
                    assessment_inventory_binding=assessment_inventory_binding(exported, inventory_identity))
                if q.question_form in {"natural_scenario", COMPLETE_CLAUSE_FORM}:
                    exported = replace(exported, source_rule_identity="", source_rule_focus="")
            questions.append(exported)
        missing = [t.target_id for t in plan.targets if t.target_id not in plan.admitted_target_ids]
        missing.extend(tid for result in results for tid in result.missing_target_ids)
        missing.extend(case_batch_unassessed_target_ids)
        missing.extend(sorted(support_export_blocked | local_joint_blocked))
        unassessed_source_gaps = [
            {**row, "target_ids": list(row["target_ids"])}
            for row in plan.unassessed_source_gaps
        ]
        missing.extend(
            target_id
            for row in plan.unassessed_source_gaps
            for target_id in row["target_ids"]
        )
        missing = list(dict.fromkeys(missing))
        retained_ids = {tid for result in results for question in result.questions for tid in question.target_ids}
        retained_ids.difference_update(support_export_blocked | local_joint_blocked)
        operational_retained_ids.difference_update(support_export_blocked | local_joint_blocked)
        unresolved_obligations = list(plan.unresolved_obligation_ids)
        unresolved_refs = set(plan.unresolved_source_refs)
        unresolved_obligations.extend(row["obligation_id"] for row in plan.unassessed_source_gaps)
        unresolved_refs.update(row["source_ref"] for row in plan.unassessed_source_gaps)
        covered_by_level = {"source_recognition": 0, "operational_decision": 0}
        material_rows = []
        actual_obligations = []
        for obligation in plan.material_obligations:
            eligible_ids = (operational_retained_ids
                            if obligation.evidence_level == "operational_decision" else retained_ids)
            actual_ids = tuple(tid for tid in obligation.target_ids if tid in eligible_ids)
            material_rows.append(asdict(replace(obligation, target_ids=actual_ids)))
            actual_obligations.append(replace(obligation, target_ids=actual_ids))
            if actual_ids:
                covered_by_level[obligation.evidence_level] += 1
            else:
                unresolved_obligations.append(obligation.obligation_id)
                unresolved_refs.add(obligation.source_ref)
        for obligation in operational_evidence_gaps(tuple(actual_obligations)):
            unresolved_obligations.append(obligation.obligation_id)
            unresolved_refs.add(obligation.source_ref)
        unresolved_obligations = list(dict.fromkeys(unresolved_obligations))
        # Legacy plans remain loadable, but absent material accounting is unknown
        # completeness, never a validated empty inventory or release-ready result.
        facet_status = plan_facet_status(plan, retained_ids)
        unresolved_dependency_edges = selection.ledger.get("unresolved_dependency_edges", ())
        requires_review = (bool(unresolved_dependency_edges) or self._local_joint_reviewer is not None or bool(missing or unresolved_obligations) or plan.requires_review
                           or not plan.material_inventory_present
                           or not facet_status["source_completeness"]["complete"]
                           or not facet_status["assessment_coverage"]["complete"])
        required_target_ids = {
            target.target_id for target in plan.targets
        } | {
            target_id
            for row in plan.unassessed_source_gaps
            for target_id in row["target_ids"]
        }
        return BlockAssessmentResult(tuple(questions), {
            "engine": "lesson_cycle", "policy": f"{self.source_plan_policy}/{POLICY_VERSION}",
            **prior_diagnostics,
            "terminal_status": "review_required" if requires_review else "ready_for_methodologist",
            **({"unresolved_dependency_edge_count": len(unresolved_dependency_edges)}
               if unresolved_dependency_edges else {}),
            **({"local_joint_review": "available-facts-only; not source completeness or approval authority",
                "local_joint_blocked_target_ids": sorted(local_joint_blocked)}
               if self._local_joint_reviewer is not None else {}),
            **({"assessment_applicability": "supporting_only",
                "teaching_contexts": [asdict(row) for row in plan.teaching_contexts]}
               if not required_target_ids and plan.teaching_contexts and not requires_review else {}),
            "coverage": {"requires_review": requires_review, "required_target_count": len(required_target_ids),
                         "retained_target_count": len(required_target_ids - set(missing)),
                         "missing_target_ids": missing,
                         "unresolved_source_refs": sorted(unresolved_refs),
                         "material_inventory_present": plan.material_inventory_present,
                         "material_obligation_count": len(plan.material_obligations),
                         "unresolved_obligation_ids": unresolved_obligations,
                         "covered_obligations_by_level": covered_by_level,
                         **({"support_source_export_unavailable": sorted(support_export_blocked)}
                            if support_export_blocked else {}),
                         **({"case_batch_unassessed_target_ids": list(case_batch_unassessed_target_ids)}
                            if case_batch_unassessed_target_ids else {})},
            "material_obligations": material_rows,
            "unassessed_source_gaps": unassessed_source_gaps,
            **facet_status,
            "source_plan": plan.evidence, "lesson_id": lesson.lesson_id,
            **({"historical_diagnostics": diagnostic} if self._source_plan_factory.description_review
               and (diagnostic := _historical_feedback_diagnostic(saved)) is not None else {}),
            "source_context": dict(selection.ledger),
            "logical_model_calls": client.calls, "provider_attempt_count": client.attempts,
            **({"restore_accounting": {
                "logical_model_calls": sum(row["logical_calls"] for row in self._restore_call_observations[lesson.lesson_id]),
                "physical_attempts": None, "physical_attempts_observation": "unavailable",
                "overlaps_logical_model_calls": True,
            }} if self._restore_call_observations[lesson.lesson_id] else {}),
            "results": [asdict(result) for result in results],
        }, client.attempts)
