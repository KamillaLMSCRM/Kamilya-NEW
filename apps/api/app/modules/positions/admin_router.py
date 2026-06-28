"""Positions admin router — staff tree, department management.

ADR-0011 consolidation: this router absorbs the role previously
filled by `apps/api/app/modules/users/staff_tree_router.py`. The
old endpoint stays live as `/admin/staff/tree` (handled in
`apps/api/app/modules/users/staff_tree_router.py` with a thin
shim) but the canonical path is now `/admin/staff/structure` under
the positions module's admin namespace.

Why: the tree is structurally about positions (Position.department
→ Position → User), not generic user management. Co-locating it
with the rest of position CRUD also lets us add department-list
endpoints next to it without dragging in a `users/staff` dependency.
"""
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.positions.models import Position, PositionCourse

router = APIRouter(prefix="/admin/staff", tags=["staff-structure"])


class EmployeeNode(BaseModel):
    id: str
    full_name: str
    personnel_number: str | None = None
    is_active: bool
    assigned_courses: int = 0
    completed_courses: int = 0
    ready_percent: int = 0


class PositionNode(BaseModel):
    id: str
    name: str
    department: str
    department_slug: str | None = None  # ADR-0011: normalized
    employee_count: int
    ready_percent: int
    employees: list[EmployeeNode]


class DepartmentNode(BaseModel):
    id: str | None = None
    name: str
    slug: str
    position_count: int
    employee_count: int
    ready_percent: int
    positions: list[PositionNode]


class StructureResponse(BaseModel):
    departments: list[DepartmentNode]
    summary: dict


@router.get("/structure", response_model=StructureResponse)
async def get_staff_structure(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "teacher")),
):
    """Return nested tree: departments → positions → employees with progress.

    ADR-0011: department is normalized via the `departments` table when
    Position.department_id is set, falling back to lower(Position.department)
    grouping for legacy rows where the FK is NULL.
    """
    from app.models.department import Department  # ADR-0011

    # 1. Load positions + departments (LEFT JOIN to include legacy rows).
    pos_result = await db.execute(
        select(Position, Department)
        .outerjoin(Department, Position.department_id == Department.id)
        .where(Position.tenant_id == user.tenant_id)
        .order_by(Department.slug.nullslast(), Position.name)
    )
    pos_with_dept = pos_result.all()

    # 2. Employees with position_id (active in tenant).
    employees_result = await db.execute(
        select(User).where(
            User.tenant_id == user.tenant_id,
            User.position_id.is_not(None),
        )
    )
    employees = employees_result.scalars().all()
    employees_by_pos: dict[UUID, list[User]] = {}
    for emp in employees:
        employees_by_pos.setdefault(emp.position_id, []).append(emp)

    # 3. Position courses count.
    pc_result = await db.execute(
        select(PositionCourse.position_id, func.count(PositionCourse.course_id))
        .where(PositionCourse.position_id.in_([p.id for p, _ in pos_with_dept] or [UUID("00000000-0000-0000-0000-000000000000")]))
        .group_by(PositionCourse.position_id)
    )
    pc_count_by_pos = {row[0]: row[1] for row in pc_result.all()}

    # 4. Enrollments.
    user_ids = [e.id for e in employees]
    enr_result = await db.execute(
        select(Enrollment.user_id, Enrollment.course_id, Enrollment.completed_at)
        .where(
            Enrollment.user_id.in_(user_ids) if user_ids else Enrollment.user_id == None,
            Enrollment.tenant_id == user.tenant_id,
        )
    )
    enrollments_by_user: dict[UUID, list[tuple[UUID, bool]]] = {}
    for row in enr_result.all():
        enrollments_by_user.setdefault(row[0], []).append((row[1], row[2] is not None))

    # 5. Group positions by department (use Department.slug if FK set,
    #    else fall back to lower(trim(Position.department))).
    dept_map: dict[str, DepartmentNode] = {}

    for pos, dept in pos_with_dept:
        if dept is not None:
            dept_key = dept.slug
            dept_name = dept.name
            dept_id = str(dept.id)
        else:
            legacy_text = (pos.department or "").strip()
            dept_key = legacy_text.lower() or "(no-department)"
            dept_name = legacy_text or "(без отдела)"
            dept_id = None

        if dept_key not in dept_map:
            dept_map[dept_key] = DepartmentNode(
                id=dept_id,
                name=dept_name,
                slug=dept_key,
                position_count=0,
                employee_count=0,
                ready_percent=0,
                positions=[],
            )
        dept_node = dept_map[dept_key]
        dept_node.position_count += 1

        pos_employees = employees_by_pos.get(pos.id, [])
        required_courses = pc_count_by_pos.get(pos.id, 0)

        emp_nodes: list[EmployeeNode] = []
        pos_completed_sum = 0
        pos_assigned_sum = 0
        for emp in pos_employees:
            enr = enrollments_by_user.get(emp.id, [])
            assigned = required_courses + len(enr)
            completed = sum(1 for _, is_done in enr if is_done)
            ready_pct = int(completed * 100 / assigned) if assigned > 0 else 0
            pos_assigned_sum += assigned
            pos_completed_sum += completed

            emp_nodes.append(EmployeeNode(
                id=str(emp.id),
                full_name=f"{emp.last_name} {emp.first_name}".strip(),
                personnel_number=emp.personnel_number,
                is_active=emp.is_active,
                assigned_courses=assigned,
                completed_courses=completed,
                ready_percent=ready_pct,
            ))

        pos_ready_pct = int(pos_completed_sum * 100 / pos_assigned_sum) if pos_assigned_sum > 0 else 0
        emp_count = len(emp_nodes)
        dept_node.employee_count += emp_count

        dept_node.positions.append(PositionNode(
            id=str(pos.id),
            name=pos.name,
            department=dept_node.name,
            department_slug=dept_key,
            employee_count=emp_count,
            ready_percent=pos_ready_pct,
            employees=emp_nodes,
        ))

    # 6. Compute department rollups.
    total_emp = 0
    total_assigned = 0
    total_completed = 0
    for dept in dept_map.values():
        assigned_sum = 0
        completed_sum = 0
        for p in dept.positions:
            for e in p.employees:
                assigned_sum += e.assigned_courses
                completed_sum += e.completed_courses
        dept.ready_percent = int(completed_sum * 100 / assigned_sum) if assigned_sum > 0 else 0
        total_emp += dept.employee_count
        total_assigned += assigned_sum
        total_completed += completed_sum

    summary = {
        "total_employees": total_emp,
        "total_departments": len(dept_map),
        "total_positions": sum(d.position_count for d in dept_map.values()),
        "overall_ready_percent": int(total_completed * 100 / total_assigned) if total_assigned > 0 else 0,
        "total_assigned_courses": total_assigned,
        "total_completed_courses": total_completed,
    }

    return StructureResponse(
        departments=sorted(dept_map.values(), key=lambda d: d.slug),
        summary=summary,
    )