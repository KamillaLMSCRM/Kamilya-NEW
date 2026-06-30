import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    UUID,
    func,
)
from sqlalchemy.orm import relationship

from app.core.db import Base

# Department is referenced via relationship("Department", ...) below.
# Import it here so SQLAlchemy's class registry knows about it before
# any mapper configuration runs.
from app.models.department import Department  # noqa: F401
# Course is referenced from Module.course = relationship("Course", ...).
# Import Course BEFORE importing lessons.models so the registry can
# resolve the string. Without this, importing positions.models
# standalone (e.g. from a test) breaks because lessons.models tries
# to resolve "Course" before Course is loaded.
from app.models.courses import Course  # noqa: F401
# Course.modules is defined as a relationship("Module", ...) in
# app.modules.courses.models. Importing lessons.models here ensures
# SQLAlchemy's class registry is populated whenever this module is
# loaded (e.g. from a test that imports assignment_service without
# first triggering the lessons module to be loaded).
from app.modules.lessons.models import Lesson, Module  # noqa: F401


class PositionCourse(Base):
    __tablename__ = "position_courses"
    __table_args__ = {'extend_existing': True}

    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    course_id = Column(UUID(as_uuid=True), primary_key=True)
    # Whether this course counts toward the position's ready_percent.
    # required=True (default): counts. required=False: enrolled but
    # excluded from the ready_percent denominator.
    required = Column(Boolean, nullable=False, default=True, server_default=func.true())


class DepartmentCourse(Base):
    """Rule binding a course to a department.

    When a user holds a position in this department, recompute_enrollments
    materializes an Enrollment for them. Same required semantics as
    PositionCourse. v1.0 ignores Department.parent_id — the rule
    applies only to the department it is attached to, not ancestors.
    """
    __tablename__ = "department_courses"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "department_id", "course_id",
            name="uq_department_courses_tenant_dept_course",
        ),
        {'extend_existing': True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    required = Column(Boolean, nullable=False, default=True, server_default=func.true())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(Text, nullable=False)
    department = Column(Text, nullable=False, default="")
    level = Column(Text, nullable=False, default="")
    responsibilities = Column(Text, nullable=False, default="")
    requirements = Column(Text, nullable=False, default="")
    course_id = Column(UUID(as_uuid=True), nullable=True)  # legacy, kept for backward compat
    employee_count = Column(Integer, nullable=False, default=0)
    # FK to normalized Department (ADR-0011). Column was added in
    # migration 0035; the ORM was missing it until B1a.
    department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    courses = relationship("PositionCourse", primaryjoin="Position.id == PositionCourse.position_id", cascade="all, delete-orphan")
    # Note: 'department' above is a Column (text) used for legacy rows.
    # The normalised FK relationship must use a different attribute name,
    # otherwise SQLAlchemy treats the second declaration as overriding the
    # first, and any handler that passes a string for `department` crashes
    # with `AttributeError: 'str' object has no attribute '_sa_instance_state'`.
    # Renamed to `department_obj` to keep both accessible. (Lesson 19.)
    department_obj = relationship("Department", lazy="joined")


class PositionJDVersion(Base):
    """Snapshot of position.responsibilities + position.requirements.

    Inserted automatically before a PUT that changes them, or manually
    via POST /positions/{id}/jd-versions.
    """
    __tablename__ = "position_jd_versions"
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    responsibilities = Column(Text, nullable=False, default="")
    requirements = Column(Text, nullable=False, default="")
    created_by = Column(UUID(as_uuid=True), nullable=True)  # user.id or NULL for system
    source = Column(String(32), nullable=False, default="auto")  # "auto" | "manual"
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PositionQuiz(Base):
    """Onboarding quiz for a position (Phase 3).

    One quiz per position (1-to-1 via unique position_id). Generated
    by AI from the position's responsibilities + requirements, then
    edited by the methodologist and saved here.

    Questions are stored as a JSON column for v1 (simpler than a
    proper Question/QuizChoice table pair, and the methodologist edits
    them inline in the modal before saving). A separate table pair can
    be added in v1.1 if we need attempts/history.

    Shape of `questions` JSON (list):
    [
      {
        "text": "Что обязан делать кассир при обнаружении подозрительной купюры?",
        "type": "MCQ",
        "explanation": "По правилам ЦБ РК кассир обязан вызвать старшего и не возвращать купюру клиенту.",
        "choices": [
          {"text": "...", "is_correct": false},
          {"text": "...", "is_correct": true},
        ]
      },
      ...
    ]

    is_active toggles whether this quiz is auto-assigned on onboarding.
    """
    __tablename__ = "position_quizzes"
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    position_id = Column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="Онбординг-тест")
    pass_score = Column(Integer, nullable=False, default=80)  # percent
    time_limit = Column(Integer, nullable=True)  # minutes, NULL = unlimited
    questions = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)  # user.id who first generated/saved it
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
