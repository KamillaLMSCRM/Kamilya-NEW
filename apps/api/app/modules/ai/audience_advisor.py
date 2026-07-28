"""Read-only, tenant-scoped audience advice for the methodologist assistant.

The service deliberately returns aggregate organizational scopes instead of
people. It is also intentionally independent from the assignment routers:
recommendations can be calculated without creating or changing an
Enrollment, rule, cohort, user, or invitation.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.courses import Course
from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortMember
from app.modules.competencies.models import Competency, CompetencyCourse, PositionCompetency
from app.modules.lessons.models import Module
from app.modules.positions.models import DepartmentCourse, Position, PositionCourse
from app.modules.training_rules.models import OrganizationCourseRule

logger = logging.getLogger(__name__)


@dataclass
class ScopeCandidate:
    ref: str
    type: str
    id: UUID | None
    name: str
    employee_count: int
    priority: str = "secondary"
    confidence: str = "medium"
    reasons: list[str] = field(default_factory=list)
    position_ids: set[UUID] = field(default_factory=set)
    semantic_context: dict[str, str] = field(default_factory=dict)


@dataclass
class AudienceSnapshot:
    course: Course
    candidates: list[ScopeCandidate]
    warnings: list[str]
    already_enrolled_count: int
    active_student_count: int
    course_context: dict[str, Any] = field(default_factory=dict)


MAX_CANDIDATES = 40
MAX_LLM_PAYLOAD_CHARS = 18000
MAX_MODULES = 6
MAX_LESSONS_PER_MODULE = 3
MAX_SEMANTIC_FIELD_CHARS = 240


def _course_status(course: Course) -> str:
    if course.status == "published":
        return "published"
    if course.status == "archived":
        return "archived"
    return "review" if course.review_status == "needs_changes" else "draft"


def _active_student_filter(tenant_id: UUID):
    return (
        User.tenant_id == tenant_id,
        User.role == "student",
        User.is_active.is_(True),
        User.status == "active",
    )


def _find_candidate(candidates: list[ScopeCandidate], scope_type: str, scope_id: UUID | None, name: str = ""):
    for candidate in candidates:
        if candidate.type == scope_type and ((scope_id is not None and candidate.id == scope_id) or (scope_id is None and candidate.name.casefold() == name.casefold())):
            return candidate
    return None


async def _load_positions(db: AsyncSession, tenant_id: UUID) -> tuple[list[ScopeCandidate], dict[UUID, ScopeCandidate]]:
    rows = await db.execute(
        select(
            Position.id,
            Position.name,
            Position.department_id,
            Position.department,
            Position.responsibilities,
            Position.requirements,
            func.count(User.id),
        )
        .outerjoin(User, (User.position_id == Position.id) & (User.role == "student") & User.is_active.is_(True) & (User.status == "active"))
        .where(Position.tenant_id == tenant_id)
        .group_by(Position.id, Position.name, Position.department_id, Position.department)
        .order_by(Position.name)
    )
    candidates: list[ScopeCandidate] = []
    by_id: dict[UUID, ScopeCandidate] = {}
    for position_id, name, _department_id, _legacy_department, responsibilities, requirements, count in rows.all():
        item = ScopeCandidate(
            ref=f"position_{len(candidates) + 1}",
            type="position",
            id=position_id,
            name=name,
            employee_count=int(count or 0),
            position_ids={position_id},
        )
        item.reasons.append("position_structure")
        item.semantic_context = {
            "responsibilities": responsibilities or "",
            "requirements": requirements or "",
        }
        candidates.append(item)
        by_id[position_id] = item
    return candidates, by_id


async def _load_departments(db: AsyncSession, tenant_id: UUID) -> list[ScopeCandidate]:
    rows = await db.execute(
        select(Department.id, Department.name, Department.description, func.count(User.id))
        .outerjoin(Position, Position.department_id == Department.id)
        .outerjoin(User, (User.position_id == Position.id) & (User.role == "student") & User.is_active.is_(True) & (User.status == "active"))
        .where(Department.tenant_id == tenant_id)
        .group_by(Department.id, Department.name)
        .order_by(Department.name)
    )
    items: list[ScopeCandidate] = []
    for index, (department_id, name, description, count) in enumerate(rows.all(), start=1):
        items.append(
            ScopeCandidate(
                ref=f"department_{index}",
                type="department",
                id=department_id,
                name=name,
                employee_count=int(count or 0),
                reasons=["department_structure"],
                semantic_context={"description": description or ""},
            )
        )
    return items


async def _load_cohorts(db: AsyncSession, tenant_id: UUID) -> list[ScopeCandidate]:
    rows = await db.execute(
        select(Cohort.id, Cohort.name, Cohort.description, func.count(distinct(User.id)))
        .outerjoin(CohortMember, (CohortMember.cohort_id == Cohort.id) & (CohortMember.tenant_id == tenant_id))
        .outerjoin(User, and_(User.id == CohortMember.user_id, *_active_student_filter(tenant_id)))
        .where(Cohort.tenant_id == tenant_id, Cohort.is_active.is_(True))
        .group_by(Cohort.id, Cohort.name)
        .order_by(Cohort.name)
    )
    return [
        ScopeCandidate(
            ref=f"cohort_{index}",
            type="cohort",
            id=cohort_id,
            name=name,
            employee_count=int(count or 0),
            reasons=["cohort_structure"],
            semantic_context={"description": description or ""},
        )
        for index, (cohort_id, name, description, count) in enumerate(rows.all(), start=1)
    ]


def _course_context(course: Course) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    for module in (course.modules or [])[:MAX_MODULES]:
        lessons = [
            {
                "title": lesson.title or "",
                "content": lesson.content or "",
            }
            for lesson in (module.lessons or [])[:MAX_LESSONS_PER_MODULE]
        ]
        modules.append({"title": module.title or "", "description": module.description or "", "lessons": lessons})
    return {"title": course.title or "", "description": course.description or "", "modules": modules}


async def build_audience_snapshot(db: AsyncSession, tenant_id: UUID, course_id: UUID) -> AudienceSnapshot | None:
    course = await db.scalar(
        select(Course)
        .options(selectinload(Course.modules).selectinload(Module.lessons))
        .where(Course.id == course_id, Course.tenant_id == tenant_id)
    )
    if course is None:
        return None

    positions, positions_by_id = await _load_positions(db, tenant_id)
    departments = await _load_departments(db, tenant_id)
    cohorts = await _load_cohorts(db, tenant_id)
    warnings: list[str] = []
    candidates: list[ScopeCandidate] = []
    candidate_by_key: dict[tuple[str, UUID | None, str], ScopeCandidate] = {}

    def add_candidate(item: ScopeCandidate, *, primary: bool, reason: str, confidence: str = "high") -> ScopeCandidate:
        key = (item.type, item.id, item.name.casefold())
        existing = candidate_by_key.get(key)
        if existing is None:
            item.priority = "primary" if primary else item.priority
            item.confidence = confidence
            item.reasons = list(dict.fromkeys([*item.reasons, reason]))
            candidate_by_key[key] = item
            candidates.append(item)
            return item
        if primary:
            existing.priority = "primary"
        existing.confidence = "high" if confidence == "high" else existing.confidence
        existing.reasons = list(dict.fromkeys([*existing.reasons, reason]))
        return existing

    org_rule = await db.scalar(
        select(OrganizationCourseRule.id).where(
            OrganizationCourseRule.tenant_id == tenant_id,
            OrganizationCourseRule.course_id == course_id,
        )
    )
    active_total = int(await db.scalar(select(func.count(User.id)).where(*_active_student_filter(tenant_id))) or 0)
    add_candidate(
        ScopeCandidate("organization", "organization", None, "Вся организация", active_total),
        primary=bool(org_rule),
        reason="organization_rule" if org_rule else "organization_structure",
        confidence="high" if org_rule else "medium",
    )
    for position in positions:
        add_candidate(position, primary=False, reason="position_structure", confidence="medium")
    for department in departments:
        add_candidate(department, primary=False, reason="department_structure", confidence="medium")
    for cohort in cohorts:
        add_candidate(cohort, primary=False, reason="cohort_structure", confidence="low")

    for position_id, in (await db.execute(select(PositionCourse.position_id).where(PositionCourse.tenant_id == tenant_id, PositionCourse.course_id == course_id))).all():
        position = positions_by_id.get(position_id)
        if position:
            add_candidate(position, primary=True, reason="position_rule")
        else:
            warnings.append("missing_position_rule_target")

    department_by_id = {item.id: item for item in departments}
    for department_id, in (await db.execute(select(DepartmentCourse.department_id).where(DepartmentCourse.tenant_id == tenant_id, DepartmentCourse.course_id == course_id))).all():
        department = department_by_id.get(department_id)
        if department:
            add_candidate(department, primary=True, reason="department_rule")
        else:
            warnings.append("missing_department_rule_target")

    competency_rows = await db.execute(
        select(Competency.name, Position.id, Position.name)
        .join(CompetencyCourse, CompetencyCourse.competency_id == Competency.id)
        .join(PositionCompetency, PositionCompetency.competency_id == Competency.id)
        .join(Position, Position.id == PositionCompetency.position_id)
        .where(
            CompetencyCourse.tenant_id == tenant_id,
            CompetencyCourse.course_id == course_id,
            PositionCompetency.tenant_id == tenant_id,
            Position.tenant_id == tenant_id,
        )
    )
    for _competency_name, position_id, _position_name in competency_rows.all():
        position = positions_by_id.get(position_id)
        if position:
            add_candidate(position, primary=True, reason="competency_link")
        else:
            warnings.append("missing_competency_position_target")

    if course.source_instruction_id is not None:
        instruction_positions = await db.execute(
            select(Position.id).where(
                Position.tenant_id == tenant_id,
                Position.instruction_document_id == course.source_instruction_id,
            )
        )
        for (position_id,) in instruction_positions.all():
            position = positions_by_id.get(position_id)
            if position:
                add_candidate(position, primary=True, reason="instruction_source")
            else:
                warnings.append("missing_instruction_position_target")

    if not any(candidate.priority == "primary" for candidate in candidates):
        warnings.append("no_explicit_links")

    enrolled = int(
        await db.scalar(
            select(func.count(distinct(Enrollment.user_id))).where(
                Enrollment.tenant_id == tenant_id,
                Enrollment.course_id == course_id,
                Enrollment.status != "cancelled",
            )
        )
        or 0
    )
    return AudienceSnapshot(
        course=course,
        candidates=candidates,
        warnings=list(dict.fromkeys(warnings)),
        already_enrolled_count=enrolled,
        active_student_count=active_total,
        course_context=_course_context(course),
    )


async def _matched_count(db: AsyncSession, tenant_id: UUID, scopes: list[ScopeCandidate]) -> int:
    if any(scope.type == "organization" for scope in scopes):
        return int(await db.scalar(select(func.count(User.id)).where(*_active_student_filter(tenant_id))) or 0)
    position_ids: set[UUID] = set()
    cohort_ids: set[UUID] = set()
    for scope in scopes:
        if scope.type == "position" and scope.id:
            position_ids.add(scope.id)
        elif scope.type == "department" and scope.id:
            dept_positions = await db.execute(select(Position.id).where(Position.tenant_id == tenant_id, Position.department_id == scope.id))
            position_ids.update(dept_positions.scalars().all())
        elif scope.type == "cohort" and scope.id:
            cohort_ids.add(scope.id)
    clauses = []
    if position_ids:
        clauses.append(User.position_id.in_(position_ids))
    if cohort_ids:
        cohort_users = await db.execute(select(CohortMember.user_id).where(CohortMember.tenant_id == tenant_id, CohortMember.cohort_id.in_(cohort_ids)))
        user_ids = list(cohort_users.scalars().all())
        if user_ids:
            clauses.append(User.id.in_(user_ids))
    if not clauses:
        return 0
    from sqlalchemy import or_
    return int(await db.scalar(select(func.count(distinct(User.id))).where(*_active_student_filter(tenant_id), or_(*clauses))) or 0)


def _safe_json_object(value: str) -> dict[str, Any] | None:
    value = value.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _deterministic_scopes(snapshot: AudienceSnapshot) -> list[ScopeCandidate]:
    primary = [candidate for candidate in snapshot.candidates if candidate.priority == "primary"]
    return primary or [candidate for candidate in snapshot.candidates if candidate.type == "organization"][:1]


def _llm_select_scopes(snapshot: AudienceSnapshot, response: str) -> list[ScopeCandidate]:
    payload = _safe_json_object(response)
    if not payload:
        return []
    by_ref = {candidate.ref: candidate for candidate in snapshot.candidates}
    refs = payload.get("selected_refs")
    if not isinstance(refs, list):
        return []
    selected: list[ScopeCandidate] = []
    primary_refs = set(payload.get("primary_refs") or [])
    secondary_refs = set(payload.get("secondary_refs") or [])
    for ref in refs:
        if not isinstance(ref, str) or ref not in by_ref or by_ref[ref] in selected:
            continue
        item = by_ref[ref]
        item.priority = "primary" if ref in primary_refs or ref not in secondary_refs else "secondary"
        selected.append(item)
    return selected


def _public_scopes(scopes: list[ScopeCandidate]):
    from app.modules.ai.schemas import AudienceRecommendationScope

    return [
        AudienceRecommendationScope(
            type=scope.type,
            id=scope.id,
            name=scope.name,
            employee_count=scope.employee_count,
            priority=scope.priority,
            confidence=scope.confidence,
            reasons=scope.reasons[:3],
        )
        for scope in scopes
    ]


_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)"),
    re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}(?!\w)"),
)


def _redact_sensitive_text(value: str | None) -> str:
    """Remove direct contact identifiers before course text reaches the LLM."""
    text = value or ""
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub("[скрыто]", text)
    return text[:4000]


def _bounded_semantic_context(snapshot: AudienceSnapshot) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    course_context = {
        "title": _redact_sensitive_text(snapshot.course_context.get("title"))[:MAX_SEMANTIC_FIELD_CHARS],
        "description": _redact_sensitive_text(snapshot.course_context.get("description"))[:MAX_SEMANTIC_FIELD_CHARS],
        "modules": [],
    }
    for module in snapshot.course_context.get("modules", []):
        course_context["modules"].append(
            {
                "title": _redact_sensitive_text(module.get("title"))[:MAX_SEMANTIC_FIELD_CHARS],
                "description": _redact_sensitive_text(module.get("description"))[:MAX_SEMANTIC_FIELD_CHARS],
                "lessons": [
                    {
                        "title": _redact_sensitive_text(lesson.get("title"))[:MAX_SEMANTIC_FIELD_CHARS],
                        "content": _redact_sensitive_text(lesson.get("content"))[:MAX_SEMANTIC_FIELD_CHARS],
                    }
                    for lesson in module.get("lessons", [])[:MAX_LESSONS_PER_MODULE]
                ],
            }
        )

    ordered = sorted(snapshot.candidates, key=lambda item: item.priority != "primary")
    options: list[dict[str, Any]] = []
    for item in ordered[:MAX_CANDIDATES]:
        semantic = {
            key: _redact_sensitive_text(value)[:MAX_SEMANTIC_FIELD_CHARS]
            for key, value in item.semantic_context.items()
        }
        options.append(
            {
                "ref": item.ref,
                "type": item.type,
                "name": _redact_sensitive_text(item.name)[:MAX_SEMANTIC_FIELD_CHARS],
                "employee_count": item.employee_count,
                "evidence": item.reasons,
                "context": semantic,
            }
        )
    return course_context, options


async def recommend_audience(db: AsyncSession, tenant_id: UUID, course_id: UUID, llm=None):
    """Return an aggregate recommendation. The optional LLM only ranks known scopes."""
    snapshot = await build_audience_snapshot(db, tenant_id, course_id)
    if snapshot is None:
        return None
    selected = _deterministic_scopes(snapshot)
    used_fallback = True
    if llm is not None and snapshot.candidates:
        try:
            course_context, options = _bounded_semantic_context(snapshot)
            prompt_payload: dict[str, Any] = {"course": course_context, "candidates": []}
            for option in options:
                candidate_payload = {**prompt_payload, "candidates": [*prompt_payload["candidates"], option]}
                encoded = json.dumps(candidate_payload, ensure_ascii=False)
                if len(encoded) > MAX_LLM_PAYLOAD_CHARS and prompt_payload["candidates"]:
                    break
                prompt_payload = candidate_payload
            prompt = (
                "Choose audience scopes only from the supplied options. Never invent a scope, name, id, or count. "
                "Return JSON only: {selected_refs:[], primary_refs:[], secondary_refs:[]}. "
                "Prefer explicit rule/competency evidence over semantic guesses.\n"
                f"Bounded context: {json.dumps(prompt_payload, ensure_ascii=False)}"
            )
            response = await llm.ainvoke([{"role": "system", "content": "You are a cautious HR learning recommendation formatter."}, {"role": "user", "content": prompt}])
            llm_selected = _llm_select_scopes(snapshot, (response.content or "").strip())
            if llm_selected:
                selected = llm_selected
                used_fallback = False
        except Exception:
            logger.warning("Audience recommendation LLM failed; using deterministic fallback", exc_info=True)
    matched = await _matched_count(db, tenant_id, selected)
    from app.modules.ai.schemas import AudienceRecommendation

    warnings = list(snapshot.warnings)
    if used_fallback:
        warnings.append("Рекомендация построена по явным связям структуры компании")
    return AudienceRecommendation(
        course_status=_course_status(snapshot.course),
        recommended_scopes=_public_scopes(selected),
        matched_employee_count=matched,
        already_enrolled_count=snapshot.already_enrolled_count,
        data_warnings=list(dict.fromkeys(warnings)),
        assignment_url=f"/assignments?course_id={course_id}" if snapshot.course.status == "published" else None,
    )


def audience_prompt_reply(recommendation, language: str = "ru") -> str:
    """Human-readable status without leaking internal draft/review fields."""
    if language == "en":
        status = "published" if recommendation.course_status == "published" else "not published"
        return f"The course is {status}. I found {recommendation.matched_employee_count} matching employees; {recommendation.already_enrolled_count} already have an enrollment. Review the suggested scopes below and complete assignment on the standard screen."
    if language == "kk":
        status = "жарияланған" if recommendation.course_status == "published" else "әлі жарияланбаған"
        return f"Курс {status}. Сәйкес келетін қызметкерлер: {recommendation.matched_employee_count}; бұрын тағайындалғаны: {recommendation.already_enrolled_count}. Тізімді тексеріп, тағайындауды стандартты экранда аяқтаңыз."
    status = "опубликован" if recommendation.course_status == "published" else "ещё не опубликован"
    return f"Курс {status}. Подходящих сотрудников: {recommendation.matched_employee_count}; уже назначено: {recommendation.already_enrolled_count}. Проверьте аудиторию и завершите назначение на стандартном экране."
