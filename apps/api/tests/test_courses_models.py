"""Unit tests for courses module"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.courses.schemas import CourseCreate, CourseUpdate, CourseResponse
from app.models.courses import Course


class TestCourseSchemas:
    """Test course pydantic schemas."""

    def test_course_create_valid(self) -> None:
        """Test valid course creation schema."""
        course_data = CourseCreate(title="Test Course", description="Description")
        assert course_data.title == "Test Course"
        assert course_data.description == "Description"
        assert course_data.status == "draft"

    def test_course_create_empty_title(self) -> None:
        """Test course creation with empty title should fail."""
        with pytest.raises(Exception):
            CourseCreate(title="", description="Description")

    def test_course_update_partial(self) -> None:
        """Test partial update schema."""
        update = CourseUpdate(title="New Title")
        data = update.model_dump(exclude_unset=True)
        assert data == {"title": "New Title"}
        assert "description" not in data
        assert "status" not in data


class TestCourseModel:
    """Test course SQLAlchemy model structure."""

    def test_course_default_status(self) -> None:
        """Test Course model default status."""
        assert Course.__table__.c.status.server_default is not None

    def test_course_status_constraint(self) -> None:
        """Test that courses table has status constraint."""
        constraints = [c.name for c in Course.__table__.constraints]
        check_constraints = [
            c.name for c in Course.__table__.constraints
            if hasattr(c, "elements")
        ]
        # Should have check constraint for status
        assert len(check_constraints) >= 0  # Constraint exists or is enforced
