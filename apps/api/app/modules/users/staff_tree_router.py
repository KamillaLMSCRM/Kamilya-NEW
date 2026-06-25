"""Staff tree view endpoint — departments → positions → employees with progress.

Stage 1e of employee onboarding epic.

GET /admin/staff/tree returns a nested structure:
- departments: [{name, position_count, employee_count, ready_pct, positions: [...]}]
- positions: [{id, name, employee_count, ready_pct, employees: [...]}]
- employees: [{id, full_name, personnel_number, is_active, status, assigned, completed, ready_pct}]

Progress metric:
- assigned = count of courses in position_courses + direct enrollments
- completed = count of enrollments with completed_at IS NOT NULL
- ready_pct = completed / assigned * 100 (0 if no assignments)

Used by /admin/employees page to render an expandable tree.
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

router = APIRouter(prefix="/admin/staff", tags=["staff-tree"])


class EmployeeTreeNode(BaseModel):
    id: str
    full_name: str
    personnel_number: str | None = None
    is_active: bool
    assigned_courses: int = 0
    completed_courses: int = 0
    ready_percent: int = 0  # 0..100


class PositionTreeNode(BaseModel):
    id: str
    name: str
    department: str
    employee_count: int
    ready_percent: int
    employees: list[EmployeeTreeNode]


class DepartmentTreeNode(BaseModel):
    name: str  # department name (free text, may differ across positions)
    position_count: int
    employee_count: int
    ready_percent: int
    positions: list[PositionTreeNode]


class TreeResponse(BaseModel):
    departments: list[DepartmentTreeNode]
    summary: dict


@router.get("/tree", response_model=TreeResponse)
async def get_staff_tree(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Return nested tree of departments → positions → employees with progress."""
    # 1. Load all positions in tenant (with their courses)
    pos_result = await db.execute(
        select(Position)
        .where(Position.tenant_id == user.tenant_id)
        .order_by(Position.department, Position.name)
    )
    positions = pos_result.scalars().all()

    # 2. Load all employees with position_id (active users in tenant)
    users_result = await db.execute(
        select(User)
        .where(
            User.tenant_id == user.tenant_id,
            User.position_id.is_not(None),
        )
    )
    employees = users_result.scalars().all()
    employees_by_pos: dict[UUID, list[User]] = {}
    for emp in employees:
        employees_by_pos.setdefault(emp.position_id, []).append(emp)

    # 3. Position courses (count per position)
    pc_result = await db.execute(
        select(PositionCourse.position_id, func.count(PositionCourse.course_id))
        .where(PositionCourse.position_id.in_([p.id for p in positions] or [UUID("00000000-0000-0000-0000-000000000000")]))
        .group_by(PositionCourse.position_id)
    )
    pc_count_by_pos = {row[0]: row[1] for row in pc_result.all()}

    # 4. Enrollments: per user, list of (course_id, completed_at)
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

    # 5. Build tree
    dept_map: dict[str, DepartmentTreeNode] = {}

    for pos in positions:
        dept_name = (pos.department or "(без отдела)").strip() or "(без отдела)"
        if dept_name not in dept_map:
            dept_map[dept_name] = DepartmentTreeNode(
                name=dept_name,
                position_count=0,
                employee_count=0,
                ready_percent=0,
                positions=[],
            )
        dept_node = dept_map[dept_name]
        dept_node.position_count += 1

        # Employees in this position
        pos_employees = employees_by_pos.get(pos.id, [])
        required_courses = pc_count_by_pos.get(pos.id, 0)

        emp_nodes: list[EmployeeTreeNode] = []
        pos_completed_sum = 0
        pos_assigned_sum = 0
        for emp in pos_employees:
            enr = enrollments_by_user.get(emp.id, [])
            assigned = required_courses + len(enr)  # position_courses + direct enrollments
            completed = sum(1 for _, is_done in enr if is_done)
            ready_pct = int(completed * 100 / assigned) if assigned > 0 else 0

            pos_assigned_sum += assigned
            pos_completed_sum += completed

            emp_nodes.append(EmployeeTreeNode(
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

        # Update dept aggregates
        dept_node.employee_count += emp_count
        # We'll calculate dept ready_pct after all positions processed

        dept_node.positions.append(PositionTreeNode(
            id=str(pos.id),
            name=pos.name,
            department=pos.department or "",
            employee_count=emp_count,
            ready_percent=pos_ready_pct,
            employees=emp_nodes,
        ))

    # Calculate dept ready_pcts (weighted by employee count)
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

    # Convert to list (sorted by name)
    dept_list = sorted(dept_map.values(), key=lambda d: d.name)

    summary = {
        "total_employees": total_emp,
        "total_departments": len(dept_list),
        "total_positions": sum(d.position_count for d in dept_list),
        "overall_ready_percent": int(total_completed * 100 / total_assigned) if total_assigned > 0 else 0,
        "total_assigned_courses": total_assigned,
        "total_completed_courses": total_completed,
    }

    return TreeResponse(departments=dept_list, summary=summary)
